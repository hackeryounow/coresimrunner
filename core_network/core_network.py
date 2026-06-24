"""
Abstract base class for 5G Core Network implementations.

This module defines the interface that all core network implementations must follow.
"""

import os
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class CoreNetwork(ABC):
    """Abstract base class for core network implementations."""
    
    def __init__(self, name: str, config_loader):
        """Initialize the core network implementation.
        
        Args:
            name (str): Name of the core network type
            config_loader: Configuration loader instance
        """
        self.name = name
        self.config_loader = config_loader
        self.network_config = config_loader.get_network_config(name)
    
    @abstractmethod
    def provision_subscriptions(self, count: int) -> bool:
        """Provision subscriptions to the core network.
        
        Args:
            count (int): Number of subscriptions to provision
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    def delete_subscriptions(self, count: int) -> bool:
        """Delete subscriptions from the core network.
        
        Args:
            count (int): Number of subscriptions to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        pass
    
    def _get_initial_imsi_index(self) -> int:
        """Get the initial IMSI index from configuration.
        
        Returns:
            int: Initial IMSI index
        """
        return self.network_config.get("initial_imsi_index", 1)
    
    @staticmethod
    def _format_failed_range(indices: List[int]) -> str:
        """Format a list of failed indices as compact ranges.
        
        Examples:
            [1,2,3,5,7,8,9] -> "1-3, 5, 7-9"
            [1,2,3,4,5] -> "1-5"
            [1,3,5] -> "1, 3, 5"
        """
        if not indices:
            return ""
        sorted_idx = sorted(set(indices))
        ranges = []
        start = sorted_idx[0]
        end = sorted_idx[0]
        for i in sorted_idx[1:]:
            if i == end + 1:
                end = i
            else:
                ranges.append(f"{start}-{end}" if start != end else str(start))
                start = end = i
        ranges.append(f"{start}-{end}" if start != end else str(start))
        return ", ".join(ranges)