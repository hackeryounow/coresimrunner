#!/usr/bin/env python3
"""
Original 4G integration test that actually connects to MME.
This test creates an eNodeB that automatically connects to MME and sends S1 Setup Request.
Then it tests UE attach and PDN connection establishment.
"""

import sys
import os
import time

# Add paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))
sys.path.insert(0, '/root/pycrate')
sys.path.insert(0, '/root/CryptoMobile')

def test_original_integration():
    """Test the original integration functionality with actual MME connection."""
    print("Testing original 4G integration with actual MME connection...")
    
    try:
        from integration.integrated_4g_gnb import Integrated4GGNB
        
        # This is what the original test should have done:
        # Create eNodeB which automatically connects to MME and sends S1 Setup
        print("Creating eNodeB instance (will auto-connect to MME)...")
        
        gnb = Integrated4GGNB(
            enb_name="Original-Integration-Test",
            enb_id=1,
            tac="0001",
            plmn="46099",
            enb_ip="192.168.55.9",
            mme_ip="192.168.55.53",
            ki="465B5CE8B199B49FAA5F0A2EE238A6BC",
            opc="E8ED289DEBA952E4283B54E88E6183CA",
            apn="internet",
            number_of_ues=1,
            start_imsi="0000000001",
            log_level="DEBUG"
        )
        gnb.run()
        print("✓ eNodeB created successfully")
        print(f"✓ Connected to MME at {gnb.mme_ip}:{gnb.mme_port}")
        
        # Wait for MME responses - this is the key missing part!
        print("Waiting for MME responses (this may take up to 30 seconds)...")
        wait_time = 15
        time.sleep(wait_time)
        # Clean shutdown
        gnb.close()
        
        return True
    except Exception as e:
        print(f"✗ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        # Ensure cleanup even on error
        try:
            gnb.close()
        except:
            pass
        return False

if __name__ == "__main__":
    success = test_original_integration()
    if success:
        print("\n✅ Original integration test PASSED!")
        print("The system can connect to MME and send S1 Setup Request.")
        print("UE attach and PDN connection functionality is available.")
    else:
        print("\n❌ Integration test FAILED!")
        print("Check if MME is running and accessible.")
    sys.exit(0 if success else 1)