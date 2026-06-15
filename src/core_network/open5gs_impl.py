"""
Open5GS implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Open5GS,
using configuration from .env and JSON files.
"""

import json
import time
from typing import Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from tqdm import tqdm
from loguru import logger
from core_network.core_network import CoreNetwork


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
    
    def _provision_one(self, session: requests.Session, imsi_index: int) -> Tuple[int, bool]:
        """Provision a single subscription (thread-safe via session). Returns (index, success)."""
        imsi = f"{self.plmn_id}{imsi_index:010d}"
        subscription_data = self.subscription_template.copy()
        subscription_data["imsi"] = imsi
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

    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to Open5GS using concurrent threads."""
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
        if failed:
            logger.warning(f"Failed: {len(failed)}/{count}, indices: {self._format_failed_range(failed)}")
        return len(failed) == 0
