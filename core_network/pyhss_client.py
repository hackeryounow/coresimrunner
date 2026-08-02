"""
PyHSS API client for IMS subscriber provisioning.

This module provides a client for the PyHSS REST API, used to provision
IMS-related data (APN, AuC, Subscriber, IMS Subscriber) alongside the
Open5GS provisioning flow.
"""

import json
import requests
from typing import Dict, Any, Tuple, Optional
from loguru import logger


class PyHSSClient:
    """Client for the PyHSS REST API (port 8080)."""

    def __init__(self, base_url: str, mcc: str, mnc: str):
        """Initialize PyHSS client.

        Args:
            base_url: Base URL of PyHSS API (e.g., 'http://172.22.0.1:8080')
            mcc: Mobile Country Code (e.g., '460')
            mnc: Mobile Network Code (e.g., '09')
        """
        self.base_url = base_url.rstrip('/')
        self.mcc = mcc
        self.mnc = mnc
        self.realm = f"ims.mnc{mnc}.mcc{mcc}.3gppnetwork.org"
        self.scscf_uri = (
            f"sip:scscf.ims.mnc{mnc}.mcc{mcc}"
            f".3gppnetwork.org:6060"
        )
        self.scscf_peer = (
            f"scscf.ims.mnc{mnc}.mcc{mcc}"
            f".3gppnetwork.org"
        )

    # ------------------------------------------------------------------
    # APN management
    # ------------------------------------------------------------------

    def _get_apn_list(self) -> Optional[list]:
        """Fetch all APN entries from PyHSS.

        Returns:
            List of APN dicts, or None on failure.
        """
        url = f"{self.base_url}/apn/list?page=0&page_size=200"
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            logger.error(
                f"PyHSS GET /apn/list failed: HTTP {resp.status_code}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"PyHSS GET /apn/list error: {e}")
        return None

    def _create_apn(self, apn_name: str) -> Optional[int]:
        """Create a single APN entry.

        Args:
            apn_name: APN name ('internet' or 'ims')

        Returns:
            apn_id on success, None on failure.
        """
        url = f"{self.base_url}/apn/"
        payload = {
            "apn": apn_name,
            "apn_ambr_dl": 0,
            "apn_ambr_ul": 0,
        }
        try:
            resp = requests.put(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                apn_id = data.get("apn_id")
                logger.info(
                    f"PyHSS created APN '{apn_name}' -> apn_id={apn_id}"
                )
                return apn_id
            logger.error(
                f"PyHSS PUT /apn/ ({apn_name}) failed: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"PyHSS PUT /apn/ ({apn_name}) error: {e}")
        return None

    def ensure_apns(self) -> Tuple[Optional[int], Optional[int]]:
        """Ensure both 'internet' and 'ims' APNs exist in PyHSS.

        Queries the existing APN list first; only creates missing APNs.

        Returns:
            Tuple of (internet_apn_id, ims_apn_id).
            Either may be None on failure.
        """
        internet_id = None
        ims_id = None

        apn_list = self._get_apn_list()
        if apn_list is not None:
            for entry in apn_list:
                name = entry.get("apn", "")
                aid = entry.get("apn_id")
                if name == "internet":
                    internet_id = aid
                elif name == "ims":
                    ims_id = aid

        if internet_id is None:
            logger.info("APN 'internet' not found, creating...")
            internet_id = self._create_apn("internet")
        else:
            logger.debug(f"APN 'internet' exists: apn_id={internet_id}")

        if ims_id is None:
            logger.info("APN 'ims' not found, creating...")
            ims_id = self._create_apn("ims")
        else:
            logger.debug(f"APN 'ims' exists: apn_id={ims_id}")

        return internet_id, ims_id

    # ------------------------------------------------------------------
    # AuC management
    # ------------------------------------------------------------------

    def create_auc(
        self, imsi: str, ki: str, opc: str, amf: str = "8000"
    ) -> Optional[int]:
        """Create an AuC entry in PyHSS.

        Args:
            imsi: Subscriber IMSI
            ki: Permanent key (hex string)
            opc: OPc value (hex string)
            amf: AMF value (default '8000')

        Returns:
            auc_id on success, None on failure.
        """
        url = f"{self.base_url}/auc/"
        payload = {
            "ki": ki,
            "opc": opc,
            "amf": amf,
            "sqn": 0,
            "imsi": imsi,
        }
        try:
            resp = requests.put(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                auc_id = data.get("auc_id")
                logger.info(
                    f"PyHSS created AuC for IMSI {imsi} -> auc_id={auc_id}"
                )
                return auc_id
            logger.error(
                f"PyHSS PUT /auc/ ({imsi}) failed: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"PyHSS PUT /auc/ ({imsi}) error: {e}")
        return None

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def create_subscriber(
        self,
        imsi: str,
        auc_id: int,
        default_apn: int,
        apn_list: str,
        msisdn: str,
    ) -> bool:
        """Create a subscriber entry in PyHSS.

        Args:
            imsi: Subscriber IMSI
            auc_id: AuC ID from create_auc()
            default_apn: APN ID of the non-IMS (internet) APN
            apn_list: Comma-separated APN IDs (e.g., '1,2')
            msisdn: Phone number

        Returns:
            True on success, False otherwise.
        """
        url = f"{self.base_url}/subscriber/"
        payload = {
            "imsi": imsi,
            "enabled": True,
            "auc_id": auc_id,
            "default_apn": default_apn,
            "apn_list": apn_list,
            "msisdn": msisdn,
            "ue_ambr_dl": 0,
            "ue_ambr_ul": 0,
        }
        try:
            resp = requests.put(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                logger.info(f"PyHSS created subscriber for IMSI {imsi}")
                return True
            logger.error(
                f"PyHSS PUT /subscriber/ ({imsi}) failed: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"PyHSS PUT /subscriber/ ({imsi}) error: {e}")
        return False

    # ------------------------------------------------------------------
    # IMS Subscriber management
    # ------------------------------------------------------------------

    def create_ims_subscriber(self, imsi: str, msisdn: str) -> bool:
        """Create an IMS subscriber entry in PyHSS.

        Args:
            imsi: Subscriber IMSI
            msisdn: Phone number

        Returns:
            True on success, False otherwise.
        """
        url = f"{self.base_url}/ims_subscriber/"
        payload = {
            "imsi": imsi,
            "msisdn": msisdn,
            "sh_profile": "string",
            "scscf_peer": self.scscf_peer,
            "msisdn_list": f"[{msisdn}]",
            "ifc_path": "default_ifc.xml",
            "scscf": self.scscf_uri,
            "scscf_realm": self.realm,
        }
        try:
            resp = requests.put(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code in (200, 201):
                logger.info(
                    f"PyHSS created IMS subscriber for IMSI {imsi}"
                )
                return True
            logger.error(
                f"PyHSS PUT /ims_subscriber/ ({imsi}) failed: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        except requests.exceptions.RequestException as e:
            logger.error(
                f"PyHSS PUT /ims_subscriber/ ({imsi}) error: {e}"
            )
        return False

    # ------------------------------------------------------------------
    # Orchestrated provisioning
    # ------------------------------------------------------------------

    def provision_ims_subscriber(
        self,
        imsi: str,
        msisdn: str,
        ki: str,
        opc: str,
        amf: str = "8000",
    ) -> bool:
        """Provision a complete IMS subscriber in PyHSS.

        Performs the full four-step provisioning sequence:
          1. Ensure APNs exist (internet + ims)
          2. Create AuC entry
          3. Create Subscriber
          4. Create IMS Subscriber

        Args:
            imsi: Subscriber IMSI
            msisdn: Phone number
            ki: Permanent key (hex string)
            opc: OPc value (hex string)
            amf: AMF value (default '8000')

        Returns:
            True if all steps succeeded, False otherwise.
        """
        # Step 1: Ensure APNs
        internet_id, ims_id = self.ensure_apns()
        if internet_id is None or ims_id is None:
            logger.error(
                f"PyHSS: failed to ensure APNs for IMSI {imsi}"
            )
            return False

        # Step 2: Create AuC
        auc_id = self.create_auc(imsi, ki, opc, amf)
        if auc_id is None:
            logger.error(
                f"PyHSS: failed to create AuC for IMSI {imsi}"
            )
            return False

        # Step 3: Create Subscriber
        apn_list = f"{internet_id},{ims_id}"
        if not self.create_subscriber(
            imsi, auc_id, internet_id, apn_list, msisdn
        ):
            logger.error(
                f"PyHSS: failed to create subscriber for IMSI {imsi}"
            )
            return False

        # Step 4: Create IMS Subscriber
        if not self.create_ims_subscriber(imsi, msisdn):
            logger.error(
                f"PyHSS: failed to create IMS subscriber for IMSI {imsi}"
            )
            return False

        logger.info(
            f"PyHSS: full IMS provisioning complete for IMSI {imsi}"
        )
        return True

    def delete_subscriber(self, imsi: str) -> bool:
        """Delete a subscriber and its IMS data from PyHSS.

        Args:
            imsi: Subscriber IMSI to delete.

        Returns:
            True on success, False otherwise.
        """
        ok = True
        for resource in ("ims_subscriber", "subscriber", "auc"):
            url = f"{self.base_url}/{resource}/{imsi}"
            try:
                resp = requests.delete(url, timeout=30)
                if resp.status_code in (200, 204):
                    logger.debug(f"PyHSS deleted {resource}/{imsi}")
                else:
                    logger.warning(
                        f"PyHSS DELETE {resource}/{imsi}: "
                        f"HTTP {resp.status_code}"
                    )
                    ok = False
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS DELETE {resource}/{imsi} error: {e}")
                ok = False
        return ok
