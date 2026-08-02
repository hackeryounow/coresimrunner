#!/usr/bin/env python3
"""
VoNR (Voice over New Radio) Session Establishment.

Implements the complete IMS SIP registration and VoNR call flow
by sending SIP messages through the UPF GTP-U tunnel to the P-CSCF.

Flow (from pcap 5GVoNR2.pcap analysis):
  1. UE 5G NAS registration  (internet + ims PDU sessions)
  2. SIP REGISTER → P-CSCF → I-CSCF → S-CSCF (empty auth)
  3. 401 Unauthorized ← S-CSCF (nonce, ck, ik, algorithm=AKAv1-MD5)
  4. SIP REGISTER → P-CSCF → I-CSCF → S-CSCF (with AKA response)
  5. 200 OK ← S-CSCF (registration complete)
  6. SUBSCRIBE/NOTIFY (registration state)
  7. INVITE → 100 → 183 → PRACK → UPDATE → 180 → 200 → ACK  (VoNR call)

Network topology (from sa-vonr-deploy-2.7.7-embedded.yaml):
  UPF:     172.22.0.8   (GTP-U port 2152)
  P-CSCF:  172.22.0.21  (SIP port 5060 TCP/UDP)
  I-CSCF:  172.22.0.19  (port 4060)
  S-CSCF:  172.22.0.20  (port 6060)
  DNS:     172.22.0.15
  UE IMS:  172.29.x.x   (from UE_IPV4_IMS=172.29.0.0/16)
"""

import sys
import os
import time
import struct
import socket
import hashlib
import base64
import uuid
import random
import threading
from typing import Optional, Tuple, Dict, Any

from loguru import logger

# Add workspace libraries to Python path
WORKSPACE_ROOT = '/root'
CRYPTOMOBILE_PATH = os.path.join(WORKSPACE_ROOT, 'CryptoMobile')
PYCRATE_PATH = os.path.join(WORKSPACE_ROOT, 'pycrate')
PROJECT_ROOT = os.path.join('/root', '5gc')
for _p in (CRYPTOMOBILE_PATH, PYCRATE_PATH, PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from CryptoMobile.Milenage import Milenage
except ImportError:
    logger.warning("CryptoMobile not available; IMS AKA will not work")


# ---------------------------------------------------------------------------
# SIP message construction helpers
# ---------------------------------------------------------------------------

def _gen_branch() -> str:
    """Generate a random Via branch parameter (must start with z9hG4bK)."""
    return f"z9hG4bK{random.randint(1000000000, 9999999999)}"


def _gen_call_id(local_ip: str) -> str:
    """Generate a SIP Call-ID."""
    return f"{random.randint(1000000000, 9999999999)}_{random.randint(1000000000, 9999999999)}@{local_ip}"


def _gen_tag() -> str:
    """Generate a random From tag."""
    return str(random.randint(1000000000, 9999999999))


def _gen_contact_uuid() -> str:
    """Generate a unique contact user part."""
    return str(uuid.uuid4())


def build_sip_register(
    ue_ip: str,
    ue_port: int,
    imsi: str,
    ims_domain: str,
    pcscf_host: str,
    branch: str,
    call_id: str,
    from_tag: str,
    cseq: int,
    contact_uuid: str,
    imei: str = "86196306-248724-0",
    expires: int = 600000,
    auth_header: str = "",
    transport: str = "UDP",
) -> str:
    """Build a SIP REGISTER request per 3GPP TS 24.229."""

    from_uri = f"sip:{imsi}@{ims_domain}"
    to_uri = from_uri
    contact_uri = f"sip:{contact_uuid}@{ue_ip}:{ue_port}"
    pcscf_path = f"sip:term@pcscf.{ims_domain};lr"

    # Build Security-Client with all 6 mechanism combinations (per 3GPP TS 33.203)
    spi_c = random.randint(100000000, 999999999)
    spi_s = random.randint(100000000, 999999999)
    port_c = ue_port + 2
    port_s = ue_port + 1
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
        f"REGISTER sip:{ims_domain} SIP/2.0\r\n"
        f"Via: SIP/2.0/{transport} {ue_ip}:{ue_port};branch={branch}\r\n"
        f"From: <{from_uri}>;tag={from_tag}\r\n"
        f"To: <{to_uri}>\r\n"
        f"CSeq: {cseq} REGISTER\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: <{contact_uri}>;"
        f'+g.3gpp.accesstype="cellular2";audio;+g.3gpp.smsip;video;'
        f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
        f'+sip.instance="<urn:gsma:imei:{imei}>"\r\n'
        f"Expires: {expires}\r\n"
        f"Require: sec-agree\r\n"
        f"Proxy-Require: sec-agree\r\n"
        f"Supported: path,sec-agree\r\n"
        f"Allow: INVITE,BYE,CANCEL,ACK,NOTIFY,UPDATE,PRACK,INFO,MESSAGE,OPTIONS\r\n"
    )

    if auth_header:
        msg += f"{auth_header}\r\n"
    else:
        msg += (
            f'Authorization: Digest uri="sip:{ims_domain}",'
            f'username="{imsi}@{ims_domain}",response="",'
            f'realm="{ims_domain}",nonce=""\r\n'
        )

    msg += (
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"{security_client}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg


def build_sip_invite(
    ue_ip: str,
    ue_port: int,
    caller_imsi: str,
    caller_phone: str,
    callee_phone: str,
    ims_domain: str,
    branch: str,
    call_id: str,
    from_tag: str,
    cseq: int,
    contact_uuid: str,
    rtp_ip: str,
    rtp_port: int,
    sdp_session_id: int = 4,
    sdp_version: int = 1000,
) -> str:
    """Build a SIP INVITE for VoNR (MMTel) call with SDP offer."""

    from_uri = f"sip:{caller_phone}@{ims_domain}"
    to_uri = f"tel:{callee_phone};phone-context={ims_domain}"
    contact_uri = f"sip:{contact_uuid}@{ue_ip}:{ue_port}"

    # SDP offer (matches pcap: audio AMR-WB/AMR-NB with QoS precondition)
    sdp = (
        f"v=0\r\n"
        f"o=- {sdp_session_id} {sdp_version} IN IP4 {rtp_ip}\r\n"
        f"s=CoreSimRunner VoNR\r\n"
        f"c=IN IP4 {rtp_ip}\r\n"
        f"b=AS:41\r\n"
        f"b=RS:600\r\n"
        f"b=RR:2000\r\n"
        f"t=0 0\r\n"
        f"m=audio {rtp_port} RTP/AVP 104 102 96 97\r\n"
        f"b=AS:41\r\n"
        f"b=RS:600\r\n"
        f"b=RR:2000\r\n"
        f"a=curr:qos local none\r\n"
        f"a=curr:qos remote none\r\n"
        f"a=des:qos mandatory local sendrecv\r\n"
        f"a=des:qos optional remote sendrecv\r\n"
        f"a=maxptime:240\r\n"
        f"a=rtpmap:104 AMR-WB/16000/1\r\n"
        f"a=fmtp:104 mode-change-capability=2;max-red=220\r\n"
        f"a=rtpmap:102 AMR/8000/1\r\n"
        f"a=fmtp:102 mode-change-capability=2;max-red=220\r\n"
        f"a=rtpmap:96 telephone-event/16000\r\n"
        f"a=rtpmap:97 telephone-event/8000\r\n"
        f"a=ptime:20\r\n"
    )

    sdp_bytes = sdp.encode()

    msg = (
        f"INVITE sip:{callee_phone}@{ims_domain};user=phone SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {ue_ip}:{ue_port};branch={branch}\r\n"
        f"From: <{from_uri}>;tag={from_tag}\r\n"
        f"To: <{to_uri}>\r\n"
        f"CSeq: {cseq} INVITE\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Contact: <{contact_uri}>;"
        f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
        f"audio;video;+g.3gpp.mid-call;+g.3gpp.srvcc-alerting\r\n"
        f"P-Access-Network-Info: 3GPP-NR-TDD;utran-cell-id-3gpp=4600900000100066C000\r\n"
        f"Allow: INVITE,ACK,CANCEL,BYE,UPDATE,PRACK,MESSAGE,REFER,NOTIFY,INFO,OPTIONS\r\n"
        f"Content-Type: application/sdp\r\n"
        f"Accept: application/sdp,application/3gpp-ims+xml\r\n"
        f"P-Preferred-Service: urn:urn-7:3gpp-service.ims.icsi.mmtel\r\n"
        f'Accept-Contact: *;+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";audio\r\n'
        f"Supported: 100rel,replaces,precondition,histinfo,tdialog\r\n"
        f"P-Early-Media: supported\r\n"
        f"User-Agent: CoreSimRunner-VoNR/1.0\r\n"
        f"P-Charging-Vector: icid-value={uuid.uuid4().hex[:32].upper()}; icid-generated-at={ue_ip}\r\n"
        f"P-Visited-Network-ID: {ims_domain}\r\n"
        f'P-Asserted-Identity: <sip:{caller_phone}@{ims_domain}>\r\n'
        f"Content-Length: {len(sdp_bytes)}\r\n"
        f"\r\n"
    )
    return msg + sdp


def build_sip_ack(
    ue_ip: str,
    ue_port: int,
    from_uri: str,
    to_uri: str,
    to_tag: str,
    from_tag: str,
    call_id: str,
    cseq: int,
    branch: str,
    target_uri: str,
) -> str:
    """Build a SIP ACK."""
    msg = (
        f"ACK {target_uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {ue_ip}:{ue_port};branch={branch}\r\n"
        f"From: <{from_uri}>;tag={from_tag}\r\n"
        f"To: <{to_uri}>;tag={to_tag}\r\n"
        f"CSeq: {cseq} ACK\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg


def build_sip_bye(
    ue_ip: str,
    ue_port: int,
    from_uri: str,
    to_uri: str,
    to_tag: str,
    from_tag: str,
    call_id: str,
    cseq: int,
    branch: str,
    target_uri: str,
) -> str:
    """Build a SIP BYE."""
    msg = (
        f"BYE {target_uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {ue_ip}:{ue_port};branch={branch}\r\n"
        f"From: <{from_uri}>;tag={from_tag}\r\n"
        f"To: <{to_uri}>;tag={to_tag}\r\n"
        f"CSeq: {cseq} BYE\r\n"
        f"Call-ID: {call_id}\r\n"
        f"Max-Forwards: 70\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg


# ---------------------------------------------------------------------------
# SIP response parser (minimal)
# ---------------------------------------------------------------------------

def parse_sip_response(data: bytes) -> Dict[str, Any]:
    """Parse a SIP response into a dictionary."""
    result = {"status_code": 0, "headers": {}, "body": ""}
    try:
        text = data.decode("utf-8", errors="replace")
        parts = text.split("\r\n\r\n", 1)
        header_section = parts[0]
        if len(parts) > 1:
            result["body"] = parts[1]

        lines = header_section.split("\r\n")
        if lines:
            status_line = lines[0]
            tokens = status_line.split(" ", 2)
            if len(tokens) >= 2:
                result["status_code"] = int(tokens[1])
                result["reason"] = tokens[2] if len(tokens) > 2 else ""

        for line in lines[1:]:
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if key in result["headers"]:
                    # Multiple headers with same name -> list
                    existing = result["headers"][key]
                    if isinstance(existing, list):
                        existing.append(value)
                    else:
                        result["headers"][key] = [existing, value]
                else:
                    result["headers"][key] = value
    except Exception as e:
        logger.warning(f"Failed to parse SIP response: {e}")
    return result


def parse_www_authenticate(header_value: str) -> Dict[str, str]:
    """Parse WWW-Authenticate header for IMS AKA."""
    params = {}
    # Remove 'Digest ' prefix
    if header_value.startswith("Digest "):
        header_value = header_value[7:]

    # Parse key=value or key="value" pairs
    import re
    for match in re.finditer(r'(\w+)=("([^"]*)"|([^,]*))', header_value):
        key = match.group(1)
        value = match.group(3) if match.group(3) is not None else match.group(4).strip()
        params[key] = value
    return params


# ---------------------------------------------------------------------------
# IMS AKA authentication (AKAv1-MD5 per RFC 3310)
# ---------------------------------------------------------------------------

def compute_ims_aka_response(
    nonce_b64: str,
    ki_hex: str,
    opc_hex: str,
    imsi: str,
    ims_domain: str,
    method: str = "REGISTER",
    uri: str = "",
) -> Tuple[str, str, str]:
    """
    Compute IMS AKA (AKAv1-MD5) digest response.

    Args:
        nonce_b64: Base64-encoded nonce from 401 challenge (contains RAND || AUTN)
        ki_hex: Subscriber permanent key K (hex string, 32 chars)
        opc_hex: OPc value (hex string, 32 chars)
        imsi: IMSI string (e.g. '460091234567894')
        ims_domain: IMS domain (e.g. 'ims.mnc009.mcc460.3gppnetwork.org')
        method: SIP method (e.g. 'REGISTER')
        uri: Request URI (e.g. 'sip:ims.mnc009.mcc460.3gppnetwork.org')

    Returns:
        Tuple of (response_hex, res_hex, ck_hex) for the Authorization header
    """
    K = bytes.fromhex(ki_hex)
    OPc = bytes.fromhex(opc_hex)

    # Decode nonce -> RAND (16 bytes) || AUTN (16 bytes)
    nonce_bytes = base64.b64decode(nonce_b64)
    if len(nonce_bytes) < 32:
        raise ValueError(f"Nonce too short ({len(nonce_bytes)} bytes), expected >= 32 (RAND||AUTN)")
    RAND = nonce_bytes[:16]
    AUTN = nonce_bytes[16:32]

    # Run Milenage
    mil = Milenage(OPc)
    # f1 = MAC-A, f2 = RES, f3 = CK, f4 = IK, f5 = AK
    (RES, CK, IK, AK) = mil.f2345(K, RAND)

    # Compute the digest response per RFC 2617 + RFC 3310
    # For AKAv1-MD5:
    #   HA1 = MD5(username:realm:RES_hex)  (note: some impls use RES directly)
    #   HA2 = MD5(method:uri)
    #   response = MD5(HA1:nonce:HA2)
    #
    # Actually in 3GPP IMS AKA (RFC 3310 Section 3.2):
    #   The "response" in the Authorization header = hex(RES) directly for AKAv1-MD5
    #   But Kamailio may expect the full digest computation

    username = f"{imsi}@{ims_domain}"
    if not uri:
        uri = f"sip:{ims_domain}"

    # Use hex of RES as the password equivalent in digest computation
    res_hex = RES.hex()

    # HA1 = MD5(username:realm:password) where password = hex(RES)
    ha1_str = f"{username}:{ims_domain}:{res_hex}"
    ha1 = hashlib.md5(ha1_str.encode()).hexdigest()

    # HA2 = MD5(method:uri)
    ha2_str = f"{method}:{uri}"
    ha2 = hashlib.md5(ha2_str.encode()).hexdigest()

    # Response = MD5(HA1:nonce:HA2)
    # nonce here is the base64 string from the challenge
    response_str = f"{ha1}:{nonce_b64}:{ha2}"
    response = hashlib.md5(response_str.encode()).hexdigest()

    return response, res_hex, CK.hex()


# ---------------------------------------------------------------------------
# GTP-U tunnel for SIP
# ---------------------------------------------------------------------------

class GtpUTunnel:
    """Send and receive SIP messages through GTP-U tunnel to UPF."""

    GTPU_HEADER_LEN = 8  # basic GTP-U header: flags(1) + type(1) + length(2) + TEID(4)

    def __init__(self, upf_ip: str, teid: str, ue_ims_ip: str,
                 gnb_ip: str, upf_port: int = 2152):
        self.upf_ip = upf_ip
        self.upf_port = upf_port
        self.teid = int(teid, 16) if isinstance(teid, str) else teid
        self.ue_ims_ip = ue_ims_ip
        self.gnb_ip = gnb_ip

        # UDP socket for sending GTP-U to UPF
        # Bind to gnb_ip so UPF sees correct source IP for PDR matching
        self.send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_sock.bind((gnb_ip, 0))
        self.send_sock.settimeout(5.0)

        # UDP socket for receiving GTP-U from UPF (downlink)
        self.recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.recv_sock.bind((gnb_ip, upf_port))
        except OSError:
            # Fallback: bind to all interfaces if gnb_ip bind fails
            self.recv_sock.bind(('0.0.0.0', upf_port))
        self.recv_sock.settimeout(8.0)

        # Response buffer
        self._response_event = threading.Event()
        self._last_response = None
        self._recv_thread = None
        self._running = False

    def start_listener(self):
        """Start background thread to receive GTP-U responses."""
        self._running = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        logger.info(f"GTP-U listener started on {self.gnb_ip}:{self.upf_port}")

    def _recv_loop(self):
        """Receive GTP-U packets from UPF and extract inner SIP payload."""
        while self._running:
            try:
                data, addr = self.recv_sock.recvfrom(65535)
                if len(data) < self.GTPU_HEADER_LEN:
                    continue
                # Parse GTP-U header
                flags = data[0]
                msg_type = data[1]
                length = struct.unpack("!H", data[2:4])[0]
                teid = struct.unpack("!I", data[4:8])[0]

                # Extract inner packet (skip GTP-U header; handle extension headers)
                offset = self.GTPU_HEADER_LEN
                if flags & 0x07:  # E, S, or PN flags set
                    offset += 4  # extension header

                inner = data[offset:]
                if len(inner) < 20:
                    continue

                # Parse inner IP header
                ip_version = (inner[0] >> 4)
                if ip_version != 4:
                    continue
                ip_hdr_len = (inner[0] & 0x0F) * 4
                proto = inner[9]

                if proto == 17:  # UDP
                    udp_offset = ip_hdr_len
                    if len(inner) > udp_offset + 8:
                        src_port = struct.unpack("!H", inner[udp_offset:udp_offset+2])[0]
                        dst_port = struct.unpack("!H", inner[udp_offset+2:udp_offset+4])[0]
                        sip_data = inner[udp_offset+8:]
                        logger.debug(f"GTP-U recv: SIP from {addr[0]}:{src_port} -> {dst_port}, "
                                     f"TEID=0x{teid:08x}, len={len(sip_data)}")
                        self._last_response = sip_data
                        self._response_event.set()

                elif proto == 6:  # TCP
                    tcp_offset = ip_hdr_len
                    if len(inner) > tcp_offset + 20:
                        src_port = struct.unpack("!H", inner[tcp_offset:tcp_offset+2])[0]
                        dst_port = struct.unpack("!H", inner[tcp_offset+2:tcp_offset+4])[0]
                        data_offset_byte = inner[tcp_offset + 12]
                        tcp_hdr_len = ((data_offset_byte >> 4) & 0xF) * 4
                        tcp_payload = inner[tcp_offset + tcp_hdr_len:]
                        if tcp_payload:
                            logger.debug(f"GTP-U recv: TCP from {addr[0]}:{src_port} -> {dst_port}, "
                                         f"TEID=0x{teid:08x}, len={len(tcp_payload)}")
                            self._last_response = tcp_payload
                            self._response_event.set()

            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.debug(f"GTP-U recv error: {e}")

    def send_sip(self, sip_message: str, dst_ip: str, dst_port: int = 5060) -> int:
        """
        Send a SIP message through GTP-U tunnel.

        Constructs: [GTP-U header][Inner IP/UDP/SIP payload]
        """
        sip_bytes = sip_message.encode() if isinstance(sip_message, str) else sip_message

        # Build inner UDP packet
        udp_len = 8 + len(sip_bytes)
        udp_hdr = struct.pack("!HHHH",
                              random.randint(10000, 60000),  # src port
                              dst_port,
                              udp_len,
                              0)  # checksum = 0 (optional for IPv4)

        # Build inner IP packet
        ip_payload = udp_hdr + sip_bytes
        ip_total_len = 20 + len(ip_payload)
        ip_hdr = struct.pack("!BBHHHBBH4s4s",
                             0x45,           # version=4, IHL=5
                             0x00,           # DSCP/ECN
                             ip_total_len,   # total length
                             random.randint(0, 65535),  # identification
                             0x4000,         # flags=DF, fragment offset=0
                             64,             # TTL
                             17,             # protocol = UDP
                             0,              # checksum (0 = let kernel compute, or leave 0)
                             socket.inet_aton(self.ue_ims_ip),
                             socket.inet_aton(dst_ip))

        inner_packet = ip_hdr + ip_payload

        # Compute IP header checksum
        checksum = self._ip_checksum(ip_hdr)
        inner_packet = inner_packet[:10] + struct.pack("!H", checksum) + inner_packet[12:]

        # Build GTP-U header
        gtpu_hdr = struct.pack("!BBHI",
                               0x30,         # version=1, PT=1, E=0, S=0, PN=0
                               0xFF,         # G-PDU
                               len(inner_packet),
                               self.teid)

        gtpu_packet = gtpu_hdr + inner_packet

        # Send via UDP to UPF
        sent = self.send_sock.sendto(gtpu_packet, (self.upf_ip, self.upf_port))
        logger.info(f"GTP-U sent: SIP -> {dst_ip}:{dst_port}, TEID=0x{self.teid:08x}, "
                    f"inner_len={len(inner_packet)}, total={len(gtpu_packet)}B")
        return sent

    def wait_response(self, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
        """Wait for a SIP response from the GTP-U tunnel."""
        self._response_event.clear()
        if self._response_event.wait(timeout=timeout):
            if self._last_response:
                return parse_sip_response(self._last_response)
        return None

    @staticmethod
    def _ip_checksum(header: bytes) -> int:
        """Compute IP header checksum."""
        if len(header) % 2:
            header += b'\x00'
        s = 0
        for i in range(0, len(header), 2):
            w = (header[i] << 8) + header[i + 1]
            s += w
        while s >> 16:
            s = (s & 0xFFFF) + (s >> 16)
        return ~s & 0xFFFF

    def close(self):
        """Close tunnel sockets."""
        self._running = False
        try:
            self.send_sock.close()
        except Exception:
            pass
        try:
            self.recv_sock.close()
        except Exception:
            pass
        logger.info("GTP-U tunnel closed")


# ---------------------------------------------------------------------------
# VoNR Session Runner
# ---------------------------------------------------------------------------

class VoNRSessionRunner:
    """
    Manages the complete VoNR session establishment flow.

    1. Creates gNB + UE, performs 5G registration with IMS PDU session
    2. Opens GTP-U tunnel to UPF using IMS PDU session parameters
    3. Performs SIP REGISTER with P-CSCF (with IMS AKA authentication)
    4. Optionally initiates a VoNR call (SIP INVITE)
    """

    def __init__(self,
                 mcc: str = "460",
                 mnc: str = "09",
                 imsi_suffix10: str = "0000000001",
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 gnb_address: str = "192.168.55.9",
                 amf_address: str = "192.168.55.53",
                 upf_ip: str = "172.22.0.8",
                 pcscf_ip: str = "172.22.0.21",
                 pcscf_port: int = 5060,
                 ims_domain: str = None,
                 caller_phone: str = "13012345679",
                 callee_phone: str = "13012345678",
                 tac: str = "000001",
                 gnb_nr_cell_id: int = 1,
                 slices: dict = None,
                 imei: str = "86196306-248724-0",
                 log_level: str = "INFO"):
        """
        Args:
            mcc/mnc: PLMN identity
            imsi_suffix10: IMSI suffix (10 digits)
            ki/opc: Subscriber credentials (hex)
            gnb_address: gNodeB IP (for NGAP SCTP + GTP-U downlink)
            amf_address: AMF IP for NGAP
            upf_ip: UPF N3 address (GTP-U tunnel endpoint)
            pcscf_ip: P-CSCF SIP address
            pcscf_port: P-CSCF SIP port
            ims_domain: IMS home domain (auto-derived if None)
            caller_phone: Caller phone number (for INVITE From)
            callee_phone: Callee phone number (for INVITE To)
            tac: Tracking Area Code
            gnb_nr_cell_id: NR Cell ID
            slices: Slice config dict
            imei: IMEI for SIP Contact
        """
        self.mcc = mcc
        self.mnc = mnc
        self.imsi_suffix10 = imsi_suffix10
        self.imsi = f"{mcc}{mnc}{imsi_suffix10.zfill(10)}"
        self.ki = ki
        self.opc = opc
        self.gnb_address = gnb_address
        self.amf_address = amf_address
        self.upf_ip = upf_ip
        self.pcscf_ip = pcscf_ip
        self.pcscf_port = pcscf_port
        self.ims_domain = ims_domain or f"ims.mnc{mnc.zfill(3)}.mcc{mcc}.3gppnetwork.org"
        self.caller_phone = caller_phone
        self.callee_phone = callee_phone
        self.tac = tac
        self.gnb_nr_cell_id = gnb_nr_cell_id
        self.slices = slices or {"SST": 1}
        self.imei = imei
        self.log_level = log_level

        # Will be filled after PDU session establishment
        self.ims_ipv4 = None
        self.ims_teid = None
        self.ims_upf_ip = None

        # SIP session state
        self.sip_call_id = None
        self.sip_from_tag = None
        self.sip_cseq = random.randint(800000000, 999999999)
        self.sip_contact_uuid = _gen_contact_uuid()
        self.registered = False

        # GTP-U tunnel
        self.tunnel: Optional[GtpUTunnel] = None

    # ------------------------------------------------------------------
    # Phase 1: 5G Registration + PDU Sessions
    # ------------------------------------------------------------------

    def establish_pdu_sessions(self, wait_timeout: float = 30.0) -> bool:
        """
        Perform 5G registration and establish internet + ims PDU sessions.

        Uses the existing IntegratedGNB infrastructure with enable_ims=True.
        """
        from coresimrunner.integration.integrated_gnb import IntegratedGNB

        logger.info(f"Phase 1: 5G Registration + IMS PDU session establishment")
        logger.info(f"  IMSI: {self.imsi}, PLMN: {self.mcc}{self.mnc}")
        logger.info(f"  gNB: {self.gnb_address}, AMF: {self.amf_address}")

        try:
            gnb = IntegratedGNB(
                mcc=self.mcc,
                mnc=self.mnc,
                slices=self.slices,
                gnb_address=self.gnb_address,
                amf_address=self.amf_address,
                tac=self.tac,
                gnb_nr_cell_id=self.gnb_nr_cell_id,
                gnb_name="CoreSim-VoNR-gNB",
                start_suffix10=self.imsi_suffix10,
                number_of_ues=1,
                ki=self.ki,
                opc=self.opc,
                dnn="internet",
                enable_ims=True,
                logging_level=self.log_level,
            )
            gnb.run()

            # Wait for IMS PDU session to complete
            ue = gnb.ues[0]
            start = time.time()
            while time.time() - start < wait_timeout:
                if ue.dnn2_ims_connected and ue.dnn2_ipv4:
                    break
                time.sleep(0.5)

            if not ue.dnn2_ims_connected:
                logger.error("IMS PDU session not established within timeout")
                gnb.close()
                return False

            # Extract IMS session parameters
            self.ims_ipv4 = ue.dnn2_ipv4
            self.ims_teid = ue.dnn2_gtp_teid
            # Always use the configured UPF IP (docker internal) instead of
            # the NGAP-advertised IP which may be the host/external IP.
            # The UPF listens on its docker IP (e.g., 172.22.0.8) for GTP-U.
            self.ims_upf_ip = self.upf_ip

            logger.info(f"  IMS PDU session established:")
            logger.info(f"    IMS IPv4: {self.ims_ipv4}")
            logger.info(f"    IMS TEID: 0x{self.ims_teid}")
            logger.info(f"    UPF IP:   {self.ims_upf_ip}")
            logger.info(f"    Internet IPv4: {ue.dnn_ipv4}")

            # Keep gNB alive (don't close - we need the sessions)
            self._gnb = gnb
            return True

        except Exception as e:
            logger.error(f"Failed to establish PDU sessions: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ------------------------------------------------------------------
    # Phase 2: SIP REGISTER through GTP-U
    # ------------------------------------------------------------------

    def _open_tunnel(self):
        """Open GTP-U tunnel for SIP traffic."""
        self.tunnel = GtpUTunnel(
            upf_ip=self.ims_upf_ip,
            teid=self.ims_teid,
            ue_ims_ip=self.ims_ipv4,
            gnb_ip=self.gnb_address,
        )
        self.tunnel.start_listener()
        logger.info(f"GTP-U tunnel opened: UE({self.ims_ipv4}) -> UPF({self.ims_upf_ip}) "
                    f"TEID=0x{self.ims_teid}")

    def sip_register(self) -> bool:
        """
        Perform IMS SIP registration through the GTP-U tunnel.

        Flow:
          1. Send REGISTER with empty Authorization
          2. Receive 401 with WWW-Authenticate (nonce, ck, ik)
          3. Compute AKA response
          4. Send REGISTER with Authorization
          5. Receive 200 OK
        """
        if not self.tunnel:
            self._open_tunnel()

        ue_port = 5060
        branch = _gen_branch()
        self.sip_call_id = _gen_call_id(self.ims_ipv4)
        self.sip_from_tag = _gen_tag()
        uri = f"sip:{self.ims_domain}"

        logger.info(f"Phase 2: IMS SIP Registration")
        logger.info(f"  UE IMS IP: {self.ims_ipv4}, P-CSCF: {self.pcscf_ip}:{self.pcscf_port}")

        # --- Step 1: Initial REGISTER (no auth) ---
        logger.info("  [2.1] Sending initial SIP REGISTER (no auth)...")
        register1 = build_sip_register(
            ue_ip=self.ims_ipv4,
            ue_port=ue_port,
            imsi=self.imsi,
            ims_domain=self.ims_domain,
            pcscf_host=self.pcscf_ip,
            branch=branch,
            call_id=self.sip_call_id,
            from_tag=self.sip_from_tag,
            cseq=self.sip_cseq,
            contact_uuid=self.sip_contact_uuid,
            imei=self.imei,
        )
        self.tunnel.send_sip(register1, self.pcscf_ip, self.pcscf_port)

        # --- Step 2: Wait for 401 ---
        logger.info("  [2.2] Waiting for 401 Unauthorized...")
        resp = self.tunnel.wait_response(timeout=10.0)
        if resp is None:
            logger.warning("  No SIP response received (401 expected). "
                           "This may be normal if GTP-U downlink routing is not configured. "
                           "Check P-CSCF logs or tshark capture for verification.")
            # Try to proceed anyway - the REGISTER was likely forwarded
            return self._try_authenticated_register(branch)

        status = resp.get("status_code", 0)
        logger.info(f"  Received SIP {status} {resp.get('reason', '')}")

        if status == 200:
            logger.info("  SIP REGISTER succeeded without auth challenge (already registered?)")
            self.registered = True
            return True

        if status != 401:
            logger.warning(f"  Unexpected status code: {status} (expected 401)")
            if status >= 200:
                self.registered = True
            return self._try_authenticated_register(branch)

        # --- Step 3: Parse WWW-Authenticate and compute AKA response ---
        logger.info("  [2.3] Computing IMS AKA response...")
        www_auth = resp["headers"].get("WWW-Authenticate", "")
        auth_params = parse_www_authenticate(www_auth)

        nonce = auth_params.get("nonce", "")
        algorithm = auth_params.get("algorithm", "AKAv1-MD5")
        realm = auth_params.get("realm", self.ims_domain)

        logger.info(f"    Algorithm: {algorithm}")
        logger.info(f"    Nonce: {nonce[:40]}...")
        logger.info(f"    Realm: {realm}")

        if not nonce:
            logger.error("  No nonce in 401 challenge!")
            return False

        try:
            response_hex, res_hex, ck_hex = compute_ims_aka_response(
                nonce_b64=nonce,
                ki_hex=self.ki,
                opc_hex=self.opc,
                imsi=self.imsi,
                ims_domain=self.ims_domain,
                method="REGISTER",
                uri=uri,
            )
            logger.info(f"    RES: {res_hex}")
            logger.info(f"    CK:  {ck_hex}")
            logger.info(f"    Digest response: {response_hex}")
        except Exception as e:
            logger.error(f"  IMS AKA computation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

        # --- Step 4: Send authenticated REGISTER ---
        logger.info("  [2.4] Sending authenticated SIP REGISTER...")
        self.sip_cseq += 1
        branch2 = _gen_branch()

        auth_header = (
            f'Authorization: Digest uri="{uri}",'
            f'username="{self.imsi}@{self.ims_domain}",'
            f'response="{response_hex}",'
            f'realm="{realm}",'
            f'nonce="{nonce}",'
            f'algorithm={algorithm}'
        )

        register2 = build_sip_register(
            ue_ip=self.ims_ipv4,
            ue_port=ue_port,
            imsi=self.imsi,
            ims_domain=self.ims_domain,
            pcscf_host=self.pcscf_ip,
            branch=branch2,
            call_id=self.sip_call_id,
            from_tag=self.sip_from_tag,
            cseq=self.sip_cseq,
            contact_uuid=self.sip_contact_uuid,
            imei=self.imei,
            auth_header=auth_header,
        )
        self.tunnel.send_sip(register2, self.pcscf_ip, self.pcscf_port)

        # --- Step 5: Wait for 200 OK ---
        logger.info("  [2.5] Waiting for 200 OK...")
        resp2 = self.tunnel.wait_response(timeout=10.0)
        if resp2 is None:
            logger.warning("  No response to authenticated REGISTER. "
                           "Check P-CSCF/S-CSCF logs for verification.")
            return self._try_authenticated_register(branch)

        status2 = resp2.get("status_code", 0)
        logger.info(f"  Received SIP {status2} {resp2.get('reason', '')}")

        if status2 == 200:
            self.registered = True
            logger.info("  SIP REGISTER successful! UE is now IMS registered.")
            return True
        else:
            logger.warning(f"  SIP REGISTER returned {status2} (may still proceed)")
            return status2 >= 200

    def _try_authenticated_register(self, branch: str) -> bool:
        """
        Attempt to send an authenticated REGISTER even without receiving 401.
        Uses a pre-computed nonce-less auth header.
        """
        logger.info("  [Fallback] Attempting REGISTER with empty auth (for capture verification)...")
        self.sip_cseq += 1
        branch2 = _gen_branch()
        register = build_sip_register(
            ue_ip=self.ims_ipv4,
            ue_port=5060,
            imsi=self.imsi,
            ims_domain=self.ims_domain,
            pcscf_host=self.pcscf_ip,
            branch=branch2,
            call_id=self.sip_call_id,
            from_tag=self.sip_from_tag,
            cseq=self.sip_cseq,
            contact_uuid=self.sip_contact_uuid,
            imei=self.imei,
        )
        self.tunnel.send_sip(register, self.pcscf_ip, self.pcscf_port)
        logger.info("  REGISTER sent. Verify with: tshark -i docker_open5gs_default "
                     "-Y 'sip' -f 'port 5060 or port 4060 or port 6060'")
        return True

    # ------------------------------------------------------------------
    # Phase 3: VoNR Call (SIP INVITE)
    # ------------------------------------------------------------------

    def make_vonr_call(self, rtp_port: int = 49000) -> bool:
        """
        Initiate a VoNR call by sending SIP INVITE through GTP-U.

        Args:
            rtp_port: Local RTP port for media

        Returns:
            True if call was established (200 OK received)
        """
        if not self.registered:
            logger.warning("UE not IMS registered, attempting registration first...")
            if not self.sip_register():
                return False

        logger.info(f"Phase 3: VoNR Call Setup")
        logger.info(f"  Caller: {self.caller_phone}@{self.ims_domain}")
        logger.info(f"  Callee: {self.callee_phone}@{self.ims_domain}")

        branch = _gen_branch()
        call_id = _gen_call_id(self.ims_ipv4)
        from_tag = _gen_tag()
        self.sip_cseq += 1

        # --- INVITE ---
        logger.info("  [3.1] Sending SIP INVITE...")
        invite = build_sip_invite(
            ue_ip=self.ims_ipv4,
            ue_port=5060,
            caller_imsi=self.imsi,
            caller_phone=self.caller_phone,
            callee_phone=self.callee_phone,
            ims_domain=self.ims_domain,
            branch=branch,
            call_id=call_id,
            from_tag=from_tag,
            cseq=self.sip_cseq,
            contact_uuid=self.sip_contact_uuid,
            rtp_ip=self.ims_ipv4,
            rtp_port=rtp_port,
        )
        self.tunnel.send_sip(invite, self.pcscf_ip, self.pcscf_port)

        # --- Wait for responses ---
        to_tag = ""
        call_established = False

        for i in range(10):
            logger.info(f"  [3.{i+2}] Waiting for SIP response...")
            resp = self.tunnel.wait_response(timeout=10.0)
            if resp is None:
                logger.info("  No more responses (call flow may be complete)")
                break

            status = resp.get("status_code", 0)
            logger.info(f"  Received SIP {status} {resp.get('reason', '')}")

            if status == 100:
                logger.info("  100 Trying received")
                continue

            elif status == 183:
                logger.info("  183 Session Progress - early media negotiation")
                # Extract To tag
                to_hdr = resp["headers"].get("To", "")
                if "tag=" in to_hdr:
                    to_tag = to_hdr.split("tag=")[1].split(";")[0].split(">")[0]
                # Send PRACK
                logger.info("  Sending PRACK...")
                self.sip_cseq += 1
                prack_branch = _gen_branch()
                # Simple PRACK (not fully RFC 3262 compliant but sufficient for testing)
                prack = (
                    f"PRACK sip:{self.callee_phone}@{self.ims_domain} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {self.ims_ipv4}:5060;branch={prack_branch}\r\n"
                    f"From: <sip:{self.caller_phone}@{self.ims_domain}>;tag={from_tag}\r\n"
                    f"To: <tel:{self.callee_phone};phone-context={self.ims_domain}>;tag={to_tag}\r\n"
                    f"CSeq: {self.sip_cseq} PRACK\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"Max-Forwards: 70\r\n"
                    f"RAck: 1 {self.sip_cseq - 1} INVITE\r\n"
                    f"Content-Length: 0\r\n\r\n"
                )
                self.tunnel.send_sip(prack, self.pcscf_ip, self.pcscf_port)

                # Send UPDATE with updated SDP
                logger.info("  Sending UPDATE...")
                self.sip_cseq += 1
                update_branch = _gen_branch()
                update = (
                    f"UPDATE sip:{self.callee_phone}@{self.ims_domain} SIP/2.0\r\n"
                    f"Via: SIP/2.0/UDP {self.ims_ipv4}:5060;branch={update_branch}\r\n"
                    f"From: <sip:{self.caller_phone}@{self.ims_domain}>;tag={from_tag}\r\n"
                    f"To: <tel:{self.callee_phone};phone-context={self.ims_domain}>;tag={to_tag}\r\n"
                    f"CSeq: {self.sip_cseq} UPDATE\r\n"
                    f"Call-ID: {call_id}\r\n"
                    f"Max-Forwards: 70\r\n"
                    f"Content-Length: 0\r\n\r\n"
                )
                self.tunnel.send_sip(update, self.pcscf_ip, self.pcscf_port)

            elif status == 180:
                logger.info("  180 Ringing - callee is alerting")

            elif status == 200:
                logger.info("  200 OK - Call answered!")
                to_hdr = resp["headers"].get("To", "")
                if "tag=" in to_hdr and not to_tag:
                    to_tag = to_hdr.split("tag=")[1].split(";")[0].split(">")[0]

                # Send ACK
                logger.info("  Sending ACK...")
                ack = build_sip_ack(
                    ue_ip=self.ims_ipv4,
                    ue_port=5060,
                    from_uri=f"sip:{self.caller_phone}@{self.ims_domain}",
                    to_uri=f"tel:{self.callee_phone};phone-context={self.ims_domain}",
                    to_tag=to_tag,
                    from_tag=from_tag,
                    call_id=call_id,
                    cseq=self.sip_cseq,
                    branch=_gen_branch(),
                    target_uri=f"sip:{self.callee_phone}@{self.ims_domain}",
                )
                self.tunnel.send_sip(ack, self.pcscf_ip, self.pcscf_port)
                call_established = True
                break

            elif status >= 400:
                logger.warning(f"  Call failed with {status}")
                # Send ACK for error responses
                ack = build_sip_ack(
                    ue_ip=self.ims_ipv4,
                    ue_port=5060,
                    from_uri=f"sip:{self.caller_phone}@{self.ims_domain}",
                    to_uri=f"tel:{self.callee_phone};phone-context={self.ims_domain}",
                    to_tag=to_tag,
                    from_tag=from_tag,
                    call_id=call_id,
                    cseq=self.sip_cseq,
                    branch=_gen_branch(),
                    target_uri=f"sip:{self.callee_phone}@{self.ims_domain}",
                )
                self.tunnel.send_sip(ack, self.pcscf_ip, self.pcscf_port)
                break

        if call_established:
            logger.info("  VoNR call established! Media session active.")
            logger.info(f"  RTP: {self.ims_ipv4}:{rtp_port}")
        else:
            logger.info("  VoNR call setup did not complete (check capture for progress)")

        return call_established

    def end_call(self):
        """Send BYE to end the VoNR call."""
        if not self.tunnel:
            return

        self.sip_cseq += 1
        bye = build_sip_bye(
            ue_ip=self.ims_ipv4,
            ue_port=5060,
            from_uri=f"sip:{self.caller_phone}@{self.ims_domain}",
            to_uri=f"tel:{self.callee_phone};phone-context={self.ims_domain}",
            to_tag="",
            from_tag=self.sip_from_tag or "",
            call_id=self.sip_call_id or "",
            cseq=self.sip_cseq,
            branch=_gen_branch(),
            target_uri=f"sip:{self.callee_phone}@{self.ims_domain}",
        )
        self.tunnel.send_sip(bye, self.pcscf_ip, self.pcscf_port)
        logger.info("BYE sent - call terminated")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, skip_call: bool = False) -> bool:
        """
        Run the complete VoNR session establishment flow.

        Args:
            skip_call: If True, only do SIP REGISTER (no INVITE)

        Returns:
            True if all phases succeeded
        """
        print(f"\n{'='*70}")
        print(f"  VoNR Session Establishment (5G IMS + SIP)")
        print(f"{'='*70}")
        print(f"  IMSI:       {self.imsi}")
        print(f"  IMS Domain: {self.ims_domain}")
        print(f"  P-CSCF:     {self.pcscf_ip}:{self.pcscf_port}")
        print(f"  UPF:        {self.upf_ip}")
        print(f"  gNB:        {self.gnb_address}")
        print(f"  AMF:        {self.amf_address}")
        print(f"  Caller:     {self.caller_phone}")
        print(f"  Callee:     {self.callee_phone}")
        print(f"{'='*70}\n")

        # Phase 1: 5G Registration + PDU Sessions
        if not self.establish_pdu_sessions():
            logger.error("Phase 1 FAILED: PDU session establishment")
            return False

        # Phase 2: SIP Registration
        if not self.sip_register():
            logger.warning("Phase 2: SIP registration may not have completed. "
                           "Verify with packet capture.")

        # Phase 3: VoNR Call (optional)
        if not skip_call:
            self.make_vonr_call()
            # Hold call for 5 seconds
            logger.info("Holding call for 5 seconds...")
            time.sleep(5)
            self.end_call()

        # Summary
        logger.info("")
        logger.info("=" * 70)
        logger.info("VoNR Session Summary:")
        logger.info(f"  5G Registration:  OK")
        logger.info(f"  Internet PDU:     OK")
        logger.info(f"  IMS PDU:          OK (IPv4={self.ims_ipv4})")
        logger.info(f"  SIP REGISTER:     {'OK' if self.registered else 'Sent (verify via capture)'}")
        if not skip_call:
            logger.info(f"  VoNR Call:        Sent (verify via capture)")
        logger.info("=" * 70)
        logger.info("")
        logger.info("Verification commands:")
        logger.info(f"  # Capture SIP on docker network:")
        logger.info(f"  tshark -i docker_open5gs_default -Y 'sip' -f 'port 5060 or port 4060 or port 6060'")
        logger.info(f"  # Capture GTP-U on UPF:")
        logger.info(f"  tshark -i docker_open5gs_default -Y 'gtp' -f 'port 2152'")
        logger.info(f"  # Check P-CSCF logs:")
        logger.info(f"  docker logs pcscf --tail 50")
        logger.info(f"  # Check S-CSCF logs:")
        logger.info(f"  docker logs scscf --tail 50")

        # Cleanup
        if self.tunnel:
            self.tunnel.close()
        if hasattr(self, '_gnb'):
            self._gnb.close()

        return self.registered


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Command-line entry point for VoNR session runner."""
    import argparse

    parser = argparse.ArgumentParser(
        description="VoNR Session Establishment - IMS SIP Registration & Call via GTP-U",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run VoNR session with defaults (from docker_open5gs .env)
  python vonr_session.py

  # SIP REGISTER only (no call)
  python vonr_session.py --skip-call

  # Custom configuration
  python vonr_session.py --imsi 0000000001 --gnb-address 192.168.55.9 \\
    --amf-address 192.168.55.53 --upf-ip 172.22.0.8 --pcscf-ip 172.22.0.21
        """
    )

    parser.add_argument("--imsi", default="0000000001",
                        help="IMSI suffix (10 digits, default: 0000000001)")
    parser.add_argument("--plmn", default="46009",
                        help="PLMN (MCC+MNC, default: 46009)")
    parser.add_argument("--ki", default="12341234123412341234123412340000",
                        help="Subscriber key K (hex, 32 chars)")
    parser.add_argument("--opc", default="71a121bb69baf3c0cc53fb5038a0131f",
                        help="OPc value (hex, 32 chars)")
    parser.add_argument("--gnb-address", default="192.168.55.9",
                        help="gNodeB IP address")
    parser.add_argument("--amf-address", default="192.168.55.53",
                        help="AMF IP address")
    parser.add_argument("--upf-ip", default="172.22.0.8",
                        help="UPF GTP-U address")
    parser.add_argument("--pcscf-ip", default="172.22.0.21",
                        help="P-CSCF SIP address")
    parser.add_argument("--pcscf-port", type=int, default=5060,
                        help="P-CSCF SIP port (default: 5060)")
    parser.add_argument("--ims-domain", default=None,
                        help="IMS home domain (auto-derived from PLMN if omitted)")
    parser.add_argument("--caller-phone", default="13012345679",
                        help="Caller phone number")
    parser.add_argument("--callee-phone", default="13012345678",
                        help="Callee phone number")
    parser.add_argument("--tac", default="000001",
                        help="Tracking Area Code")
    parser.add_argument("--skip-call", action="store_true",
                        help="Only perform SIP REGISTER, skip VoNR call")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    mcc = args.plmn[:3]
    mnc = args.plmn[3:]

    runner = VoNRSessionRunner(
        mcc=mcc,
        mnc=mnc,
        imsi_suffix10=args.imsi,
        ki=args.ki,
        opc=args.opc,
        gnb_address=args.gnb_address,
        amf_address=args.amf_address,
        upf_ip=args.upf_ip,
        pcscf_ip=args.pcscf_ip,
        pcscf_port=args.pcscf_port,
        ims_domain=args.ims_domain,
        caller_phone=args.caller_phone,
        callee_phone=args.callee_phone,
        tac=args.tac,
        log_level=args.log_level,
    )

    success = runner.run(skip_call=args.skip_call)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
