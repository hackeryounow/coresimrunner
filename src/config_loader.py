"""
Configuration loader for CoreSimRunner.

This module handles loading configuration from .env files and JSON files,
providing a unified interface for accessing configuration values.
"""

import os
import json
import re
from typing import Dict, Any, Optional


class ConfigLoader:
    """Configuration loader that reads from .env and JSON files."""
    
    def __init__(self, env_file: str = ".env"):
        """Initialize the configuration loader.
        
        Args:
            env_file (str): Path to the .env file
        """
        self.env_file = env_file
        self._config: Dict[str, str] = {}
        self._load_env_file()
    
    def _load_env_file(self):
        """Load configuration from .env file."""
        if not os.path.exists(self.env_file):
            raise FileNotFoundError(f"Configuration file {self.env_file} not found")
        
        with open(self.env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Strip surrounding quotes (single or double)
                        if len(value) >= 2 and (
                            (value[0] == '"' and value[-1] == '"') or
                            (value[0] == "'" and value[-1] == "'")
                        ):
                            value = value[1:-1]
                        
                        # Handle variable substitution (e.g., ${VAR_NAME})
                        if value.startswith('${') and value.endswith('}'):
                            var_name = value[2:-1]
                            value = os.environ.get(var_name, self._config.get(var_name, ''))
                        
                        self._config[key] = value
    
    def get(self, key: str, default: Optional[str] = None) -> str:
        """Get a configuration value by key.
        
        Args:
            key (str): Configuration key
            default (str, optional): Default value if key not found
            
        Returns:
            str: Configuration value
        """
        return self._config.get(key, default)
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get a configuration value as integer.
        
        Args:
            key (str): Configuration key
            default (int): Default value if key not found or invalid
            
        Returns:
            int: Configuration value as integer
        """
        try:
            return int(self._config.get(key, default))
        except (ValueError, TypeError):
            return default
    
    def load_json_file(self, key: str) -> Dict[str, Any]:
        """Load JSON configuration from file path specified by key.
        
        Args:
            key (str): Configuration key that contains the file path
            
        Returns:
            Dict[str, Any]: Parsed JSON content
        """
        file_path = self.get(key)
        if not file_path:
            raise ValueError(f"No file path found for key: {key}")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"JSON configuration file {file_path} not found")
        
        with open(file_path, 'r') as f:
            json_content = f.read()
            # Replace placeholders with actual values from config
            json_content = self._substitute_placeholders(json_content)
            return json.loads(json_content)
    
    def _substitute_placeholders(self, content: str) -> str:
        """Substitute ${KEY} placeholders in content with actual config values.
        
        Args:
            content (str): Content with placeholders
            
        Returns:
            str: Content with placeholders replaced
        """
        def replace_match(match):
            key = match.group(1)
            return self.get(key, match.group(0))  # Return original if key not found
        
        # Replace ${KEY} patterns
        pattern = r'\$\{([^}]+)\}'
        return re.sub(pattern, replace_match, content)
    
    def get_network_config(self, core_network: str) -> Dict[str, Any]:
        """Get network configuration for a specific core network.
        
        Args:
            core_network (str): Core network type ('free5gc' or 'open5gs')
            
        Returns:
            Dict[str, Any]: Network configuration
        """
        # Unified base configuration
        base_config = {
            "ip": self.get("CORE_NETWORK_IP"),
            "webui_port": self.get("WEBUI_PORT"),
            "plmn_id": self.get("PLMN_ID", "20893"),
            "username": self.get("USERNAME", "admin"),
            "password": self.get("PASSWORD", "1423"),
            "api_token": self.get("API_TOKEN", "admin"),
            "initial_imsi_index": self.get_int("INITIAL_IMSI_INDEX", 1)
        }
        
        # Add core-network-specific configuration
        if core_network == "free5gc":
            base_config["subscription_template"] = self.load_json_file("FREE5GC_SUBSCRIPTION_TEMPLATE")
        elif core_network == "open5gs":
            base_config["subscription_template"] = self.load_json_file("OPEN5GS_SUBSCRIPTION_TEMPLATE")
        else:
            # For custom or other types, use Free5GC template as default
            base_config["subscription_template"] = self.load_json_file("FREE5GC_SUBSCRIPTION_TEMPLATE")
        
        return base_config