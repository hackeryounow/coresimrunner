"""
Open5GS implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Open5GS,
using configuration from .env and JSON files.

When ENABLE_IMS=true, each subscriber is also provisioned to the
PyHSS API (APN, AuC, Subscriber, IMS Subscriber) so that IMS
registration works end-to-end.
"""

import json
import time
from typing import Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
from loguru import logger
from coresimrunner.core_network.core_network import CoreNetwork
from coresimrunner.core_network.pyhss_client import PyHSSClient


class Open5GS(CoreNetwork):
    """Open5GS implementation of the CoreNetwork interface."""
    
    def __init__(self, config_loader):
        """Initialize Open5GS implementation.
        
        Args:
            config_loader: Configuration loader instance
        """
        super().__init__("open5gs", config_loader)
        self.csrf_url = f"http://{self.network_config['ip']}:{self.network_config['webui_port']}/api/auth/csrf"
        self.login_url = f"http://{self.network_config['ip']}:{self.network_config['webui_port']}/api/auth/login"
        self.session_url = f"http://{self.network_config['ip']}:{self.network_config['webui_port']}/api/auth/session"
        self.subscriber_url = f"http://{self.network_config['ip']}:{self.network_config['webui_port']}/api/db/Subscriber"
        self.subscription_template = self.network_config["subscription_template"]
        self.plmn_id = self.network_config["plmn_id"]
        self.username = self.network_config["username"]
        self.password = self.network_config["password"]

        # IMS provisioning via PyHSS
        self.enable_ims = config_loader.get("ENABLE_IMS", "false").lower() == "true"
        if self.enable_ims:
            pyhss_port = config_loader.get("PYHSS_PORT", "8080")
            pyhss_base = f"http://{self.network_config['ip']}:{pyhss_port}"
            self.pyhss = PyHSSClient(
                base_url=pyhss_base,
                mcc=self.network_config["mcc"],
                mnc=self.network_config["mnc"],
            )
            self.ki = config_loader.get("PERMANENT_KEY", "")
            self.opc = config_loader.get("OPC_VALUE", "")
            self.amf = config_loader.get("AMF", "8000")
            logger.info(f"IMS provisioning enabled (PyHSS: {pyhss_base})")
        else:
            self.pyhss = None
    
    def _authenticate(self) -> requests.Session:
        """Authenticate with Open5GS and return authenticated session.
        
        Returns:
            requests.Session: Authenticated session or None if authentication failed
        """
        session = requests.Session()
        
        try:
            # Get CSRF token
            csrf_response = session.get(self.csrf_url, timeout=30)
            
            csrf_data = csrf_response.json()
            csrf_token = csrf_data['csrfToken']
            
            # Login
            login_data = {"username": self.username, "password": self.password}
            login_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
                "X-Csrf-Token": csrf_token
            }
            
            login_response = session.post(
                self.login_url,
                data=json.dumps(login_data),
                headers=login_headers,
                timeout=30
            )
            
            if login_response.status_code != 200:
                logger.error(f"Failed to authenticate with Open5GS: HTTP {login_response.status_code}")
                return None
            
            # Get session information
            session_response = session.get(self.session_url, timeout=30)
            session_data = session_response.json()
            auth_token = session_data['authToken']
            
            # Set up authenticated headers
            session.headers.update({
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
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
    
    def _derive_msisdn(self, imsi_index: int) -> str:
        """Derive MSISDN from IMSI index.

        Uses the msisdn pattern from the subscription template
        (e.g., '13300000001' for index 1).

        Args:
            imsi_index: Numeric IMSI index

        Returns:
            MSISDN string
        """
        template_msisdn = self.subscription_template.get("msisdn", ["13300000001"])
        if template_msisdn and len(template_msisdn) > 0:
            # Use prefix from template (first 3 digits) + zero-padded index
            prefix = template_msisdn[0][:3]
            return f"{prefix}{imsi_index:08d}"
        return f"133{imsi_index:08d}"

    def _provision_one(self, session: requests.Session, imsi_index: int) -> Tuple[int, bool]:
        """Provision a single subscription (thread-safe via session). Returns (index, success)."""
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        subscription_data = self.subscription_template.copy()
        subscription_data["imsi"] = imsi
        try:
            resp = session.post(self.subscriber_url, data=json.dumps(subscription_data), timeout=30)
            if resp.status_code == 201:
                # Also provision to PyHSS for IMS
                if self.enable_ims and self.pyhss:
                    self._provision_pyhss(imsi, imsi_index)
                return imsi_index, True
        except Exception as e:
            logger.error(f"Open5GS provisioning failed for {imsi}: {e}")
        return imsi_index, False

    def _provision_pyhss(self, imsi: str, imsi_index: int):
        """Provision IMS data to PyHSS. Errors are logged but never propagated."""
        if self._pyhss_apn_ids is None:
            logger.warning(f"PyHSS APN IDs not available, skipping IMS for {imsi}")
            return
        internet_id, ims_id = self._pyhss_apn_ids
        try:
            msisdn = self._derive_msisdn(imsi_index)
            logger.debug(f"PyHSS provisioning {imsi} (msisdn={msisdn})")
            ims_ok = self.pyhss.provision_ims_subscriber(
                imsi=imsi,
                msisdn=msisdn,
                ki=self.ki,
                opc=self.opc,
                amf=self.amf,
                internet_apn_id=internet_id,
                ims_apn_id=ims_id,
            )
            if not ims_ok:
                logger.warning(
                    f"Open5GS OK but PyHSS IMS provisioning failed for {imsi}"
                )
        except Exception as e:
            logger.error(f"PyHSS IMS provisioning error for {imsi}: {e}")

    def _delete_one(self, session: requests.Session, imsi_index: int) -> Tuple[int, bool]:
        """Delete a single subscription (thread-safe via session). Returns (index, success).

        Deletion order: PyHSS IMS data first (ims_subscriber -> subscriber -> auc),
        then the Open5GS WebUI subscriber.
        """
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        # Delete PyHSS IMS data first
        if self.enable_ims and self.pyhss:
            self.pyhss.delete_subscriber(imsi)
        delete_url = f"{self.subscriber_url}/{imsi}"
        try:
            resp = session.delete(delete_url, timeout=30)
            if resp.status_code in (200, 204):
                return imsi_index, True
        except Exception:
            pass
        return imsi_index, False

    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to Open5GS using concurrent threads."""
        session = self._authenticate()
        if not session:
            return False

        # Ensure PyHSS APNs exist once before provisioning any subscribers
        self._pyhss_apn_ids = None
        if self.enable_ims and self.pyhss:
            internet_id, ims_id = self.pyhss.ensure_apns()
            if internet_id is not None and ims_id is not None:
                self._pyhss_apn_ids = (internet_id, ims_id)
                logger.info(
                    f"PyHSS APNs ready: internet={internet_id}, ims={ims_id}"
                )
            else:
                logger.error("PyHSS APN setup failed, IMS provisioning will be skipped")

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
        """Delete subscriptions from Open5GS using concurrent threads."""
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

        # Delete PyHSS APNs once after all subscribers are removed
        if self.enable_ims and self.pyhss:
            if not self.pyhss.delete_apns():
                logger.warning("PyHSS APN deletion had failures")

        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0

    def _delete_webui_one(self, session: requests.Session, subscriber: Dict[str, Any]) -> Tuple[str, bool]:
        """Delete a single WebUI subscriber entry by IMSI. Returns (imsi, success)."""
        imsi = subscriber.get("imsi", "")
        try:
            resp = session.delete(f"{self.subscriber_url}/{imsi}", timeout=30)
            if resp.status_code in (200, 204):
                return imsi, True
            logger.error(f"WebUI delete failed for {imsi}: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"WebUI delete error for {imsi}: {e}")
        return imsi, False

    def _delete_all_webui_subscribers(self) -> bool:
        """Query the WebUI subscriber database and delete every entry.

        Returns:
            True if all subscribers were deleted, False otherwise.
        """
        session = self._authenticate()
        if not session:
            logger.error("Authentication failed, cannot delete WebUI subscribers")
            return False

        try:
            resp = session.get(self.subscriber_url, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Failed to query WebUI subscribers: HTTP {resp.status_code}")
                return False
            subscribers = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"WebUI subscriber query error: {e}")
            return False

        if not isinstance(subscribers, list) or not subscribers:
            logger.info("Open5GS WebUI: no subscribers found")
            return True

        total = len(subscribers)
        logger.info(f"Open5GS WebUI: deleting {total} subscribers...")
        failed = []
        with ThreadPoolExecutor(max_workers=min(total, 20)) as pool:
            futures = {pool.submit(self._delete_webui_one, session, sub): sub for sub in subscribers}
            with tqdm(total=total, desc="Deleting", unit="sub", ncols=80) as pbar:
                for f in as_completed(futures):
                    imsi, ok = f.result()
                    if not ok:
                        failed.append(imsi)
                    pbar.update(1)
        if failed:
            logger.warning(f"Open5GS WebUI delete failed for {len(failed)}/{total}: {failed}")
            return False
        return True

    def delete_all_subscriptions(self) -> bool:
        """Delete ALL subscriptions from PyHSS and Open5GS WebUI.

        Deletion order:
          1. PyHSS ims_subscriber, 2. PyHSS subscriber,
          3. PyHSS auc, 4. PyHSS apn,
          5. every Open5GS WebUI subscriber.

        Returns:
            True on success, False otherwise.
        """
        logger.info("Deleting ALL subscriptions (PyHSS + Open5GS WebUI)...")
        ok = True

        # 1. Delete all from PyHSS first (ims_subscriber -> subscriber -> auc -> apn)
        if self.enable_ims and self.pyhss:
            if not self.pyhss.delete_all():
                logger.warning("PyHSS delete_all had failures")
                ok = False
            else:
                logger.info("PyHSS: all IMS data deleted")

        # 2. Delete all Open5GS WebUI subscribers
        if not self._delete_all_webui_subscribers():
            logger.warning("Open5GS WebUI delete-all had failures")
            ok = False
        else:
            logger.info("Open5GS WebUI: all subscribers deleted")

        return ok
