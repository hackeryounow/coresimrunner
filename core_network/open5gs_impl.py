"""
Open5GS implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Open5GS,
using configuration from .env and JSON files.

When ENABLE_IMS is true, provisioning uses the REST API directly:
  1. Ensure APNs (internet + ims) exist
  2. For each UE: create AuC → create subscriber → create IMS subscriber
When ENABLE_IMS is false, provisioning uses the legacy WebUI JSON API.
"""

import json
import time
import copy
from typing import Dict, Any, Tuple, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
from loguru import logger
from coresimrunner.core_network.core_network import CoreNetwork


class Open5GS(CoreNetwork):
    """Open5GS implementation of the CoreNetwork interface."""

    def __init__(self, config_loader):
        super().__init__("open5gs", config_loader)
        self.core_ip = self.network_config["ip"]
        self.webui_port = self.network_config["webui_port"]
        self.csrf_url = f"http://{self.core_ip}:{self.webui_port}/api/auth/csrf"
        self.login_url = f"http://{self.core_ip}:{self.webui_port}/api/auth/login"
        self.session_url = f"http://{self.core_ip}:{self.webui_port}/api/auth/session"
        self.subscriber_url = f"http://{self.core_ip}:{self.webui_port}/api/db/Subscriber"
        self.subscription_template = self.network_config["subscription_template"]
        self.plmn_id = self.network_config["plmn_id"]
        self.username = self.network_config["username"]
        self.password = self.network_config["password"]
        self.msisdn_prefixes: List[str] = self.network_config.get("msisdn_prefixes", ["133"])
        self.msisdn_length: int = self.network_config.get("msisdn_length", 11)
        self.enable_ims: bool = self.network_config.get("enable_ims", False)
        self.permanent_key: str = config_loader.get("PERMANENT_KEY", "8baf473f2f8fd09487cccbd7097c6862")
        self.opc_value: str = config_loader.get("OPC_VALUE", "8e27b6af0e692e750f32667a3b14605d")
        self.amf: str = config_loader.get("AMF", "8000")
        self.mcc = config_loader.get_mcc()
        self.mnc = config_loader.get_mnc()
        self.rest_base = f"http://{self.core_ip}:8080"

    def _authenticate(self) -> requests.Session:
        session = requests.Session()
        try:
            csrf_response = session.get(self.csrf_url, timeout=30)
            csrf_data = csrf_response.json()
            csrf_token = csrf_data['csrfToken']
            login_data = {"username": self.username, "password": self.password}
            login_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-Csrf-Token": csrf_token
            }
            login_response = session.post(self.login_url, data=json.dumps(login_data), headers=login_headers, timeout=30)
            if login_response.status_code != 200:
                logger.error(f"Failed to authenticate with Open5GS: HTTP {login_response.status_code}")
                return None
            session_response = session.get(self.session_url, timeout=30)
            session_data = session_response.json()
            auth_token = session_data['authToken']
            session.headers.update({
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "X-Csrf-Token": session_data['csrfToken'],
                "Authorization": f"Bearer {auth_token}"
            })
            logger.info("Successfully authenticated with Open5GS")
            return session
        except requests.exceptions.RequestException as e:
            logger.error(f"Authentication error: {e}")
            return None
        except KeyError as e:
            logger.error(f"Missing expected data in Open5GS response: {e}")
            return None

    def _generate_msisdn(self, imsi_index: int) -> str:
        suffix_len = self.msisdn_length - len(self.msisdn_prefixes[0])
        max_per_prefix = 10 ** suffix_len
        adjusted = imsi_index - 1
        prefix_idx = adjusted // max_per_prefix
        suffix_idx = adjusted % max_per_prefix
        prefix = self.msisdn_prefixes[prefix_idx % len(self.msisdn_prefixes)]
        return f"{prefix}{suffix_idx:0{suffix_len}d}"

    # ── IMS Provision: REST API methods ──

    def _ensure_apns(self) -> Optional[Tuple[int, int]]:
        """Ensure internet and ims APNs exist. Returns (internet_apn_id, ims_apn_id) or None."""
        try:
            resp = requests.get(f"{self.rest_base}/apn/list?page=0&page_size=200", timeout=30)
            if resp.status_code != 200:
                logger.error(f"Failed to list APNs: HTTP {resp.status_code}")
                return None
            existing = resp.json()
            apn_map = {a["apn"]: a["apn_id"] for a in existing}

            for apn_name in ["internet", "ims"]:
                if apn_name not in apn_map:
                    logger.info(f"Creating APN: {apn_name}")
                    create_resp = requests.put(
                        f"{self.rest_base}/apn/",
                        json={"apn": apn_name, "apn_ambr_dl": 0, "apn_ambr_ul": 0},
                        timeout=30,
                    )
                    if create_resp.status_code not in (200, 201):
                        logger.error(f"Failed to create APN '{apn_name}': HTTP {create_resp.status_code}")
                        return None
                    created = create_resp.json()
                    apn_map[apn_name] = created["apn_id"]
                    logger.info(f"Created APN '{apn_name}' with apn_id={created['apn_id']}")

            internet_id = apn_map.get("internet")
            ims_id = apn_map.get("ims")
            if internet_id is None or ims_id is None:
                logger.error("Missing required APN IDs after ensure")
                return None
            return internet_id, ims_id
        except Exception as e:
            logger.error(f"Error ensuring APNs: {e}")
            return None

    def _create_auc(self, imsi: str) -> Optional[int]:
        """Create AuC entry. Returns auc_id or None."""
        try:
            resp = requests.put(
                f"{self.rest_base}/auc/",
                json={"ki": self.permanent_key, "opc": self.opc_value, "amf": self.amf, "sqn": 0, "imsi": imsi},
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                logger.error(f"Failed to create AuC for {imsi}: HTTP {resp.status_code}")
                return None
            auc_id = resp.json()["auc_id"]
            logger.debug(f"Created AuC for {imsi}: auc_id={auc_id}")
            return auc_id
        except Exception as e:
            logger.error(f"Error creating AuC for {imsi}: {e}")
            return None

    def _create_subscriber(self, imsi: str, msisdn: str, auc_id: int, internet_apn_id: int, ims_apn_id: int) -> bool:
        """Create subscriber entry."""
        try:
            resp = requests.put(
                f"{self.rest_base}/subscriber/",
                json={
                    "imsi": imsi,
                    "enabled": True,
                    "auc_id": auc_id,
                    "default_apn": internet_apn_id,
                    "apn_list": f"{internet_apn_id},{ims_apn_id}",
                    "msisdn": msisdn,
                    "ue_ambr_dl": 0,
                    "ue_ambr_ul": 0,
                },
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                logger.error(f"Failed to create subscriber for {imsi}: HTTP {resp.status_code} {resp.text}")
                return False
            logger.debug(f"Created subscriber for {imsi}")
            return True
        except Exception as e:
            logger.error(f"Error creating subscriber for {imsi}: {e}")
            return False

    def _create_ims_subscriber(self, imsi: str, msisdn: str) -> bool:
        """Create IMS subscriber entry."""
        mnc_padded = self.mnc.zfill(3)
        realm = f"ims.mnc{mnc_padded}.mcc{self.mcc}.3gppnetwork.org"
        scscf_peer = f"scscf.{realm}"
        scscf = f"sip:{scscf_peer}:6060"
        try:
            resp = requests.put(
                f"{self.rest_base}/ims_subscriber/",
                json={
                    "imsi": imsi,
                    "msisdn": msisdn,
                    "sh_profile": "string",
                    "scscf_peer": scscf_peer,
                    "msisdn_list": f"[{msisdn}]",
                    "ifc_path": "default_ifc.xml",
                    "scscf": scscf,
                    "scscf_realm": realm,
                },
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                logger.error(f"Failed to create IMS subscriber for {imsi}: HTTP {resp.status_code} {resp.text}")
                return False
            logger.debug(f"Created IMS subscriber for {imsi}")
            return True
        except Exception as e:
            logger.error(f"Error creating IMS subscriber for {imsi}: {e}")
            return False

    # ── Provision one UE ──

    def _provision_one_ims(self, imsi_index: int, internet_apn_id: int, ims_apn_id: int) -> Tuple[int, bool]:
        """Provision a single UE via REST API (IMS mode). Returns (index, success)."""
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        msisdn = self._generate_msisdn(imsi_index)

        auc_id = self._create_auc(imsi)
        if auc_id is None:
            return imsi_index, False

        if not self._create_subscriber(imsi, msisdn, auc_id, internet_apn_id, ims_apn_id):
            return imsi_index, False

        if not self._create_ims_subscriber(imsi, msisdn):
            return imsi_index, False

        return imsi_index, True

    def _provision_one(self, session: requests.Session, imsi_index: int) -> Tuple[int, bool]:
        """Provision a single subscription via WebUI JSON API (non-IMS mode). Returns (index, success)."""
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        subscription_data = copy.deepcopy(self.subscription_template)
        subscription_data["imsi"] = imsi
        msisdn = self._generate_msisdn(imsi_index)
        subscription_data["msisdn"] = [msisdn]
        try:
            resp = session.post(self.subscriber_url, data=json.dumps(subscription_data), timeout=30)
            if resp.status_code == 201:
                return imsi_index, True
        except Exception:
            pass
        return imsi_index, False

    def _delete_one(self, session: requests.Session, imsi_index: int) -> Tuple[int, bool]:
        """Delete a single subscription (thread-safe via session). Returns (index, success)."""
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        delete_url = f"{self.subscriber_url}/{imsi}"
        try:
            resp = session.delete(delete_url, timeout=30)
            if resp.status_code in (200, 204):
                return imsi_index, True
        except Exception:
            pass
        return imsi_index, False

    # ── Batch provision / delete ──

    def provision_subscriptions(self, count: int) -> bool:
        if self.enable_ims:
            return self._provision_ims(count)
        return self._provision_legacy(count)

    def _provision_ims(self, count: int) -> bool:
        """Provision subscriptions with IMS support via REST API."""
        apn_ids = self._ensure_apns()
        if apn_ids is None:
            logger.error("Failed to ensure APNs, aborting IMS provision")
            return False
        internet_apn_id, ims_apn_id = apn_ids
        logger.info(f"APNs ready: internet={internet_apn_id}, ims={ims_apn_id}")

        start_index = self._get_initial_imsi_index()
        indices = list(range(start_index, start_index + count))
        failed = []
        with ThreadPoolExecutor(max_workers=min(count, 10)) as pool:
            futures = {pool.submit(self._provision_one_ims, idx, internet_apn_id, ims_apn_id): idx for idx in indices}
            with tqdm(total=count, desc="Provisioning(IMS)", unit="sub", ncols=80) as pbar:
                for f in as_completed(futures):
                    idx, ok = f.result()
                    if not ok:
                        failed.append(idx)
                    pbar.update(1)
        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0

    def _provision_legacy(self, count: int) -> bool:
        """Provision subscriptions via WebUI JSON API (legacy)."""
        session = self._authenticate()
        if not session:
            return False
        start_index = self._get_initial_imsi_index()
        indices = list(range(start_index, start_index + count))
        failed = []
        with ThreadPoolExecutor(max_workers=min(count, 20)) as pool:
            futures = {pool.submit(self._provision_one, session, idx): idx for idx in indices}
            with tqdm(total=count, desc="Provisioning", unit="sub", ncols=80) as pbar:
                for f in as_completed(futures):
                    idx, ok = f.result()
                    if not ok:
                        failed.append(idx)
                    pbar.update(1)
        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0

    def delete_subscriptions(self, count: int) -> bool:
        session = self._authenticate()
        if not session:
            logger.error("Authentication failed, cannot delete subscriptions")
            return False
        start_index = self._get_initial_imsi_index()
        indices = list(range(start_index, start_index + count))
        failed = []
        with ThreadPoolExecutor(max_workers=min(count, 20)) as pool:
            futures = {pool.submit(self._delete_one, session, idx): idx for idx in indices}
            with tqdm(total=count, desc="Deleting", unit="sub", ncols=80) as pbar:
                for f in as_completed(futures):
                    idx, ok = f.result()
                    if not ok:
                        failed.append(idx)
                    pbar.update(1)
        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0
