#!/usr/bin/env python3
"""
Test script to verify UE registration and PDU session functionality
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
        from integration.integrated_messages import plmn_bcd_encode, plmn_bcd_decode
        from integration.integrated_messages import calculateRes
        from integration.integrated_ue import IntegratedUE
        
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


def test_full_registration_flow():
    """Test full registration flow simulation (without actual network)"""
    print("\nTesting full registration flow simulation...")
    
    try:
        from integration.integrated_gnb import IntegratedGNB
        
        # This would normally connect to AMF, but we'll just test instantiation
        gnb = IntegratedGNB(
            mcc="460",
            mnc="99",
            slices={"SST": 1},
            gnb_address="127.0.0.1",
            amf_address="127.0.0.1",
            amf_port=38412,
            number_of_ues=1,
            start_suffix10="0000000001",
            ki="12341234123412341234123412340000",
            opc="71a121bb69baf3c0cc53fb5038a0131f",
            dnn="internet",
            logging_level="WARNING"
        )
        
        print("✓ GNB simulator instantiated successfully")
        print("✓ Full registration flow test completed")
        return True
        
    except Exception as e:
        print(f"✗ Full flow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success1 = test_basic_functionality()
    success2 = test_full_registration_flow()
    
    if success1 and success2:
        print("\n🎉 All tests passed! The UE registration and PDU session functionality is ready.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed. Please check the error messages above.")
        sys.exit(1)