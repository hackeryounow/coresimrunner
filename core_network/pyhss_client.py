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

    PAGE_SIZE = 200

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
        # 3GPP home network domain: MNC is zero-padded to 3 digits
        # (e.g., MNC '01' -> 'mnc001', MNC '09' -> 'mnc009')
        mnc3 = mnc.zfill(3)
        self.realm = f"ims.mnc{mnc3}.mcc{mcc}.3gppnetwork.org"
        self.scscf_uri = (
            f"sip:scscf.ims.mnc{mnc3}.mcc{mcc}"
            f".3gppnetwork.org:6060"
        )
        self.scscf_peer = (
            f"scscf.ims.mnc{mnc3}.mcc{mcc}"
            f".3gppnetwork.org"
        )

    # ------------------------------------------------------------------
    # Generic paginated list fetcher
    # ------------------------------------------------------------------

    def _fetch_all_pages(self, resource: str) -> Optional[list]:
        """Fetch ALL entries from a paginated list endpoint.

        Loops through pages until an empty page is returned.

        Args:
            resource: API resource name (e.g., 'apn', 'auc', 'ims_subscriber')

        Returns:
            Combined list of all entries, or None on failure.
        """
        all_entries = []
        page = 0
        while True:
            url = f"{self.base_url}/{resource}/list?page={page}&page_size={self.PAGE_SIZE}"
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    logger.error(
                        f"PyHSS GET /{resource}/list?page={page} failed: "
                        f"HTTP {resp.status_code}"
                    )
                    return None
                data = resp.json()
                if not data:
                    break
                all_entries.extend(data)
                # If we got fewer than PAGE_SIZE, this is the last page
                if len(data) < self.PAGE_SIZE:
                    break
                page += 1
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS GET /{resource}/list?page={page} error: {e}")
                return None
        return all_entries

    # ------------------------------------------------------------------
    # APN management
    # ------------------------------------------------------------------

    def _get_apn_list(self) -> Optional[list]:
        """Fetch all APN entries from PyHSS (paginated).

        Returns:
            List of APN dicts, or None on failure.
        """
        return self._fetch_all_pages("apn")

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
        internet_apn_id: Optional[int] = None,
        ims_apn_id: Optional[int] = None,
    ) -> bool:
        """Provision a complete IMS subscriber in PyHSS.

        Performs the full four-step provisioning sequence:
          1. Ensure APNs exist (internet + ims) — skipped if IDs provided
          2. Create AuC entry
          3. Create Subscriber
          4. Create IMS Subscriber

        Args:
            imsi: Subscriber IMSI
            msisdn: Phone number
            ki: Permanent key (hex string)
            opc: OPc value (hex string)
            amf: AMF value (default '8000')
            internet_apn_id: Pre-fetched internet APN ID (skips ensure_apns)
            ims_apn_id: Pre-fetched IMS APN ID (skips ensure_apns)

        Returns:
            True if all steps succeeded, False otherwise.
        """
        # Step 1: Ensure APNs (skip if caller already provided IDs)
        if internet_apn_id is not None and ims_apn_id is not None:
            internet_id, ims_id = internet_apn_id, ims_apn_id
        else:
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

    def delete_apns(self) -> bool:
        """Delete all APN entries from PyHSS.

        Queries /apn/list, then sends DELETE /apn/{apn_id} for each.

        Returns:
            True if all deletions succeeded, False otherwise.
        """
        apn_list = self._get_apn_list()
        if apn_list is None:
            logger.error("PyHSS: failed to query APN list for deletion")
            return False

        if not apn_list:
            logger.debug("PyHSS: no APNs to delete")
            return True

        ok = True
        for entry in apn_list:
            apn_id = entry.get("apn_id")
            apn_name = entry.get("apn", "?")
            if apn_id is None:
                continue
            url = f"{self.base_url}/apn/{apn_id}"
            try:
                resp = requests.delete(url, timeout=30)
                if resp.status_code in (200, 204):
                    logger.debug(f"PyHSS deleted APN '{apn_name}' (id={apn_id})")
                else:
                    logger.warning(
                        f"PyHSS DELETE /apn/{apn_id} ({apn_name}): "
                        f"HTTP {resp.status_code}"
                    )
                    ok = False
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS DELETE /apn/{apn_id} ({apn_name}) error: {e}")
                ok = False
        return ok

    def _get_auc_list(self) -> Optional[list]:
        """Fetch all AuC entries from PyHSS (paginated).

        Returns:
            List of AuC dicts, or None on failure.
        """
        return self._fetch_all_pages("auc")

    def _find_auc_id(self, imsi: str) -> Optional[int]:
        """Find auc_id for a given IMSI by querying the AuC list.

        Args:
            imsi: Subscriber IMSI

        Returns:
            auc_id if found, None otherwise.
        """
        auc_list = self._get_auc_list()
        if auc_list is None:
            return None
        for entry in auc_list:
            if entry.get("imsi") == imsi:
                return entry.get("auc_id")
        return None

    def _get_subscriber_list(self) -> Optional[list]:
        """Fetch all subscriber entries from PyHSS (paginated).

        Returns:
            List of subscriber dicts, or None on failure.
        """
        return self._fetch_all_pages("subscriber")

    def _find_subscriber_id(self, imsi: str) -> Optional[int]:
        """Find the numeric subscriber_id for a given IMSI.

        Args:
            imsi: Subscriber IMSI

        Returns:
            subscriber_id if found, None otherwise.
        """
        entries = self._get_subscriber_list()
        if entries is None:
            return None
        for entry in entries:
            if entry.get("imsi") == imsi:
                return entry.get("subscriber_id")
        return None

    def _get_ims_subscriber_list(self) -> Optional[list]:
        """Fetch all IMS subscriber entries from PyHSS (paginated).

        Returns:
            List of IMS subscriber dicts, or None on failure.
        """
        return self._fetch_all_pages("ims_subscriber")

    def _find_ims_subscriber_id(self, imsi: str) -> Optional[int]:
        """Find ims_subscriber_id for a given IMSI.

        Args:
            imsi: Subscriber IMSI

        Returns:
            ims_subscriber_id if found, None otherwise.
        """
        entries = self._get_ims_subscriber_list()
        if entries is None:
            return None
        for entry in entries:
            if entry.get("imsi") == imsi:
                return entry.get("ims_subscriber_id")
        return None

    def delete_subscriber(self, imsi: str) -> bool:
        """Delete a subscriber and its IMS data from PyHSS.

        Deletion order:
          1. Query /ims_subscriber/list to find ims_subscriber_id by IMSI
          2. DELETE /ims_subscriber/{ims_subscriber_id}
          3. Query /subscriber/list to find subscriber_id by IMSI
          4. DELETE /subscriber/{subscriber_id}
          5. Query /auc/list to find auc_id by IMSI
          6. DELETE /auc/{auc_id}

        Args:
            imsi: Subscriber IMSI to delete.

        Returns:
            True on success, False otherwise.
        """
        ok = True

        # Step 1 & 2: Query ims_subscriber list, find ID, delete by ID
        ims_sub_id = self._find_ims_subscriber_id(imsi)
        if ims_sub_id is not None:
            url = f"{self.base_url}/ims_subscriber/{ims_sub_id}"
            try:
                resp = requests.delete(url, timeout=30)
                if resp.status_code in (200, 204):
                    logger.debug(f"PyHSS deleted ims_subscriber/{ims_sub_id} (imsi={imsi})")
                else:
                    logger.warning(
                        f"PyHSS DELETE /ims_subscriber/{ims_sub_id}: HTTP {resp.status_code}"
                    )
                    ok = False
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS DELETE /ims_subscriber/{ims_sub_id} error: {e}")
                ok = False
        else:
            logger.warning(f"PyHSS: ims_subscriber_id not found for IMSI {imsi}, skipping")

        # Step 3 & 4: Query subscriber list, find numeric ID, delete by ID
        sub_id = self._find_subscriber_id(imsi)
        if sub_id is not None:
            url = f"{self.base_url}/subscriber/{sub_id}"
            try:
                resp = requests.delete(url, timeout=30)
                if resp.status_code in (200, 204):
                    logger.debug(f"PyHSS deleted subscriber/{sub_id} (imsi={imsi})")
                else:
                    logger.warning(
                        f"PyHSS DELETE /subscriber/{sub_id}: HTTP {resp.status_code}"
                    )
                    ok = False
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS DELETE /subscriber/{sub_id} error: {e}")
                ok = False
        else:
            logger.warning(f"PyHSS: subscriber_id not found for IMSI {imsi}, skipping")

        # Step 5 & 6: Query AuC list, find auc_id, then delete by auc_id
        auc_id = self._find_auc_id(imsi)
        if auc_id is not None:
            url = f"{self.base_url}/auc/{auc_id}"
            try:
                resp = requests.delete(url, timeout=30)
                if resp.status_code in (200, 204):
                    logger.debug(f"PyHSS deleted auc/{auc_id} (imsi={imsi})")
                else:
                    logger.warning(
                        f"PyHSS DELETE /auc/{auc_id}: HTTP {resp.status_code}"
                    )
                    ok = False
            except requests.exceptions.RequestException as e:
                logger.error(f"PyHSS DELETE /auc/{auc_id} error: {e}")
                ok = False
        else:
            logger.warning(f"PyHSS: auc_id not found for IMSI {imsi}, skipping AuC delete")

        return ok

    def delete_all(self) -> bool:
        """Delete ALL IMS data from PyHSS.

        Deletion order:
          1. All ims_subscriber entries (by ims_subscriber_id)
          2. All subscriber entries (by subscriber_id)
          3. All AuC entries (by auc_id)
          4. All APN entries (by apn_id)

        Returns:
            True if all deletions succeeded, False otherwise.
        """
        ok = True

        # Step 1: Delete all ims_subscriber entries
        ims_list = self._fetch_all_pages("ims_subscriber")
        if ims_list:
            for entry in ims_list:
                sid = entry.get("ims_subscriber_id")
                if sid is None:
                    continue
                url = f"{self.base_url}/ims_subscriber/{sid}"
                try:
                    resp = requests.delete(url, timeout=30)
                    if resp.status_code not in (200, 204):
                        logger.warning(f"PyHSS DELETE /ims_subscriber/{sid}: HTTP {resp.status_code}")
                        ok = False
                except requests.exceptions.RequestException as e:
                    logger.error(f"PyHSS DELETE /ims_subscriber/{sid} error: {e}")
                    ok = False
            logger.info(f"PyHSS: deleted {len(ims_list)} ims_subscriber entries")

        # Step 2: Delete all subscriber entries (by numeric subscriber_id)
        sub_list = self._fetch_all_pages("subscriber")
        if sub_list:
            for entry in sub_list:
                sub_id = entry.get("subscriber_id")
                if sub_id is None:
                    continue
                url = f"{self.base_url}/subscriber/{sub_id}"
                try:
                    resp = requests.delete(url, timeout=30)
                    if resp.status_code not in (200, 204):
                        logger.warning(f"PyHSS DELETE /subscriber/{sub_id}: HTTP {resp.status_code}")
                        ok = False
                except requests.exceptions.RequestException as e:
                    logger.error(f"PyHSS DELETE /subscriber/{sub_id} error: {e}")
                    ok = False
            logger.info(f"PyHSS: deleted {len(sub_list)} subscriber entries")

        # Step 3: Delete all AuC entries
        auc_list = self._fetch_all_pages("auc")
        if auc_list:
            for entry in auc_list:
                auc_id = entry.get("auc_id")
                if auc_id is None:
                    continue
                url = f"{self.base_url}/auc/{auc_id}"
                try:
                    resp = requests.delete(url, timeout=30)
                    if resp.status_code not in (200, 204):
                        logger.warning(f"PyHSS DELETE /auc/{auc_id}: HTTP {resp.status_code}")
                        ok = False
                except requests.exceptions.RequestException as e:
                    logger.error(f"PyHSS DELETE /auc/{auc_id} error: {e}")
                    ok = False
            logger.info(f"PyHSS: deleted {len(auc_list)} AuC entries")

        # Step 4: Delete all APN entries
        if not self.delete_apns():
            ok = False

        logger.info(f"PyHSS: delete_all completed, success={ok}")
        return ok
