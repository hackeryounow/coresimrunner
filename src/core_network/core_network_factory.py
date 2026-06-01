"""
Factory module for creating core network implementations.

This module provides a factory function to instantiate the appropriate
core network implementation based on the configuration.
"""

from typing import Optional
from config_loader import ConfigLoader
from core_network.core_network import CoreNetwork
from core_network.free5gc_impl import Free5GC
from core_network.open5gs_impl import Open5GS


def create_core_network(core_network_type: str, config_loader: ConfigLoader) -> Optional[CoreNetwork]:
    """Create a core network implementation instance.
    
    Args:
        core_network_type (str): Type of core network ('free5gc', 'open5gs', or 'custom')
        config_loader (ConfigLoader): Configuration loader instance
        
    Returns:
        Optional[CoreNetwork]: Core network implementation instance or None if not supported
    """
    if core_network_type == "free5gc":
        return Free5GC(config_loader)
    elif core_network_type == "open5gs":
        return Open5GS(config_loader)
    elif core_network_type == "custom":
        print("Custom core network mode selected. Please implement your custom logic.")
        print("For now, using Free5GC as template.")
        return Free5GC(config_loader)
    else:
        return None