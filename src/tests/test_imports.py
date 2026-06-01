#!/usr/bin/env python3
"""
Quick import test to verify all modules can be loaded
"""

import sys
import os

# Add workspace libraries to Python path
WORKSPACE_ROOT = '/root'
PYCRATE_PATH = os.path.join(WORKSPACE_ROOT, 'pycrate')
CRYPTOMOBILE_PATH = os.path.join(WORKSPACE_ROOT, 'CryptoMobile')

if PYCRATE_PATH not in sys.path:
    sys.path.insert(0, PYCRATE_PATH)
if CRYPTOMOBILE_PATH not in sys.path:
    sys.path.insert(0, CRYPTOMOBILE_PATH)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Testing imports...")

try:
    print("1. Testing pycrate_asn1dir...", end=" ")
    from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("2. Testing pycrate_mobile...", end=" ")
    from pycrate_mobile.TS24501_FGMM import FGMMRegistrationRequest
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("3. Testing CryptoMobile...", end=" ")
    from CryptoMobile.Milenage import Milenage
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("4. Testing Crypto (pycryptodome)...", end=" ")
    from Crypto.Cipher import AES
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("5. Testing loguru...", end=" ")
    from loguru import logger
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("6. Testing tqdm...", end=" ")
    from tqdm import tqdm
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    sys.exit(1)

try:
    print("7. Testing integrated_messages...", end=" ")
    from integrated_messages import ProcedureCode, MessageType
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("8. Testing integrated_ue...", end=" ")
    from integrated_ue import IntegratedUE
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("9. Testing integrated_gnb...", end=" ")
    from integrated_gnb import IntegratedGNB
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("10. Testing ue_test_runner...", end=" ")
    from ue_test_runner import UETestRunner
    print("✓ OK")
except Exception as e:
    print(f"✗ FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n✓ All imports successful!")
print("\nYou can now run UE tests with:")
print("  python3 coresim_runner.py --mode ue-test --count 1 --core-network open5gs \\")
print("      --gnb-address 192.168.55.9 --amf-address 192.168.55.53 --log-level WARNING")
