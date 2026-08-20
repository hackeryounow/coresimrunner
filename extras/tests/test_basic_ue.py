#!/usr/bin/env python3
"""
Simple test to verify basic UE functionality without network connection
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

def test_basic_functionality():
    """Test basic functionality without network connection"""
    print("Testing basic functionality...")
    
    try:
        # Test imports
        from integrated_messages import plmn_bcd_encode, plmn_bcd_decode
        from integrated_messages import calculateRes
        from integrated_ue import IntegratedUE
        
        print("✓ Imports successful")
        
        # Test PLMN encoding/decoding
        plmn_encoded = plmn_bcd_encode("46099")
        plmn_decoded = plmn_bcd_decode(plmn_encoded)
        assert plmn_decoded == "46099"
        print("✓ PLMN encoding/decoding works")
        
        # Test UE creation (without network)
        ue = IntegratedUE(
            mcc="460",
            mnc="99", 
            imsi_suffix10="0000000001",
            ran_ue_ngap_id=1,
            gnb_nr_cell_id=1,
            gnb_address="127.0.0.1",
            logging_level="WARNING"
        )
        print(f"✓ UE created: {ue.supi}")
        
        # Test message construction
        initial_msg = ue.send_initial_ue_message()
        print("✓ Initial UE Message constructed successfully")
        
        print("\nAll basic tests passed! The integration is working correctly.")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_basic_functionality()
    sys.exit(0 if success else 1)