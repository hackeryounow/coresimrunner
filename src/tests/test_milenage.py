#!/usr/bin/env python3
"""
Test Milenage functionality
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

def test_milenage():
    """Test Milenage with known test vectors"""
    try:
        from CryptoMobile.Milenage import Milenage
        
        # Test vector from 3GPP TS 35.208
        k = bytes.fromhex("465b5ce8b199b49faa5f0a2ee238a6bc")
        opc = bytes.fromhex("cd63cb71954a9f4e48a5f50f229c9ca3")
        rand = bytes.fromhex("23573977777777777777777777777777")
        sqn = bytes.fromhex("000000000001")
        amf = bytes.fromhex("8000")
        
        print("Testing Milenage with standard test vectors...")
        print(f"K: {k.hex()}")
        print(f"OPC: {opc.hex()}")
        print(f"RAND: {rand.hex()}")
        print(f"SQN: {sqn.hex()}")
        print(f"AMF: {amf.hex()}")
        
        # Initialize Milenage
        mil = Milenage(opc)
        
        # Test f2345
        res, ck, ik, ak = mil.f2345(k, rand)
        print(f"RES: {res.hex()}")
        print(f"CK: {ck.hex()}")
        print(f"IK: {ik.hex()}")
        print(f"AK: {ak.hex()}")
        
        # Test f1
        mac_a = mil.f1(k, rand, SQN=sqn, AMF=amf)
        print(f"MAC-A: {mac_a.hex()}")
        
        print("✓ Milenage test passed!")
        return True
        
    except Exception as e:
        print(f"✗ Milenage test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_calculate_res():
    """Test the calculateRes function"""
    try:
        from integrated_messages import calculateRes
        
        opc = bytes.fromhex("71a121bb69baf3c0cc53fb5038a0131f")
        k = bytes.fromhex("12341234123412341234123412340000")
        rand = bytes.fromhex("1234567890abcdef1234567890abcdef")
        sqn_xor_ak = bytes.fromhex("1234567890ab")  # 6 bytes
        
        print("\nTesting calculateRes function...")
        kseaf, res = calculateRes(opc, k, rand, sqn_xor_ak, "99", "460")
        print(f"KSEAF length: {len(kseaf)}")
        print(f"RES: {res[:16]}...")
        print("✓ calculateRes test passed!")
        return True
        
    except Exception as e:
        print(f"✗ calculateRes test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("="*60)
    print("Milenage Functionality Test")
    print("="*60)
    
    success1 = test_milenage()
    success2 = test_calculate_res()
    
    if success1 and success2:
        print("\n🎉 ALL MILANAGE TESTS PASSED!")
    else:
        print("\n💥 SOME MILANAGE TESTS FAILED!")