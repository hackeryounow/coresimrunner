#!/usr/bin/env python3
"""
Full IMS Registration via UERANSIM uesimtun0.
Flow: REGISTER(initial) -> 401 -> REGISTER(auth) -> 200 OK -> SUBSCRIBE -> NOTIFY
"""
import socket
import random
import string
import time
import base64
import hashlib
import struct
import sys
import re
from CryptoMobile.Milenage import Milenage

# ======================== Configuration ========================
UE_IP = "172.29.0.18"
UE_PORT = 5060
PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
IMSI = "460090000000001"
MSISDN = "13300000001"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"
IMEI = "356938035643803"

# Subscriber credentials (from .env)
KI_HEX = "12341234123412341234123412340000"
OPC_HEX = "71a121bb69baf3c0cc53fb5038a0131f"

# Generate a stable UUID for Contact header (per pcap: UUID@UE_IP:PORT)
import uuid
CONTACT_UUID = str(uuid.uuid4())

# ======================== Milenage (via CryptoMobile) ========================
def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))

# ======================== AKA Digest ========================
def compute_aka_response(nonce_b64, ki_hex, opc_hex, username, realm, method, uri, cnonce, nc="00000001"):
    """
    Compute AKAv1-MD5 digest response per RFC 3310.
    
    Returns: (response_hex, res_hex, ck_hex, ik_hex)
    """
    K = bytes.fromhex(ki_hex)
    OPc = bytes.fromhex(opc_hex)

    # Decode nonce -> RAND (16) || AUTN (16)
    nonce_bytes = base64.b64decode(nonce_b64)
    RAND = nonce_bytes[:16]
    AUTN = nonce_bytes[16:32]

    # Extract SQN^AK and AMF from AUTN
    sqn_xor_ak = AUTN[0:6]
    amf_field = AUTN[6:8]

    # Milenage via CryptoMobile
    mil = Milenage(OPc)
    mil.set_opc(OPc)
    RES, CK, IK, AK = mil.f2345(K, RAND)
    SQN = xor_bytes(sqn_xor_ak, AK)

    # Verify MAC-A
    mac_a = mil.f1(K, RAND, SQN=SQN, AMF=amf_field)
    mac_a_received = AUTN[8:16]
    if mac_a != mac_a_received:
        print(f"  [WARN] MAC-A mismatch: computed={mac_a.hex()}, received={mac_a_received.hex()}")
    else:
        print(f"  [OK] MAC-A verified: {mac_a.hex()}")

    print(f"  RAND: {RAND.hex()}")
    print(f"  RES:  {RES.hex()}")
    print(f"  CK:   {CK.hex()}")
    print(f"  IK:   {IK.hex()}")
    print(f"  AK:   {AK.hex()}")
    print(f"  SQN:  {SQN.hex()}")

    # AKAv1-MD5 digest computation (RFC 3310 Section 3.2)
    # NOTE: Kamailio ims_auth uses RAW RES BYTES (not hex string) as password
    # HA1 = MD5(username:realm:RES_raw_bytes)
    ha1_input = f"{username}:{realm}:".encode() + RES
    ha1 = hashlib.md5(ha1_input).hexdigest()

    # HA2 = MD5(method:uri)
    ha2_str = f"{method}:{uri}"
    ha2 = hashlib.md5(ha2_str.encode()).hexdigest()

    # With qop=auth: response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
    response_str = f"{ha1}:{nonce_b64}:{nc}:{cnonce}:auth:{ha2}"
    response = hashlib.md5(response_str.encode()).hexdigest()

    return response, RES.hex(), CK.hex(), IK.hex()

# ======================== SIP Message Builders ========================
def rand_hex(n):
    return ''.join(random.choices(string.hexdigits[:16], k=n))

def build_security_client():
    spi_c = random.randint(100000000, 999999999)
    spi_s = random.randint(100000000, 999999999)
    # Use same port for both client and server to avoid IPSec redirection issues
    port_c = UE_PORT
    port_s = UE_PORT
    mechanisms = []
    for alg in ['hmac-md5-96', 'hmac-sha-1-96']:
        for ealg in ['des-ede3-cbc', 'aes-cbc', 'null']:
            mechanisms.append(
                f'ipsec-3gpp; alg={alg}; ealg={ealg}; '
                f'spi-c={spi_c}; spi-s={spi_s}; '
                f'port-c={port_c}; port-s={port_s}'
            )
    return 'Security-Client: ' + ','.join(mechanisms), spi_c, spi_s, port_c, port_s

def build_initial_register(call_id, from_tag, branch, cseq):
    sec_client_hdr, _, _, _, _ = build_security_client()
    # Contact uses UUID@UE_IP:PORT (per pcap reference, NOT IMSI directly)
    contact = (f'<sip:{CONTACT_UUID}@{UE_IP}:{UE_PORT}>;'
               f'+g.3gpp.accesstype="cellular2";audio;+g.3gpp.smsip;video;'
               f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
               f'+sip.instance="<urn:gsma:imei:{IMEI}>"')
    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={branch}\r\n"
        f"From: <sip:{IMSI}@{IMS_DOMAIN}>;tag={from_tag}\r\n"
        f"To: <sip:{IMSI}@{IMS_DOMAIN}>\r\n"
        f"CSeq: {cseq} REGISTER\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: {contact}\r\n"
        f"Expires: 600000\r\n"
        f"Require: sec-agree\r\n"
        f"Proxy-Require: sec-agree\r\n"
        f"Supported: path,sec-agree\r\n"
        f"Allow: INVITE,BYE,CANCEL,ACK,NOTIFY,UPDATE,PRACK,INFO,MESSAGE,OPTIONS\r\n"
        f'Authorization: Digest uri="sip:{IMS_DOMAIN}",'
        f'username="{IMSI}@{IMS_DOMAIN}",response="",'
        f'realm="{IMS_DOMAIN}",nonce="",algorithm=AKAv1-MD5\r\n'
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"{sec_client_hdr}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

def build_auth_register(call_id, from_tag, branch, cseq, nonce, realm,
                        response, cnonce, security_verify=""):
    sec_client_hdr, _, _, _, _ = build_security_client()
    # Contact uses UUID@UE_IP:PORT (per pcap reference)
    contact = (f'<sip:{CONTACT_UUID}@{UE_IP}:{UE_PORT}>;'
               f'+g.3gpp.accesstype="cellular2";audio;+g.3gpp.smsip;video;'
               f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
               f'+sip.instance="<urn:gsma:imei:{IMEI}>"')
    # NOTE: Do NOT include To-tag from 401 - REGISTER is not a dialog-forming request
    to_hdr = f"<sip:{IMSI}@{IMS_DOMAIN}>"
    
    auth_hdr = (f'Authorization: Digest username="{IMSI}@{IMS_DOMAIN}",'
                f'realm="{realm}",'
                f'uri="sip:{IMS_DOMAIN}",'
                f'qop=auth,'
                f'nonce="{nonce}",'
                f'nc=00000001,'
                f'cnonce="{cnonce}",'
                f'algorithm=AKAv1-MD5,'
                f'response="{response}"')

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={branch}\r\n"
        f"From: <sip:{IMSI}@{IMS_DOMAIN}>;tag={from_tag}\r\n"
        f"To: {to_hdr}\r\n"
        f"CSeq: {cseq} REGISTER\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: {contact}\r\n"
        f"Expires: 600000\r\n"
        f"Require: sec-agree\r\n"
        f"Proxy-Require: sec-agree\r\n"
        f"Supported: path,sec-agree\r\n"
        f"Allow: INVITE,BYE,CANCEL,ACK,NOTIFY,UPDATE,PRACK,INFO,MESSAGE,OPTIONS\r\n"
        f"{auth_hdr}\r\n"
    )
    if security_verify:
        msg += f"Security-Verify: {security_verify}\r\n"
    msg += (
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"{sec_client_hdr}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

def build_subscribe(call_id, from_tag, branch, cseq, service_route):
    """Build SUBSCRIBE for reg event package (per pcap: uses MSISDN, not IMSI)."""
    # Contact uses same UUID as REGISTER
    contact = f'<sip:{CONTACT_UUID}@{UE_IP}:{UE_PORT}>'
    # Route: P-CSCF first, then S-CSCF service route
    route_hdr = f'<sip:{PCSCF_IP}:{PCSCF_PORT};lr>'
    if service_route:
        route_hdr += f',<{service_route}>'
    msg = (
        f"SUBSCRIBE sip:{MSISDN}@{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={branch}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={from_tag}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"CSeq: {cseq} SUBSCRIBE\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: {contact}\r\n"
        f"Route: {route_hdr}\r\n"
        f"Event: reg\r\n"
        f"Expires: 600000\r\n"
        f"Accept: application/reginfo+xml\r\n"
        f"P-Preferred-Identity: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"P-Access-Network-Info: 3GPP-NR-TDD;utran-cell-id-3gpp=4600900000100066C000\r\n"
        f"Require: sec-agree\r\n"
        f"Proxy-Require: sec-agree\r\n"
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

def build_200_ok_notify(notify_msg):
    """Build 200 OK response to a NOTIFY (per pcap: multiple Via headers required)."""
    # Parse ALL Via headers (NOTIFY has Via from P-CSCF + S-CSCF)
    via_headers = re.findall(r'^Via: (.+)$', notify_msg, re.M | re.I)
    from_hdr = re.search(r'^From: (.+)$', notify_msg, re.M | re.I)
    to_hdr = re.search(r'^To: (.+)$', notify_msg, re.M | re.I)
    call_id = re.search(r'^Call-ID: (.+)$', notify_msg, re.M | re.I)
    cseq = re.search(r'^CSeq: (.+)$', notify_msg, re.M | re.I)

    to_val = to_hdr.group(1).strip() if to_hdr else ""
    if "tag=" not in to_val:
        to_val += f";tag={rand_hex(8)}"

    from_val = from_hdr.group(1).strip() if from_hdr else ""
    call_id_val = call_id.group(1).strip() if call_id else ""
    cseq_val = cseq.group(1).strip() if cseq else ""

    print(f"  [DEBUG] 200 OK to NOTIFY:")
    print(f"    Via headers: {len(via_headers)}")
    for i, v in enumerate(via_headers):
        print(f"      [{i}] {v[:60]}...")
    print(f"    Call-ID: {call_id_val}")
    print(f"    CSeq: {cseq_val}")

    # Build response with ALL Via headers (required for proper routing)
    msg = "SIP/2.0 200 OK\r\n"
    for via_val in via_headers:
        msg += f"Via: {via_val.strip()}\r\n"
    msg += (
        f"To: {to_val}\r\n"
        f"From: {from_val}\r\n"
        f"Call-ID: {call_id_val}\r\n"
        f"CSeq: {cseq_val}\r\n"
        f"Content-Length: 0\r\n"
        f"Server: CoreSimRunner-VoNR/1.0\r\n"
        f"P-Access-Network-Info: 3GPP-NR-TDD;utran-cell-id-3gpp=4600900000100066C000\r\n"
        f"\r\n"
    )
    return msg

# ======================== SIP Parser ========================
def parse_sip(data):
    """Parse SIP response, return dict with status_code and headers."""
    text = data.decode(errors='replace')
    lines = text.split('\r\n')
    status_line = lines[0]
    status_code = int(status_line.split(' ')[1]) if len(status_line.split(' ')) > 1 else 0
    
    headers = {}
    for line in lines[1:]:
        if not line:
            break
        if ':' in line:
            key, val = line.split(':', 1)
            headers[key.strip().lower()] = val.strip()
    
    return {'status_code': status_code, 'status_line': status_line, 
            'headers': headers, 'raw': text}

# ======================== Main Flow ========================
def main():
    print("=" * 70)
    print("IMS Registration via UERANSIM uesimtun0")
    print(f"  UE IP: {UE_IP}:{UE_PORT}")
    print(f"  P-CSCF: {PCSCF_IP}:{PCSCF_PORT}")
    print(f"  IMSI: {IMSI}")
    print(f"  Domain: {IMS_DOMAIN}")
    print("=" * 70)

    # Create UDP socket bound to uesimtun0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"uesimtun0")
    sock.bind((UE_IP, UE_PORT))
    sock.settimeout(10.0)

    # Create TCP socket for incoming NOTIFY (P-CSCF may use TCP)
    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"uesimtun0")
    tcp_sock.bind((UE_IP, UE_PORT))
    tcp_sock.listen(5)
    tcp_sock.settimeout(0.1)  # non-blocking for accept

    call_id = f"{rand_hex(16)}@{UE_IP}"
    from_tag = rand_hex(8)
    cseq = 1

    # ============ Step 1: Initial REGISTER ============
    print(f"\n[1] Sending initial REGISTER (no auth)...")
    branch = f"z9hG4bK{rand_hex(16)}"
    msg = build_initial_register(call_id, from_tag, branch, cseq)
    sock.sendto(msg.encode(), (PCSCF_IP, PCSCF_PORT))

    # Wait for 401
    nonce = None
    realm = None
    security_server = ""
    to_tag_401 = ""
    
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
            resp = parse_sip(data)
            print(f"  <- {resp['status_line']}")
            if resp['status_code'] == 401:
                www_auth = resp['headers'].get('www-authenticate', '')
                security_server = resp['headers'].get('security-server', '')
                # Extract nonce
                m = re.search(r'nonce="([^"]+)"', www_auth)
                if m:
                    nonce = m.group(1)
                m = re.search(r'realm="([^"]+)"', www_auth)
                if m:
                    realm = m.group(1)
                # Extract To tag
                to_hdr = resp['headers'].get('to', '')
                m = re.search(r'tag=([^\s;]+)', to_hdr)
                if m:
                    to_tag_401 = m.group(1)
                break
        except socket.timeout:
            break

    if not nonce:
        print("  [FAIL] No 401 received!")
        sock.close()
        return

    print(f"  Nonce: {nonce}")
    print(f"  Realm: {realm}")
    print(f"  Security-Server: {security_server}")

    # ============ Step 2: Compute AKA Response ============
    print(f"\n[2] Computing AKA (AKAv1-MD5)...")
    username = f"{IMSI}@{IMS_DOMAIN}"
    uri = f"sip:{IMS_DOMAIN}"
    cnonce = str(random.randint(1000000000, 9999999999))
    
    response, res_hex, ck_hex, ik_hex = compute_aka_response(
        nonce, KI_HEX, OPC_HEX, username, realm, "REGISTER", uri, cnonce)
    print(f"  Digest response: {response}")
    print(f"  cnonce: {cnonce}")

    # ============ Step 3: Authenticated REGISTER ============
    print(f"\n[3] Sending authenticated REGISTER...")
    cseq += 1
    branch = f"z9hG4bK{rand_hex(16)}"
    msg = build_auth_register(call_id, from_tag, branch, cseq, nonce, realm,
                              response, cnonce, security_server)
    sock.sendto(msg.encode(), (PCSCF_IP, PCSCF_PORT))

    # Wait for 200 OK
    service_route = ""
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
            resp = parse_sip(data)
            print(f"  <- {resp['status_line']}")
            if resp['status_code'] == 200:
                service_route = resp['headers'].get('service-route', '').strip('<>')
                p_assoc = resp['headers'].get('p-associated-uri', '')
                print(f"  Service-Route: {service_route}")
                print(f"  P-Associated-URI: {p_assoc}")
                print(f"\n  *** IMS REGISTRATION SUCCESSFUL ***")
                break
        except socket.timeout:
            break

    if not service_route:
        print("  [WARN] No 200 OK with Service-Route received")
        # Continue anyway for SUBSCRIBE

    # ============ Step 4: SUBSCRIBE (reg event) ============
    print(f"\n[4] Sending SUBSCRIBE (reg event)...")
    sub_call_id = f"{rand_hex(16)}@{UE_IP}"
    sub_from_tag = rand_hex(8)
    sub_cseq = 1
    branch = f"z9hG4bK{rand_hex(16)}"
    
    route = service_route if service_route else f"sip:orig@scscf.{IMS_DOMAIN}:6060;lr"
    msg = build_subscribe(sub_call_id, sub_from_tag, branch, sub_cseq, route)
    sock.sendto(msg.encode(), (PCSCF_IP, PCSCF_PORT))

    # Wait for 200 OK to SUBSCRIBE and then NOTIFY
    deadline = time.time() + 15
    got_notify = False
    tcp_conn = None
    while time.time() < deadline:
        # Check TCP for incoming NOTIFY
        try:
            conn, addr = tcp_sock.accept()
            conn.settimeout(5.0)
            data = conn.recv(65535)
            if data:
                text = data.decode(errors='replace')
                first_line = text.split('\r\n')[0]
                print(f"  <- [TCP] {first_line}")
                if first_line.startswith('NOTIFY'):
                    got_notify = True
                    print(f"\n[5] Received NOTIFY via TCP, sending 200 OK...")
                    event_m = re.search(r'^Event: (.+)$', text, re.M)
                    sub_state_m = re.search(r'^Subscription-State: (.+)$', text, re.M)
                    if event_m:
                        print(f"  Event: {event_m.group(1)}")
                    if sub_state_m:
                        print(f"  Subscription-State: {sub_state_m.group(1)}")
                    ok_msg = build_200_ok_notify(text)
                    conn.sendall(ok_msg.encode())
                    print(f"  -> 200 OK (to NOTIFY via TCP)")
                    body_start = text.find('\r\n\r\n')
                    if body_start > 0:
                        body = text[body_start+4:]
                        if body.strip():
                            print(f"\n  Body (reginfo):")
                            print(f"  {body[:500]}")
                    tcp_conn = conn
                    break
        except socket.timeout:
            pass
        except OSError:
            pass

        # Check UDP for responses
        try:
            data, addr = sock.recvfrom(65535)
            text = data.decode(errors='replace')
            first_line = text.split('\r\n')[0]
            print(f"  <- {first_line}")
            
            if first_line.startswith('NOTIFY'):
                got_notify = True
                print(f"\n[5] Received NOTIFY via UDP, sending 200 OK...")
                event_m = re.search(r'^Event: (.+)$', text, re.M)
                sub_state_m = re.search(r'^Subscription-State: (.+)$', text, re.M)
                if event_m:
                    print(f"  Event: {event_m.group(1)}")
                if sub_state_m:
                    print(f"  Subscription-State: {sub_state_m.group(1)}")
                ok_msg = build_200_ok_notify(text)
                sock.sendto(ok_msg.encode(), addr)
                print(f"  -> 200 OK (to NOTIFY via UDP)")
                body_start = text.find('\r\n\r\n')
                if body_start > 0:
                    body = text[body_start+4:]
                    if body.strip():
                        print(f"\n  Body (reginfo):")
                        print(f"  {body[:500]}")
                break
            elif '200' in first_line:
                print(f"  (200 OK to SUBSCRIBE)")
        except socket.timeout:
            pass

    if not got_notify:
        print("  [INFO] No NOTIFY received (may be normal)")

    # ============ Step 6: Unsubscribe (Expires: 0) ============
    print(f"\n[6] Sending SUBSCRIBE with Expires: 0 to terminate subscription...")
    unsub_branch = f"z9hG4bK{rand_hex(16)}"
    unsub_msg = (
        f"SUBSCRIBE sip:{MSISDN}@{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={unsub_branch}\r\n"
        f"From: <sip:{MSISDN}@{IMS_DOMAIN}>;tag={sub_from_tag}\r\n"
        f"To: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"CSeq: {sub_cseq + 1} SUBSCRIBE\r\n"
        f"Call-ID: {sub_call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: <sip:{CONTACT_UUID}@{UE_IP}:{UE_PORT}>\r\n"
        f"Route: <sip:{PCSCF_IP}:{PCSCF_PORT};lr>"
    )
    if service_route:
        unsub_msg += f",<{service_route}>"
    unsub_msg += (
        f"\r\n"
        f"Event: reg\r\n"
        f"Expires: 0\r\n"
        f"Accept: application/reginfo+xml\r\n"
        f"P-Preferred-Identity: <sip:{MSISDN}@{IMS_DOMAIN}>\r\n"
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    sock.sendto(unsub_msg.encode(), (PCSCF_IP, PCSCF_PORT))
    # Wait for 200 OK to unsubscribe
    try:
        sock.settimeout(3.0)
        data, addr = sock.recvfrom(65535)
        text = data.decode(errors='replace')
        first_line = text.split('\r\n')[0]
        print(f"  <- {first_line}")
    except socket.timeout:
        print("  (no response to unsubscribe)")

    # ============ Summary ============
    print(f"\n{'=' * 70}")
    print(f"IMS Registration Flow Complete")
    print(f"  Registration: {'OK' if service_route else 'PENDING'}")
    print(f"  SUBSCRIBE:    Sent")
    print(f"  NOTIFY:       {'Received' if got_notify else 'Not received'}")
    print(f"  Unsubscribe:  Sent (Expires: 0)")
    print(f"{'=' * 70}")

    if tcp_conn:
        tcp_conn.close()
    tcp_sock.close()
    sock.close()

if __name__ == "__main__":
    main()
