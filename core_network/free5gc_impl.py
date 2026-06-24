"""
Free5GC implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Free5GC,
using configuration from .env and JSON files.
"""

import json
import time
from typing import Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
from loguru import logger
from coresimrunner.core_network.core_network import CoreNetwork


class Free5GC(CoreNetwork):
    """Free5GC implementation of the CoreNetwork interface."""
    
    def __init__(self, config_loader):
        """Initialize Free5GC implementation.
        
        Args:
            config_loader: Configuration loader instance
        """
        super().__init__("free5gc", config_loader)
        self.api_base_url = f"http://{self.network_config['ip']}:{self.network_config['webui_port']}/api"
        self.login_url = f"{self.api_base_url}/login"
        self.subscription_template = self.network_config["subscription_template"]
        self.plmn_id = self.network_config["plmn_id"]
        self.username = self.network_config.get("username", "admin")
        self.password = self.network_config.get("password", "free5gc")
        self.access_token = None
    
    def _login(self) -> bool:
        """Authenticate with Free5GC and obtain access token.
        
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            login_data = {
                "username": self.username,
                "password": self.password
            }
            
            response = requests.post(
                url=self.login_url,
                headers={"Content-Type": "application/json"},
                data=json.dumps(login_data),
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                self.access_token = result.get("access_token")
                if self.access_token:
                    logger.info("Successfully authenticated with Free5GC")
                    return True
                else:
                    logger.error("Failed to obtain access token from response")
                    return False
            else:
                logger.error(f"Login failed: HTTP {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Login request failed: {e}")
            return False
    
    def _provision_one(self, imsi_index: int) -> Tuple[int, bool]:
        """Provision a single subscription (thread-safe). Returns (index, success)."""
        imsi = f"imsi-{self.plmn_id}{imsi_index:010d}"
        subscription_data = self.subscription_template.copy()
        subscription_data["ueId"] = imsi
        subscription_data["plmnID"] = self.plmn_id
        unique_gpsi = f"msisdn-09{imsi_index:09d}"
        if "AccessAndMobilitySubscriptionData" in subscription_data:
            subscription_data["AccessAndMobilitySubscriptionData"]["gpsis"] = [unique_gpsi]
        api_url = f"{self.api_base_url}/subscriber/{imsi}/{self.plmn_id}"
        headers = {"Content-Type": "application/json;charset=utf-8", "token": self.access_token}
        try:
            resp = requests.post(api_url, headers=headers, data=json.dumps(subscription_data), timeout=30)
            if resp.status_code in (200, 201):
                return imsi_index, True
        except Exception:
            pass
        return imsi_index, False
    
    def _delete_one(self, imsi_index: int) -> Tuple[int, bool]:
        """Delete a single subscription (thread-safe). Returns (index, success)."""
        imsi = f"imsi-{self.plmn_id}{imsi_index:010d}"
        api_url = f"{self.api_base_url}/subscriber/{imsi}/{self.plmn_id}"
        headers = {"Content-Type": "application/json;charset=utf-8", "token": self.access_token}
        try:
            resp = requests.delete(api_url, headers=headers, timeout=30)
            if resp.status_code in (200, 204):
                return imsi_index, True
        except Exception:
            pass
        return imsi_index, False
    
    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to Free5GC using concurrent threads."""
        if not self._login():
            return False
        start_index = self._get_initial_imsi_index()
        indices = list(range(start_index, start_index + count))
        failed = []
        with ThreadPoolExecutor(max_workers=min(count, 20)) as pool:
            futures = {pool.submit(self._provision_one, idx): idx for idx in indices}
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
        """Delete subscriptions from Free5GC using concurrent threads."""
        if not self._login():
            return False
        start_index = self._get_initial_imsi_index()
        indices = list(range(start_index, start_index + count))
        failed = []
        with ThreadPoolExecutor(max_workers=min(count, 20)) as pool:
            futures = {pool.submit(self._delete_one, idx): idx for idx in indices}
            with tqdm(total=count, desc="Deleting", unit="sub", ncols=80) as pbar:
                for f in as_completed(futures):
                    idx, ok = f.result()
                    if not ok:
                        failed.append(idx)
                    pbar.update(1)
        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0