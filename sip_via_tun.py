#!/usr/bin/env python3
"""Send SIP REGISTER through uesimtun1 (UERANSIM IMS PDU session)."""
import socket
import sys
import random
import string
import time

UE_IP = "172.29.0.14"
UE_PORT = 5060
PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
IMSI = "460090000000001"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"
IMEI = "356938035643803"

def build_register():
    branch = "z9hG4bK" + ''.join(random.choices(string.hexdigits[:16], k=16))
    from_tag = ''.join(random.choices(string.hexdigits[:16], k=8))
    call_id = ''.join(random.choices(string.hexdigits[:16], k=16)) + "@" + UE_IP
    cseq = 1

    from_uri = f"sip:{IMSI}@{IMS_DOMAIN}"
    to_uri = f"sip:{IMSI}@{IMS_DOMAIN}"
    contact_uri = f"sip:{IMSI}@{UE_IP}:{UE_PORT};transport=udp"

    # Security-Client with 6 mechanisms
    spi_c = random.randint(100000000, 999999999)
    spi_s = random.randint(100000000, 999999999)
    port_c = UE_PORT + 2
    port_s = UE_PORT + 1
    algs = ['hmac-md5-96', 'hmac-sha-1-96']
    ealgs = ['des-ede3-cbc', 'aes-cbc', 'null']
    mechanisms = []
    for alg in algs:
        for ealg in ealgs:
            mechanisms.append(
                f'ipsec-3gpp; alg={alg}; ealg={ealg}; '
                f'spi-c={spi_c}; spi-s={spi_s}; '
                f'port-c={port_c}; port-s={port_s}'
            )
    security_client = 'Security-Client: ' + ','.join(mechanisms)

    msg = (
        f"REGISTER sip:{IMS_DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={branch}\r\n"
        f"From: <{from_uri}>;tag={from_tag}\r\n"
        f"To: <{to_uri}>\r\n"
        f"CSeq: {cseq} REGISTER\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: <{contact_uri}>;"
        f'+g.3gpp.accesstype="cellular2";audio;+g.3gpp.smsip;video;'
        f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
        f'+sip.instance="<urn:gsma:imei:{IMEI}>"\r\n'
        f"Expires: 600000\r\n"
        f"Require: sec-agree\r\n"
        f"Proxy-Require: sec-agree\r\n"
        f"Supported: path,sec-agree\r\n"
        f"Allow: INVITE,BYE,CANCEL,ACK,NOTIFY,UPDATE,PRACK,INFO,MESSAGE,OPTIONS\r\n"
        f'Authorization: Digest uri="sip:{IMS_DOMAIN}",'
        f'username="{IMSI}@{IMS_DOMAIN}",response="",'
        f'realm="{IMS_DOMAIN}",nonce=""\r\n'
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"{security_client}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

def main():
    # Create UDP socket bound to uesimtun1
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"uesimtun1")
    sock.bind((UE_IP, UE_PORT))
    sock.settimeout(10.0)

    register_msg = build_register()
    print(f"=== Sending SIP REGISTER via uesimtun1 ===")
    print(f"  Source: {UE_IP}:{UE_PORT}")
    print(f"  Dest:   {PCSCF_IP}:{PCSCF_PORT}")
    print(f"  Length: {len(register_msg)} bytes")
    print()
    print(register_msg)

    sock.sendto(register_msg.encode(), (PCSCF_IP, PCSCF_PORT))
    print("[SENT] Waiting for response...")

    try:
        data, addr = sock.recvfrom(65535)
        response = data.decode(errors='replace')
        print(f"\n[RECEIVED] From {addr}:")
        print(response)
    except socket.timeout:
        print("\n[TIMEOUT] No response received in 10s")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
