"""
Free5GC implementation for 5G Core Network subscription provisioning.

This module implements the CoreNetwork interface for Free5GC,
using configuration from .env and JSON files.
"""

import json
import time
from typing import Dict, Any
import requests
from core_network.core_network import CoreNetwork


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
                    print(f"✓ Successfully authenticated with Free5GC")
                    return True
                else:
                    print("✗ Failed to obtain access token from response")
                    return False
            else:
                print(f"✗ Login failed: HTTP {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Login request failed: {e}")
            return False
    
    def _delete_subscription(self, imsi: str) -> bool:
        """Delete a subscription from Free5GC.
        
        Args:
            imsi (str): IMSI identifier (e.g., 'imsi-208930000000001')
            
        Returns:
            bool: True if deletion successful, False otherwise
        """
        # Build subscriber API URL
        api_url = f"{self.api_base_url}/subscriber/{imsi}/{self.plmn_id}"
        
        # Set up headers with access token
        headers = {
            "Content-Type": "application/json;charset=utf-8",
            "token": self.access_token
        }
        
        try:
            response = requests.delete(
                url=api_url,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200 or response.status_code == 204:
                print(f"✓ Successfully deleted {imsi}")
                return True
            else:
                print(f"✗ Failed to delete {imsi}: HTTP {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            print(f"✗ Error deleting {imsi}: {e}")
            return False
    
    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to Free5GC.
        
        Args:
            count (int): Number of subscriptions to provision
            
        Returns:
            bool: True if successful, False otherwise
        """
        # First, authenticate to get access token
        if not self._login():
            return False
        
        # Always start from INITIAL_IMSI_INDEX
        start_index = self._get_initial_imsi_index()
        success_count = 0
        
        for i in range(count):
            imsi_index = start_index + i
            imsi = f"imsi-{self.plmn_id}{imsi_index:010d}"
            
            # Create subscription data from template
            subscription_data = self.subscription_template.copy()
            subscription_data["ueId"] = imsi
            subscription_data["plmnID"] = self.plmn_id
            
            # Generate unique GPSI based on IMSI index to avoid duplicates
            # Format: msisdn-09XXXXXXXXX where X is the IMSI index
            unique_gpsi = f"msisdn-09{imsi_index:09d}"
            if "AccessAndMobilitySubscriptionData" in subscription_data:
                subscription_data["AccessAndMobilitySubscriptionData"]["gpsis"] = [unique_gpsi]
            
            # Build subscriber API URL
            api_url = f"{self.api_base_url}/subscriber/{imsi}/{self.plmn_id}"
            
            # Set up headers with access token
            headers = {
                "Content-Type": "application/json;charset=utf-8",
                "token": self.access_token
            }
            
            print(f"Provisioning subscription {imsi} to Free5GC...")
            
            try:
                response = requests.post(
                    url=api_url,
                    headers=headers,
                    data=json.dumps(subscription_data),
                    timeout=30
                )
                
                if response.status_code == 201 or response.status_code == 200:
                    print(f"✓ Successfully provisioned {imsi}")
                    success_count += 1
                else:
                    print(f"✗ Failed to provision {imsi}: HTTP {response.status_code}")
                    print(f"   Response: {response.text}")
                    
            except requests.exceptions.RequestException as e:
                print(f"✗ Error provisioning {imsi}: {e}")
            
            # Small delay between requests
            if i < count - 1:
                time.sleep(2)
        
        return success_count == count
    
    def delete_subscriptions(self, count: int) -> bool:
        """Delete subscriptions from Free5GC.
        
        Args:
            count (int): Number of subscriptions to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        # First, authenticate to get access token
        if not self._login():
            return False
        
        # Always start from INITIAL_IMSI_INDEX
        start_index = self._get_initial_imsi_index()
        success_count = 0
        
        for i in range(count):
            imsi_index = start_index + i
            imsi = f"imsi-{self.plmn_id}{imsi_index:010d}"
            
            print(f"Deleting subscription {imsi} from Free5GC...")
            
            if self._delete_subscription(imsi):
                success_count += 1
            
            # Small delay between requests
            if i < count - 1:
                time.sleep(1)
        
        return success_count == count