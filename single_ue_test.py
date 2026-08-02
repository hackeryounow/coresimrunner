#!/usr/bin/env python3
"""
single_ue_test.py - 5G SA Single UE Registration + PDU Session (Standalone)

Complete flow in one file:
  1. Parameter setup
  2. SCTP connection to AMF + NG Setup
  3. UE Registration (InitialUE → Auth → SMC → RegAccept → RegComplete)
  4. PDU Session Establishment (UL NAS Transport → PDU ResourceSetup → Response)

NAS messages are built via pycrate (with raw hex logged for visibility).
NGAP encoding uses pycrate (APER).  Crypto uses CryptoMobile (Milenage + key derivation).

Usage:
  python3 single_ue_test.py --gnb-address 192.168.100.10 --core-address 192.168.55.53
"""

import sys, os, time, struct, socket, argparse, ipaddress

# ── Library paths ───────────────────────────────────────────────────────────
WORKSPACE = '/root'
for p in [os.path.join(WORKSPACE, 'pycrate'), os.path.join(WORKSPACE, 'CryptoMobile')]:
    if p not in sys.path:
        sys.path.insert(0, p)

import sctp
from loguru import logger

# pycrate NGAP + NAS
from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
from pycrate_mobile.TS24501_FGMM import (
    FGMMRegistrationRequest, FGMMSecProtNASMessage,
    FGMMSecurityModeComplete, FGMMSecurityModeCommand,
    FGMMRegistrationAccept, FGMMRegistrationComplete,
    FGMMULNASTransport, FGMMDLNASTransport,
)
from pycrate_mobile.TS24501_FGSM import FGSMPDUSessionEstabRequest, FGSMPDUSessionEstabAccept
from pycrate_mobile.TS24501_IE import FGSIDTYPE_IMEISV

# CryptoMobile
try:
    from CryptoMobile.conv import conv_501_A2, conv_501_A4, conv_501_A6, conv_501_A7, conv_501_A8
    from CryptoMobile.Milenage import Milenage
except ImportError:
    from CryptoMobile import conv, Milenage
    conv_501_A2, conv_501_A4 = conv.conv_501_A2, conv.conv_501_A4
    conv_501_A6, conv_501_A7, conv_501_A8 = conv.conv_501_A6, conv.conv_501_A7, conv.conv_501_A8
    Milenage = Milenage.Milenage

NGAP_PPID = 60
PDU = NGAP_PDU_Descriptions.NGAP_PDU


# ════════════════════════════════════════════════════════════════════════════
#  Utilities
# ════════════════════════════════════════════════════════════════════════════

def bcd(chars: str) -> bytes:
    """BCD encode digit string: '46099' → 0x64f099."""
    s = ""
    for i in range(len(chars) // 2):
        s += chars[1 + 2 * i] + chars[2 * i]
    return bytes.fromhex(s)

def plmn_encode(mccmnc: str) -> bytes:
    """PLMN BCD encode: '46099' → 3 bytes."""
    if len(mccmnc) == 5:
        return bcd(mccmnc[0] + mccmnc[1] + mccmnc[2] + 'f' + mccmnc[3] + mccmnc[4])
    return bcd(mccmnc)

def plmn_decode(b: bytes) -> str:
    """PLMN BCD decode."""
    s = ""
    for byte in b:
        s += str(byte & 0xF)
        if (byte >> 4) & 0xF != 0xF:
            s += str((byte >> 4) & 0xF)
    return s

def byte_xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))

def nas_type(nas: bytes) -> int:
    """Extract NAS message type byte, handling plain / security-protected headers."""
    if len(nas) < 3:
        return 0
    sec = nas[1]
    if sec == 0:              # plain: EPD(1) + SecHdr(1) + Type(1)
        return nas[2]
    if sec in (0x02, 0x03, 0x04):  # sec-protected: +MAC(4)+SeqNo(1) then inner
        if len(nas) > 8:
            inner = nas[7]    # inner EPD
            if inner == 0x7e: # inner SecHdr at [8], inner Type at [9]
                if len(nas) > 9:
                    return nas[9]
            return nas[7]     # fallback: byte after MAC+SeqNo
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  NAS Message Builders (pycrate-based, with hex logging)
# ════════════════════════════════════════════════════════════════════════════

def build_reg_request_minimal(msin: str, plmn: str) -> bytes:
    """Minimal Registration Request — mandatory IEs only (cleartext, initial)."""
    ies = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 65},
        'NAS_KSI': {'TSC': 0, 'Value': 7},
        '5GSRegType': {'FOR': 0, 'Value': 1},
        '5GSID': {'spare': 0, 'Fmt': 0, 'spare': 0, 'Type': 1,
                  'Value': {'PLMN': plmn, 'RoutingInd': b'\x00\x00',
                            'spare': 0, 'ProtSchemeID': 0, 'HNPKID': 0,
                            'Output': bcd(msin)}},
        'UESecCap': {
            '5G-EA0': 1, '5G-EA1_128': 1, '5G-EA2_128': 1, '5G-EA3_128': 1,
            '5G-EA4': 0, '5G-EA5': 0, '5G-EA6': 0, '5G-EA7': 0,
            '5G-IA0': 1, '5G-IA1_128': 1, '5G-IA2_128': 1, '5G-IA3_128': 1,
            '5G-IA4': 0, '5G-IA5': 0, '5G-IA6': 0, '5G-IA7': 0,
            'EEA0': 1, 'EEA1_128': 1, 'EEA2_128': 1, 'EEA3_128': 1,
            'EEA4': 0, 'EEA5': 0, 'EEA6': 0, 'EEA7': 0,
            'EIA0': 1, 'EIA1_128': 1, 'EIA2_128': 1, 'EIA3_128': 1,
            'EIA4': 0, 'EIA5': 0, 'EIA6': 0, 'EIA7': 0,
        },
    }
    return FGMMRegistrationRequest(val=ies).to_bytes()


def build_reg_request_full(msin: str, plmn: str, sst: int = 1) -> bytes:
    """Full Registration Request with NSSAI, 5GMM Capability, Update Type.
    Used inside Security Mode Complete NAS Container."""
    ies = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 65},
        'NAS_KSI': {'TSC': 0, 'Value': 7},
        '5GSRegType': {'FOR': 0, 'Value': 1},
        '5GSID': {'spare': 0, 'Fmt': 0, 'spare': 0, 'Type': 1,
                  'Value': {'PLMN': plmn, 'RoutingInd': b'\x00\x00',
                            'spare': 0, 'ProtSchemeID': 0, 'HNPKID': 0,
                            'Output': bcd(msin)}},
        'UESecCap': {
            '5G-EA0': 1, '5G-EA1_128': 1, '5G-EA2_128': 1, '5G-EA3_128': 1,
            '5G-EA4': 0, '5G-EA5': 0, '5G-EA6': 0, '5G-EA7': 0,
            '5G-IA0': 1, '5G-IA1_128': 1, '5G-IA2_128': 1, '5G-IA3_128': 1,
            '5G-IA4': 0, '5G-IA5': 0, '5G-IA6': 0, '5G-IA7': 0,
            'EEA0': 1, 'EEA1_128': 1, 'EEA2_128': 1, 'EEA3_128': 1,
            'EEA4': 0, 'EEA5': 0, 'EEA6': 0, 'EEA7': 0,
            'EIA0': 1, 'EIA1_128': 1, 'EIA2_128': 1, 'EIA3_128': 1,
            'EIA4': 0, 'EIA5': 0, 'EIA6': 0, 'EIA7': 0,
        },
        '5GSUpdateType': {'EPS-PNB-CIoT': 0, '5GS-PNB-CIoT': 0, 'NG-RAN-RCU': 0, 'SMSRequested': 0},
        '5GMMCap': {'SGC': 0, '5G-HC-CP-CIoT': 0, 'N3Data': 0, '5G-CP-CIoT': 0,
                    'RestrictEC': 0, 'LPP': 0, 'HOAttach': 0, 'S1Mode': 0},
        'NSSAI': [{'SNSSAI': {'SST': sst}}],
    }
    msg = FGMMRegistrationRequest(val=ies)
    msg['5GMMCap']['5GMMCap'].disable_from(8)
    return msg.to_bytes()


def build_auth_response(res_star_hex: str) -> bytes:
    """Authentication Response (type=0x57)."""
    return bytes.fromhex(f'7e00572d10{res_star_hex}')


def build_sec_mode_complete(full_reg_req: bytes, imeisv: str = "4370816125816151") -> bytes:
    """Security Mode Complete (type=0x5d) with IMEISV + NAS Container."""
    ies = {'5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0}}
    ies['IMEISV'] = {'Type': FGSIDTYPE_IMEISV, 'Digit1': int(imeisv[0]), 'Digits': imeisv[1:]}
    ies['NASContainer'] = {}
    msg = FGMMSecurityModeComplete(val=ies)
    msg['NASContainer']['V'].set_val(full_reg_req)
    return msg.to_bytes()


def build_reg_complete() -> bytes:
    """Registration Complete (type=0x43)."""
    return FGMMRegistrationComplete().to_bytes()


def build_pdu_session_estab_request(pdu_sess_id: int = 1) -> bytes:
    """PDU Session Establishment Request (5GSM, type=0xc1)."""
    ies = {
        '5GSMHeader': {'PDUSessID': pdu_sess_id, 'Type': 193, 'PTI': 1},
        'PDUSessType': {'Value': 1},       # IPv4
        'SSCMode': {'Value': 1},
        '5GSMCap': {'TPMIC': 0, 'ATSSS-ST': 0, 'EPT-S1': 0, 'MH6-PDU': 0, 'RQoS': 0},
        'ExtProtConfig': {'Ext': 1, 'spare': 0, 'Prot': 0},
    }
    return FGSMPDUSessionEstabRequest(val=ies).to_bytes()


def build_ul_nas_transport(inner_nas: bytes, dnn: str = "internet",
                           sst: int = 1, pdu_sess_id: int = 1) -> bytes:
    """UL NAS Transport (type=0x67) wrapping PDU Session Establishment Request."""
    ies = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 103},
        'PDUSessID': pdu_sess_id,
        'RequestType': 1,
        'SNSSAI': {'SST': sst},
    }
    msg = FGMMULNASTransport(val=ies)
    msg['PayloadContainer']['V'].set_val(inner_nas)
    # Manually append DNN (pycrate bug workaround)
    dnn_b = dnn.encode() if isinstance(dnn, str) else dnn
    dnn_ie = bytes([0x25, len(dnn_b) + 1, len(dnn_b)]) + dnn_b
    return msg.to_bytes() + dnn_ie


# ════════════════════════════════════════════════════════════════════════════
#  NAS Security
# ════════════════════════════════════════════════════════════════════════════

def compute_milenage(ki: bytes, opc: bytes, rand: bytes,
                     sqn_xor_ak: bytes, mcc: str, mnc: str,
                     amf_field: bytes = b"\x80\x00"):
    """Milenage + 5G-AKA → (KSEAF, res_star_hex)."""
    snn = f"5G:mnc{mnc.zfill(3)}.mcc{mcc.zfill(3)}.3gppnetwork.org".encode()
    mil = Milenage(opc); mil.set_opc(opc)
    RES, CK, IK, AK = mil.f2345(ki, rand)
    mil.f1(ki, rand, SQN=byte_xor(AK, sqn_xor_ak), AMF=amf_field)
    res_star = conv_501_A4(CK, IK, snn, rand, RES)
    kausf = conv_501_A2(CK, IK, snn, sqn_xor_ak)
    return conv_501_A6(kausf, snn), res_star.hex()


def derive_nas_keys(kseaf: bytes, supi: str, ciph_algo: int, integ_algo: int,
                    abba: bytes = b"\x00\x00"):
    """KSEAF → (K_NAS_enc, K_NAS_int)."""
    k_amf = conv_501_A7(kseaf, supi.encode(), abba)
    return conv_501_A8(k_amf, alg_type=1, alg_id=ciph_algo)[16:], \
           conv_501_A8(k_amf, alg_type=2, alg_id=integ_algo)[16:]


def security_protect(inner_nas: bytes, k_int: bytes, k_enc: bytes,
                     ciph: int, integ: int, seq: int = 0, is_smc: bool = False) -> bytes:
    """Wrap inner NAS with 5GMM security header (MAC + encryption)."""
    hdr_val = 0x04 if is_smc else 0x02
    sec = FGMMSecProtNASMessage(val={'5GMMHeaderSec': {'EPD': 126, 'spare': 0, 'SecHdr': hdr_val}})
    sec['NASMessage'].set_val(inner_nas)
    if ciph != 0:
        sec.encrypt(key=k_enc, dir=0, fgea=ciph, seqnoff=seq, bearer=1)
    sec.mac_compute(key=k_int, dir=0, fgia=integ, seqnoff=seq, bearer=1)
    return sec.to_bytes()


# ════════════════════════════════════════════════════════════════════════════
#  NGAP Message Builders (dict → APER via pycrate)
# ════════════════════════════════════════════════════════════════════════════

def ngap_ng_setup(plmn: str, name: str, gnb_id: int, tac: str, sst: int, sd=None):
    plmn_b = plmn_encode(plmn)
    ies = [
        {'id': 27, 'criticality': 'reject', 'value': (
            'GlobalRANNodeID', ('globalGNB-ID', {
                'pLMNIdentity': plmn_b, 'gNB-ID': ('gNB-ID', (gnb_id, 32))
            }))},
        {'id': 82, 'criticality': 'ignore', 'value': ('RANNodeName', name)},
        {'id': 102, 'criticality': 'reject', 'value': ('SupportedTAList', [{
            'tAC': bytes.fromhex(tac),
            'broadcastPLMNList': [{'pLMNIdentity': plmn_b,
                'tAISliceSupportList': [{'s-NSSAI': {
                    'sST': bytes([sst]),
                    **({'sD': bytes.fromhex(hex(sd)[2:].zfill(6))} if sd else {})
                }}]}]}])},
        {'id': 21, 'criticality': 'ignore', 'value': ('PagingDRX', 'v128')},
    ]
    return ('initiatingMessage', {'procedureCode': 21, 'criticality': 'reject',
                                  'value': ('NGSetupRequest', {'protocolIEs': ies})})

def ngap_initial_ue(nas: bytes, plmn_b: bytes, tac: str, ran_id=1, cell_id=1):
    ies = [
        {'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_id)},
        {'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', nas)},
        {'id': 121, 'criticality': 'reject', 'value': ('UserLocationInformation',
            ('userLocationInformationNR', {
                'nR-CGI': {'pLMNIdentity': plmn_b, 'nRCellIdentity': (cell_id, 36)},
                'tAI': {'pLMNIdentity': plmn_b, 'tAC': bytes.fromhex(tac)},
                'timeStamp': (int(time.time()) + 2208988800).to_bytes(4, 'big')
            }))},
        {'id': 90, 'criticality': 'ignore', 'value': ('RRCEstablishmentCause', 'mo-Signalling')},
        {'id': 112, 'criticality': 'ignore', 'value': ('UEContextRequest', 'requested')},
    ]
    return ('initiatingMessage', {'procedureCode': 15, 'criticality': 'ignore',
                                  'value': ('InitialUEMessage', {'protocolIEs': ies})})

def ngap_ul_transport(nas: bytes, amf_id: int, ran_id: int, plmn_b: bytes, tac: str, cell_id=1):
    ies = [
        {'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_id)},
        {'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_id)},
        {'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', nas)},
        {'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation',
            ('userLocationInformationNR', {
                'tAI': {'pLMNIdentity': plmn_b, 'tAC': bytes.fromhex(tac)},
                'nR-CGI': {'pLMNIdentity': plmn_b, 'nRCellIdentity': (cell_id, 36)}
            }))},
    ]
    return ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore',
                                  'value': ('UplinkNASTransport', {'protocolIEs': ies})})

def ngap_ctx_setup_resp(amf_id: int, ran_id=1):
    return ('successfulOutcome', {'procedureCode': 14, 'criticality': 'ignore',
        'value': ('InitialContextSetupResponse', {'protocolIEs': [
            {'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_id)},
            {'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_id)},
        ]})})

def ngap_pdu_setup_resp(amf_id: int, qos_id: int, gnb_ip: str, ran_id=1, sess_id=1):
    ip_hex = ipaddress.ip_address(gnb_ip).packed.hex()
    return ('successfulOutcome', {'procedureCode': 29, 'criticality': 'reject',
        'value': ('PDUSessionResourceSetupResponse', {'protocolIEs': [
            {'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_id)},
            {'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', ran_id)},
            {'id': 75, 'criticality': 'ignore', 'value': ('PDUSessionResourceSetupListSURes', [{
                'pDUSessionID': sess_id,
                'pDUSessionResourceSetupResponseTransfer':
                    bytes.fromhex(f'0003e0{ip_hex}00000002{qos_id:04x}')
            }])},
        ]})})

def ngap_ue_release_complete(amf_id: int, ran_id: int, plmn_b: bytes, tac: str, cell_id=1):
    return ('successfulOutcome', {'procedureCode': 41, 'criticality': 'reject',
        'value': ('UEContextReleaseComplete', {'protocolIEs': [
            {'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_id)},
            {'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', ran_id)},
            {'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation',
                ('userLocationInformationNR', {
                    'tAI': {'pLMNIdentity': plmn_b, 'tAC': bytes.fromhex(tac)},
                    'nR-CGI': {'pLMNIdentity': plmn_b, 'nRCellIdentity': (cell_id, 36)}
                }))},
        ]})})


# ════════════════════════════════════════════════════════════════════════════
#  SCTP / NGAP Transport
# ════════════════════════════════════════════════════════════════════════════

def ngap_send(sock, message):
    PDU.set_val(message)
    sock.sctp_send(PDU.to_aper(), ppid=socket.htonl(NGAP_PPID))

def ngap_recv(sock, timeout=15):
    sock.settimeout(timeout)
    data = sock.recv(8192)
    if not data:
        return None, None
    p = NGAP_PDU_Descriptions.NGAP_PDU
    p.from_aper(data)
    return p()

def find_ie(ies, name):
    for ie in ies:
        if isinstance(ie['value'], (list, tuple)) and ie['value'][0] == name:
            return ie['value'][1]
    return None

def find_nas(ies):
    return find_ie(ies, 'NAS-PDU')


# ════════════════════════════════════════════════════════════════════════════
#  Main Flow
# ════════════════════════════════════════════════════════════════════════════

def run_test(gnb_addr, amf_addr, imsi, plmn="46099",
             ki_hex="12341234123412341234123412340000",
             opc_hex="71a121bb69baf3c0cc53fb5038a0131f",
             dnn="internet", tac="000001", sst=1,
             amf_port=38412, gnb_id=513, imeisv="4370816125816151"):

    mcc, mnc = plmn[:3], plmn[3:]
    msin = imsi[-10:]
    supi = f"{plmn}{msin}"
    plmn_b = plmn_encode(plmn)
    ki = bytes.fromhex(ki_hex)
    opc = bytes.fromhex(opc_hex)
    ran_id = 1

    logger.info(f"{'='*60}")
    logger.info(f"5G SA Single UE Test")
    logger.info(f"  gNB: {gnb_addr}  →  AMF: {amf_addr}:{amf_port}")
    logger.info(f"  PLMN={plmn}  IMSI={imsi}  SUPI={supi}")
    logger.info(f"  DNN={dnn}  SST={sst}  TAC={tac}")
    logger.info(f"{'='*60}")

    # ── Step 1: SCTP + NG Setup ─────────────────────────────────────────
    logger.info(f"\n[Step 1] SCTP connection + NG Setup")
    sock = sctp.sctpsocket_tcp(socket.AF_INET)
    sock.bind((gnb_addr, 0))
    sock.connect((amf_addr, amf_port))
    ngap_send(sock, ngap_ng_setup(plmn, "CoreSim-UE1", gnb_id, tac, sst))
    t, r = ngap_recv(sock)
    if t is None:
        raise RuntimeError("No NG Setup Response")
    if r['value'][0] == 'unsuccessfulOutcome':
        raise RuntimeError(f"NG Setup Failed: {r}")
    logger.info(f"  ✓ NG Setup OK — AMF: {find_ie(r['value'][1]['protocolIEs'], 'AMFName')}")

    # ── Step 2: Initial UE (Registration Request) ───────────────────────
    logger.info(f"\n[Step 2] Initial UE Message (Registration Request)")
    reg_min = build_reg_request_minimal(msin, plmn)
    logger.info(f"  NAS ({len(reg_min)}B): {reg_min.hex()}")
    ngap_send(sock, ngap_initial_ue(reg_min, plmn_b, tac, ran_id))

    # ── Step 3: Authentication ──────────────────────────────────────────
    logger.info(f"\n[Step 3] Authentication")
    t, r = ngap_recv(sock)
    ies = r['value'][1]['protocolIEs']
    nas = find_nas(ies)

    # Skip Configuration Update Commands
    while nas is not None and nas_type(nas) == 0x54:
        logger.info(f"  (Config Update Command — skipping)")
        t, r = ngap_recv(sock)
        ies = r['value'][1]['protocolIEs']
        nas = find_nas(ies)

    if nas is None or nas_type(nas) != 0x56:
        raise RuntimeError(f"Expected Auth Request (0x56), got 0x{nas_type(nas):02x}")

    # Parse Auth Request using hardcoded offsets (proven with Open5GS)
    # Format: EPD(2) + SecHdr(1) + Type(1) + ngKSI/spare(1) + ABBA_IEI(1) + ABBA_L(1) + ABBA_val + RAND_IEI(1) + RAND_L(1) + RAND(16) + AUTN_IEI(1) + AUTN_L(1) + AUTN(16)
    # Use same offsets as existing integrated_messages.py
    rand_val = nas[8:24]
    autn_val = nas[24:]
    sqn_xor_ak = autn_val[2:8]
    amf_field = autn_val[8:10]
    # Extract ABBA from Auth Request
    abba_len = nas[5]  # ABBA length at byte 5
    abba = nas[6:6 + abba_len] if abba_len > 0 else b"\x00\x00"

    amf_ue_id = find_ie(ies, 'AMF-UE-NGAP-ID')
    if hasattr(amf_ue_id, 'get_val'): amf_ue_id = amf_ue_id.get_val()
    amf_ue_id = int(amf_ue_id)

    kseaf, res_star = compute_milenage(ki, opc, rand_val, sqn_xor_ak, mcc, mnc, amf_field)
    logger.info(f"  RAND={rand_val.hex()}")
    logger.info(f"  AUTN={autn_val.hex()}")
    logger.info(f"  RES*={res_star}, KSEAF={kseaf.hex()[:32]}...")
    logger.info(f"  AMF UE ID={amf_ue_id}")

    auth_nas = build_auth_response(res_star)
    ngap_send(sock, ngap_ul_transport(auth_nas, amf_ue_id, ran_id, plmn_b, tac))
    logger.info(f"  ✓ Auth Response sent")

    # ── Step 4: Security Mode ───────────────────────────────────────────
    logger.info(f"\n[Step 4] Security Mode")
    t, r = ngap_recv(sock)
    ies = r['value'][1]['protocolIEs']
    nas = find_nas(ies)
    # Skip any non-SMC messages (Config Update, etc.)
    while nas is not None and nas_type(nas) != 0x5d:
        logger.info(f"  (Got NAS type=0x{nas_type(nas):02x}, skipping — waiting for SMC)")
        t, r = ngap_recv(sock)
        ies = r['value'][1]['protocolIEs']
        nas = find_nas(ies)
    if nas is None:
        raise RuntimeError("No SMC received")

    smc = FGMMSecurityModeCommand()
    smc.from_bytes(nas[7:])  # skip EPD(2)+SecHdr(1)+MAC(4)
    ciph = smc['NASSecAlgo']['NASSecAlgo']['CiphAlgo'].get_val()
    integ = smc['NASSecAlgo']['NASSecAlgo']['IntegAlgo'].get_val()
    k_enc, k_int = derive_nas_keys(kseaf, supi, ciph, integ, abba)
    logger.info(f"  Ciph={ciph}, Integ={integ}, K_enc={k_enc.hex()}, K_int={k_int.hex()}")

    smc_inner = build_sec_mode_complete(build_reg_request_full(msin, plmn, sst), imeisv)
    smc_prot = security_protect(smc_inner, k_int, k_enc, ciph, integ, is_smc=True)
    ngap_send(sock, ngap_ul_transport(smc_prot, amf_ue_id, ran_id, plmn_b, tac))
    logger.info(f"  ✓ Security Mode Complete sent ({len(smc_prot)}B)")

    # ── Step 5: Registration Accept ─────────────────────────────────────
    logger.info(f"\n[Step 5] Registration Accept")
    t, r = ngap_recv(sock)
    proc = r.get('procedureCode', -1)
    ies = r['value'][1]['protocolIEs']

    while proc == 4:
        nas = find_nas(ies)
        if nas and nas_type(nas) == 0x54:
            logger.info(f"  (Config Update — skipping)")
            t, r = ngap_recv(sock); proc = r.get('procedureCode', -1)
            ies = r['value'][1]['protocolIEs']
        else:
            break

    if proc != 14:
        raise RuntimeError(f"Expected InitialContextSetup (proc 14), got proc={proc}")

    nas = find_nas(ies)
    reg_accept = FGMMRegistrationAccept()
    reg_accept.from_bytes(nas[7:])
    logger.info(f"  ✓ Registration Accept received")

    ngap_send(sock, ngap_ctx_setup_resp(amf_ue_id, ran_id))
    rc_prot = security_protect(build_reg_complete(), k_int, k_enc, ciph, integ)
    ngap_send(sock, ngap_ul_transport(rc_prot, amf_ue_id, ran_id, plmn_b, tac))
    logger.info(f"  ✓ Registration Complete sent")

    # ── Step 6: PDU Session Establishment ───────────────────────────────
    logger.info(f"\n[Step 6] PDU Session Establishment Request")
    pdu_req = build_pdu_session_estab_request(1)
    ul_nas = build_ul_nas_transport(pdu_req, dnn=dnn, sst=sst, pdu_sess_id=1)
    ul_prot = security_protect(ul_nas, k_int, k_enc, ciph, integ)
    ngap_send(sock, ngap_ul_transport(ul_prot, amf_ue_id, ran_id, plmn_b, tac))
    logger.info(f"  PDU Session Estab Request sent ({len(ul_prot)}B)")

    # ── Step 7: PDU Session Resource Setup ──────────────────────────────
    logger.info(f"\n[Step 7] PDU Session Resource Setup")
    t, r = ngap_recv(sock, timeout=30)
    proc = r.get('procedureCode', -1)
    # Skip DownlinkNASTransport (proc 4) — Config Update, etc.
    while proc == 4:
        dl_nas = find_nas(r['value'][1]['protocolIEs'])
        dl_type = nas_type(dl_nas) if dl_nas else 0
        logger.info(f"  (DL NAS Transport: type=0x{dl_type:02x}, {len(dl_nas) if dl_nas else 0}B)")
        t, r = ngap_recv(sock, timeout=30)
        if t is None:
            raise RuntimeError("Timeout waiting for PDU Session Resource Setup")
        proc = r.get('procedureCode', -1)
    if proc != 29:
        raise RuntimeError(f"Expected PDUSessionResourceSetup (proc 29), got proc={proc}")

    ies = r['value'][1]['protocolIEs']
    pdu_list = find_ie(ies, 'PDUSessionResourceSetupListSUReq')
    sess_id = pdu_list[0]['pDUSessionID']
    xfer_ies = pdu_list[0]['pDUSessionResourceSetupRequestTransfer'][1]['protocolIEs']

    ie139 = next(ie for ie in xfer_ies if ie['id'] == 139)
    tunnel = ie139['value'][1][1]
    teid_hex = tunnel['gTP-TEID'].hex() if hasattr(tunnel['gTP-TEID'], 'hex') else str(tunnel['gTP-TEID'])
    upf_raw = tunnel.get('transportLayerAddress')
    upf_ip = None
    if upf_raw is not None:
        raw = upf_raw.get_val() if hasattr(upf_raw, 'get_val') else upf_raw
        if isinstance(raw, tuple):
            upf_ip = str(ipaddress.IPv4Address(raw[0]))

    ie136 = next(ie for ie in xfer_ies if ie['id'] == 136)
    qos_id = ie136['value'][1][0]['qosFlowIdentifier']

    # Extract IPv4 from PDU Session Establishment Accept
    nas_raw = pdu_list[0]['pDUSessionNAS-PDU']
    dl_nas = FGMMDLNASTransport(); dl_nas.from_bytes(nas_raw[7:])
    accept = FGSMPDUSessionEstabAccept()
    accept.from_bytes(dl_nas['PayloadContainer']['V'].get_val())
    addr = accept['PDUAddress']['PDUAddress']['Addr'].get_val()
    if isinstance(addr, (bytes, bytearray)):
        ipv4 = '.'.join(str(b) for b in addr[:4])
    else:
        ipv4 = f'{(addr >> 24) & 0xff}.{(addr >> 16) & 0xff}.{(addr >> 8) & 0xff}.{addr & 0xff}'

    logger.info(f"  ✓ IPv4={ipv4}, TEID=0x{teid_hex}, UPF={upf_ip}, QoS={qos_id}")

    ngap_send(sock, ngap_pdu_setup_resp(amf_ue_id, qos_id, gnb_addr, ran_id, sess_id))
    logger.info(f"  ✓ PDU Session Resource Setup Response sent")

    # ── Step 8: Optional UE Context Release ─────────────────────────────
    logger.info(f"\n[Step 8] Waiting for UE Context Release (5s)...")
    try:
        sock.settimeout(5)
        data = sock.recv(8192)
        if data:
            p = NGAP_PDU_Descriptions.NGAP_PDU; p.from_aper(data)
            t2, r2 = p()
            if r2.get('procedureCode') == 41:
                rel_ies = r2['value'][1]['protocolIEs']
                for ie in rel_ies:
                    if ie['id'] == 114:
                        pair = ie['value'][1]
                        if isinstance(pair, tuple) and pair[0] == 'uE-NGAP-ID-pair':
                            a = pair[1]['aMF-UE-NGAP-ID']
                            b2 = pair[1]['rAN-UE-NGAP-ID']
                            if hasattr(a, 'get_val'): a = a.get_val()
                            if hasattr(b2, 'get_val'): b2 = b2.get_val()
                            ngap_send(sock, ngap_ue_release_complete(int(a), int(b2), plmn_b, tac))
                            logger.info(f"  ✓ UE Context Release Complete sent")
    except socket.timeout:
        logger.info(f"  (No release received)")

    # ── Summary ─────────────────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"✓ TEST COMPLETE")
    logger.info(f"  SUPI={supi}  IPv4={ipv4}  TEID=0x{teid_hex}  UPF={upf_ip}  DNN={dnn}")
    logger.info(f"{'='*60}")

    try: sock.shutdown(socket.SHUT_RDWR); sock.close()
    except: pass

    return {'supi': supi, 'ipv4': ipv4, 'teid': teid_hex, 'upf_ip': upf_ip, 'dnn': dnn}


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>")

    ap = argparse.ArgumentParser(description='5G SA Single UE Test')
    ap.add_argument('--gnb-address', default='192.168.100.10')
    ap.add_argument('--core-address', default='192.168.55.53')
    ap.add_argument('--core-port', type=int, default=38412)
    ap.add_argument('--imsi', default='0000000001')
    ap.add_argument('--plmn', default='46099')
    ap.add_argument('--ki', default='12341234123412341234123412340000')
    ap.add_argument('--opc', default='71a121bb69baf3c0cc53fb5038a0131f')
    ap.add_argument('--dnn', default='internet')
    ap.add_argument('--tac', default='000001')
    ap.add_argument('--sst', type=int, default=1)
    ap.add_argument('--gnb-id', type=int, default=513)
    args = ap.parse_args()

    try:
        result = run_test(args.gnb_address, args.core_address, args.imsi,
                          plmn=args.plmn, ki_hex=args.ki, opc_hex=args.opc,
                          dnn=args.dnn, tac=args.tac, sst=args.sst,
                          amf_port=args.core_port, gnb_id=args.gnb_id)
        print(f"\nResult: {result}")
    except Exception as e:
        logger.error(f"FAILED: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)
