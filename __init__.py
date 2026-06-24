"""
CoreSimRunner - 5G/4G Core Network Subscription Provisioning and Multi-UE Testing

A standalone Python package for 5G/4G core network testing, supporting
subscription provisioning and multi-UE concurrent registration/PDU session tests.
"""

__version__ = "1.0.0"

from coresimrunner.config_loader import ConfigLoader
from coresimrunner.ue_test_runner import UETestRunner

__all__ = [
    "ConfigLoader",
    "UETestRunner",
    "__version__",
]
