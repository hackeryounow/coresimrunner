#!/usr/bin/env python3
"""
CoreSimRunner Internal NAS MAC Calculator for Security Mode Complete.

Uses the EXACT same internal functions from integrated_4g_messages.py and eNAS.py
to compute the MAC for a Security Mode Complete message.

This is useful for comparing CoreSimRunner's internal computation with the
eNB reference (eNB/enb_compute_mac.py).

Usage:
    # Build SMC Complete from IMEISV
    python3 src/tests/test_compute_smc_mac.py \
        --plmn 46099 \
        --ki 465B5CE8B199B49FAA5F0A2EE238A6BC \
        --opc E8ED289DEBA952E4283B54E88E6183CA \
        --rand 627aa36be9d754fae47aabb1391edb77 \
        --autn b0fd44d82c318000f646d40f7e29ee20 \
        --enc-alg 0 --int-alg 2 --up-count 0 \
        --imeisv 1234567890123456

    # Use a captured plain NAS hex
    python3 src/tests/test_compute_smc_mac.py \
        --plmn 46099 \
        --ki 465B5CE8B199B49FAA5F0A2EE238A6BC \
        --opc E8ED289DEBA952E4283B54E88E6183CA \
        --rand 608a7424eab77464673c5b10467918e2 \
        --autn 1c09757fb6b880001cb68c7d410c8b75 \
        --enc-alg 0 \
        --int-alg 2 \
        --up-count 0 \
        --smc-complete-plain 075e23094309512430325781f6
"""

import sys
import os
import argparse
from binascii import hexlify, unhexlify

# Add paths for internal imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, '/root/pycrate')
sys.path.insert(0, '/root/CryptoMobile')

from coresimrunner.integration.integrated_4g_messages import (
    milenage_res_ck_ik,
    return_kasme,
    derive_all_nas_keys,
    set_key,
    nas_encrypt_func,
    nas_hash_func,
    nas_security_protected_nas_message,
    nas_security_mode_complete,
    return_plmn_s1ap,
)
from coresimrunner.integration.eNAS import bcd


def compute_smc_complete_mac(plmn, ki_hex, opc_hex, rand_hex, autn_hex,
                              enc_alg, int_alg, up_count, imeisv, smc_complete_plain_hex):
    """
    Compute SMC Complete MAC using CoreSimRunner internal functions.

    Replicates the flow in Integrated4GUE._handle_security_mode_command():
    1. Milenage -> RES, CK, IK
    2. KASME derivation
    3. NAS key derivation
    4. Build/encrypt SMC Complete
    5. Compute MAC
    """

    print("=" * 70)
    print("CoreSimRunner Internal: Security Mode Complete MAC Computation")
    print("=" * 70)

    # Step 1: Milenage
    print("\n[1] Milenage (RES, CK, IK)")
    print("-" * 40)
    ki = unhexlify(ki_hex)
    opc = unhexlify(opc_hex)
    res, ck, ik = milenage_res_ck_ik(ki, opc, rand_hex)
    print(f"  RES:  {res}")
    print(f"  CK:   {ck}")
    print(f"  IK:   {ik}")

    # Step 2: KASME
    print("\n[2] KASME Derivation")
    print("-" * 40)
    kasme = return_kasme(plmn, autn_hex, ck, ik)
    kasme_hex = hexlify(kasme).decode()
    plmn_encoded = hexlify(return_plmn_s1ap(plmn)).decode()
    print(f"  KASME: {kasme_hex}")
    print(f"  PLMN encoding (return_plmn_s1ap): {plmn_encoded}")

    # Step 3: NAS keys
    print("\n[3] NAS Key Derivation")
    print("-" * 40)
    nas_keys = derive_all_nas_keys(kasme)
    for k, v in nas_keys.items():
        print(f"  {k}: {hexlify(v).decode()}")

    enc_key, int_key = set_key(enc_alg, int_alg, nas_keys)
    print(f"\n  Active keys for ENC_ALG={enc_alg}, INT_ALG={int_alg}:")
    print(f"    ENC-KEY: {hexlify(enc_key).decode() if enc_key else 'None (EEA0)'}")
    print(f"    INT-KEY: {hexlify(int_key).decode() if int_key else 'None (EIA0)'}")

    # Step 4: Build SMC Complete plain NAS
    print("\n[4] Security Mode Complete NAS Message")
    print("-" * 40)
    if smc_complete_plain_hex:
        nas_plain = bytes.fromhex(smc_complete_plain_hex)
        print(f"  Plain NAS (from --smc-complete-plain): {hexlify(nas_plain).decode()}")
    else:
        nas_plain = nas_security_mode_complete(imeisv)
        print(f"  Plain NAS (built from IMEISV={imeisv}): {hexlify(nas_plain).decode()}")
    print(f"  Length: {len(nas_plain)} bytes")

    # Step 5: Encrypt
    print("\n[5] NAS Encryption")
    print("-" * 40)
    nas_encrypted = nas_encrypt_func(nas_plain, up_count, 0, enc_key, enc_alg)
    print(f"  COUNT:     {up_count}")
    print(f"  DIRECTION: 0 (uplink)")
    print(f"  ENC-ALG:   {enc_alg}")
    print(f"  Encrypted: {hexlify(nas_encrypted).decode()}")
    if nas_encrypted == nas_plain:
        print(f"  (unchanged — EEA0 or null encryption)")

    # Step 6: Compute MAC
    print("\n[6] MAC Computation")
    print("-" * 40)
    mac = nas_hash_func(nas_encrypted, up_count, 0, int_key, int_alg)
    mac_hex = hexlify(mac).decode()
    print(f"  INT-ALG:   {int_alg}")
    print(f"  EIA input: {hexlify(bytes([up_count % 256]) + nas_encrypted).decode()}")
    print(f"  MAC-I:     0x{mac_hex}")

    # Step 7: Full protected message
    print("\n[7] Security-Protected NAS Message")
    print("-" * 40)
    sqn_byte = bytes([up_count % 256])
    security_header = 4  # new EPS security context
    protected = nas_security_protected_nas_message(security_header, mac, sqn_byte, nas_encrypted)
    print(f"  Security Header: 4 (integrity + ciphered + new EPS security context)")
    print(f"  MAC:             {hexlify(mac).decode()}")
    print(f"  SQN:             {hexlify(sqn_byte).decode()}")
    print(f"  Full protected:  {hexlify(protected).decode()}")

    print("\n" + "=" * 70)
    print(f"FINAL MAC-I: 0x{mac_hex}")
    print("=" * 70)

    return mac_hex, protected


def main():
    parser = argparse.ArgumentParser(
        description='CoreSimRunner Internal: Compute SMC Complete MAC using integrated_4g_messages.py functions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--plmn', required=True, help='PLMN (e.g., 46099)')
    parser.add_argument('--ki', required=True, help='KI hex (16 bytes)')
    parser.add_argument('--opc', required=True, help='OPC hex (16 bytes)')
    parser.add_argument('--rand', required=True, help='RAND hex (16 bytes)')
    parser.add_argument('--autn', required=True, help='AUTN hex (16 bytes)')
    parser.add_argument('--enc-alg', type=int, default=0, choices=[0, 1, 2, 3],
                        help='Encryption algo: 0=EEA0, 1=EEA1, 2=EEA2, 3=EEA3')
    parser.add_argument('--int-alg', type=int, default=2, choices=[0, 1, 2, 3],
                        help='Integrity algo: 0=EIA0, 1=EIA1, 2=EIA2, 3=EIA3')
    parser.add_argument('--up-count', type=int, default=0,
                        help='UP-COUNT for MAC computation (default 0)')
    parser.add_argument('--imeisv', default=None,
                        help='IMEISV string (e.g., 4370816125816151)')
    parser.add_argument('--smc-complete-plain', default=None,
                        help='Plain SMC Complete NAS hex (alternative to --imeisv)')

    args = parser.parse_args()

    compute_smc_complete_mac(
        plmn=args.plmn,
        ki_hex=args.ki,
        opc_hex=args.opc,
        rand_hex=args.rand,
        autn_hex=args.autn,
        enc_alg=args.enc_alg,
        int_alg=args.int_alg,
        up_count=args.up_count,
        imeisv=args.imeisv,
        smc_complete_plain_hex=args.smc_complete_plain,
    )


if __name__ == '__main__':
    main()
