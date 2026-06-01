"""
Open5GS implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Open5GS,
using configuration from .env and JSON files.
"""

import json
import time
from typing import Dict, Any
import requests
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
            print("Getting CSRF token...")
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
                print(f"✗ Failed to authenticate with Open5GS: HTTP {login_response.status_code}")
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
            
            return session
            
        except requests.exceptions.RequestException as e:
            print(f"✗ Authentication error: {e}")
            return None
        except KeyError as e:
            print(f"✗ Missing expected data in Open5GS response: {e}")
            return None
    
    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to Open5GS.
        
        Args:
            count (int): Number of subscriptions to provision
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Authenticate
        session = self._authenticate()
        if not session:
            return False
        
        # Always start from INITIAL_IMSI_INDEX
        start_index = self._get_initial_imsi_index()
        success_count = 0
        
        try:
            # Provision subscriptions
            for i in range(count):
                imsi_index = start_index + i
                imsi = f"{self.plmn_id}{imsi_index:010d}"
                
                # Create subscription data from template
                subscription_data = self.subscription_template.copy()
                subscription_data["imsi"] = imsi
                
                print(f"Provisioning subscription {imsi} to Open5GS...")
                
                subscriber_response = session.post(
                    self.subscriber_url,
                    data=json.dumps(subscription_data),
                    timeout=30
                )
                
                if subscriber_response.status_code == 201:
                    print(f"✓ Successfully provisioned {imsi}")
                    success_count += 1
                else:
                    print(f"✗ Failed to provision {imsi}: HTTP {subscriber_response.status_code}")
                
                # Small delay between requests
                if i < count - 1:
                    time.sleep(2)
                    
        except requests.exceptions.RequestException as e:
            print(f"✗ Error during Open5GS provisioning: {e}")
            return False
        
        return success_count == count
    
    def delete_subscriptions(self, count: int) -> bool:
        """Delete subscriptions from Open5GS.
        
        Args:
            count (int): Number of subscriptions to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Authenticate
        session = self._authenticate()
        if not session:
            print("✗ Authentication failed, cannot delete subscriptions")
            return False
        
        print(f"✓ Successfully authenticated with Open5GS")
        
        # Always start from INITIAL_IMSI_INDEX
        start_index = self._get_initial_imsi_index()
        success_count = 0
        
        try:
            for i in range(count):
                imsi_index = start_index + i
                imsi = f"{self.plmn_id}{imsi_index:010d}"
                
                # Build subscriber API URL according to Open5GS API specification
                # Format: http://{IP}:{WEBUI_PORT}/api/db/Subscriber/{imsi}
                delete_url = f"{self.subscriber_url}/{imsi}"
                
                # print(f"Deleting subscription {imsi} from Open5GS...")
                # print(f"   URL: {delete_url}")
                # print(f"   Authorization: Bearer token (configured)")
                
                delete_response = session.delete(delete_url, timeout=30)
                
                if delete_response.status_code == 200 or delete_response.status_code == 204:
                    print(f"✓ Successfully deleted {imsi}")
                    success_count += 1
                else:
                    print(f"✗ Failed to delete {imsi}: HTTP {delete_response.status_code}")
                    if delete_response.text:
                        print(f"   Response: {delete_response.text}")
                
                # Small delay between requests to avoid overwhelming the API
                if i < count - 1:
                    time.sleep(1)
                    
        except requests.exceptions.RequestException as e:
            print(f"✗ Error during Open5GS deletion: {e}")
            return False
        
        print(f"\nDeletion Summary: {success_count}/{count} subscriptions deleted successfully")
        return success_count == count
