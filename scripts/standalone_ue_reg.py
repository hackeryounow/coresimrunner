#!/usr/bin/env python3
"""
Standalone 5G UE Registration + PDU Session Script
====================================================
Complete flow in a single file: parameter setup → NG Setup → Registration → PDU Session.
Uses raw bytes + pycrate for NGAP encoding.  No external runner needed.

Usage:
    python3 standalone_ue_reg.py [--amf-ip 192.168.55.53] [--gnb-ip 192.168.100.10]
"""

import sys, os, time, struct, socket, argparse, ipaddress

# ── paths ──────────────────────────────────────────────────────────────
sys.path.insert(0, '/root/pycrate')
sys.path.insert(0, '/root/CryptoMobile')

from loguru import logger
from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
import sctp

# CryptoMobile key derivation
try:
    from CryptoMobile.conv import conv_501_A2, conv_501_A4, conv_501_A6, conv_501_A7, conv_501_A8
    from CryptoMobile.Milenage import Milenage
except ImportError:
    from CryptoMobile import conv, Milenage
    conv_501_A2, conv_501_A4, conv_501_A6 = conv.conv_501_A2, conv.conv_501_A2, conv.conv_501_A6
    conv_501_A7, conv_501_A8 = conv.conv_501_A7, conv.conv_501_A8

# pycrate NAS
from pycrate_mobile.TS24501_FGMM import (
    FGMMRegistrationRequest, FGMMRegistrationComplete,
    FGMMSecurityModeComplete, FGMMSecProtNASMessage, FGMMULNASTransport,
)
from pycrate_mobile.TS24501_FGSM import FGSMPDUSessionEstabRequest
from pycrate_mobile.TS24501_IE import FGSIDTYPE_IMEISV

# =====================================================================
# 1. PARAMETERS
# =====================================================================
PLMN       = "46099"
MCC, MNC   = PLMN[:3], PLMN[3:]
MSIN       = "0000000001"
SUPI       = f"{PLMN}{MSIN}"
IMSI       = SUPI
K          = "12341234123412341234123412340000"
OPC        = "71a121bb69baf3c0cc53fb5038a0131f"
AMF_FIELD  = b"\x80\x00"
ABBA       = b"\x00\x00"
IMEISV     = "0000000000000001"
DNN        = b"internet"
TAC        = "000001"
SST        = 1
GNB_ID     = 513
GNB_ID_LEN = 32
GNB_NAME   = "CoreSim-Standalone"
RAN_UE_ID  = 1
CELL_ID    = 1
NGAP_PPID  = 60

# =====================================================================
# Helpers
# =====================================================================
def bcd(chars):
    s = ""
    for i in range(len(chars) // 2):
        s += chars[1+2*i] + chars[2*i]
    return bytes(bytearray.fromhex(s))

def plmn_bcd_encode(mccmnc):
    mccmnc = str(mccmnc)
    if len(mccmnc) == 5:
        return bcd(mccmnc[0]+mccmnc[1]+mccmnc[2]+'f'+mccmnc[3]+mccmnc[4])
    return bcd(mccmnc[0]+mccmnc[1]+mccmnc[2]+mccmnc[3]+mccmnc[4]+mccmnc[5])

PLMN_BCD = plmn_bcd_encode(PLMN)

def xor_bytes(a, b):
    return bytes([x ^ y for x, y in zip(a, b)])

def timestamp_bytes():
    return (int(time.time()) + 2208988800).to_bytes(4, byteorder='big')

PDU = NGAP_PDU_Descriptions.NGAP_PDU

def send_ngap(sock, msg):
    PDU.set_val(msg)
    sock.sctp_send(PDU.to_aper(), ppid=socket.htonl(NGAP_PPID))

def recv_ngap(sock, timeout=10):
    sock.settimeout(timeout)
    data = sock.recv(4096)
    if not data:
        return None, None
    PDU.from_aper(data)
    return PDU()

def extract_nas(pdu_dict):
    for ie in pdu_dict['value'][1]['protocolIEs']:
        if ie['value'][0] == 'NAS-PDU':
            return ie['value'][1]
    return None

def extract_amf_id(pdu_dict):
    for ie in pdu_dict['value'][1]['protocolIEs']:
        if ie['value'][0] == 'AMF-UE-NGAP-ID':
            return ie['value'][1]
    return None

def get_msg_type(pdu_dict):
    """Extract NAS message type, handling security-protected messages.
    
    NAS structure:
      EPD(1) + SecHdr(1) + [MAC(4) + SeqNo(1)] + inner_NAS...
    
    SecHdr values:
      0 = no security → type at nas[2]
      1 = integrity only → type at nas[2]  (no MAC)
      2 = integrity + ciphered → type at nas[7] (after MAC+SeqNo)
      3 = integrity + ciphered + new context → type at nas[7]
      4 = integrity + new context → type at nas[7]
    """
    nas = extract_nas(pdu_dict)
    if nas and len(nas) >= 3:
        sec_hdr = nas[1] & 0x0F
        if sec_hdr in (2, 3, 4):  # security-protected: type after MAC(4)+SeqNo(1)
            return nas[7] if len(nas) > 7 else nas[2]
        return nas[2]
    return None

# =====================================================================
# 2. NGAP MESSAGE BUILDERS (minimal / raw-bytes style)
# =====================================================================

def ngap_ng_setup_request():
    IEs = [
        {'id': 27, 'criticality': 'reject', 'value': ('GlobalRANNodeID',
            ('globalGNB-ID', {'pLMNIdentity': PLMN_BCD,
             'gNB-ID': ('gNB-ID', (GNB_ID, GNB_ID_LEN))}))},
        {'id': 82, 'criticality': 'ignore', 'value': ('RANNodeName', GNB_NAME)},
        {'id': 102, 'criticality': 'reject', 'value': ('SupportedTAList', [{
            'tAC': bytes.fromhex(TAC),
            'broadcastPLMNList': [{'pLMNIdentity': PLMN_BCD,
                'tAISliceSupportList': [{'s-NSSAI': {'sST': bytes([SST])}}]}]}])},
        {'id': 21, 'criticality': 'ignore', 'value': ('PagingDRX', 'v128')},
    ]
    return ('initiatingMessage', {'procedureCode': 21, 'criticality': 'reject',
            'value': ('NGSetupRequest', {'protocolIEs': IEs})})

def ngap_initial_ue_message(nas_pdu_bytes):
    IEs = [
        {'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', RAN_UE_ID)},
        {'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', nas_pdu_bytes)},
        {'id': 121, 'criticality': 'reject', 'value': ('UserLocationInformation',
            ('userLocationInformationNR', {
                'nR-CGI': {'pLMNIdentity': PLMN_BCD, 'nRCellIdentity': (CELL_ID, 36)},
                'tAI':    {'pLMNIdentity': PLMN_BCD, 'tAC': bytes.fromhex(TAC)},
                'timeStamp': timestamp_bytes()}))},
        {'id': 90, 'criticality': 'ignore', 'value': ('RRCEstablishmentCause', 'mo-Signalling')},
        {'id': 112, 'criticality': 'ignore', 'value': ('UEContextRequest', 'requested')},
    ]
    return ('initiatingMessage', {'procedureCode': 15, 'criticality': 'ignore',
            'value': ('InitialUEMessage', {'protocolIEs': IEs})})

def ngap_uplink_nas_transport(amf_id, nas_pdu_bytes):
    IEs = [
        {'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_id)},
        {'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', RAN_UE_ID)},
        {'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', nas_pdu_bytes)},
        {'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation',
            ('userLocationInformationNR', {
                'timeStamp': timestamp_bytes(),
                'tAI': {'pLMNIdentity': PLMN_BCD, 'tAC': bytes.fromhex(TAC)},
                'nR-CGI': {'pLMNIdentity': PLMN_BCD, 'nRCellIdentity': (CELL_ID, 36)}}))},
    ]
    return ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore',
            'value': ('UplinkNASTransport', {'protocolIEs': IEs})})

def ngap_initial_ctx_setup_response(amf_id):
    IEs = [
        {'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_id)},
        {'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', RAN_UE_ID)},
    ]
    return ('successfulOutcome', {'procedureCode': 14, 'criticality': 'ignore',
            'value': ('InitialContextSetupResponse', {'protocolIEs': IEs})})

def ngap_pdu_sess_resource_setup_response(amf_id, qos_flow_id, pdu_sess_id,
                                           gnb_ip="192.168.100.10", gnb_teid=2):
    ip_obj = ipaddress.ip_address(gnb_ip)
    gnb_addr_int = int(ip_obj)
    IEs = [
        {'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_id)},
        {'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', RAN_UE_ID)},
        {'id': 74, 'criticality': 'ignore', 'value': ('PDUSessionResourceSetupListSURes', [{
            'pDUSessionID': pdu_sess_id,
            'pDUSessionResourceSetupResponseTransfer':
                ('pDUSessionResourceSetupResponseTransfer', {
                    'dLQosFlowPerTNLInformation': {
                        'uPTransportLayerInformation': ('gTPTunnel', {
                            'transportLayerAddress': (gnb_addr_int, 32),
                            'gTP-TEID': struct.pack('!I', gnb_teid)}),
                        'associatedQosFlowList': [{'qosFlowIdentifier': qos_flow_id}]}})}])},
    ]
    return ('successfulOutcome', {'procedureCode': 29, 'criticality': 'ignore',
            'value': ('PDUSessionResourceSetupResponse', {'protocolIEs': IEs})})

# =====================================================================
# 3. NAS MESSAGE BUILDERS (pycrate RegIEs pattern)
# =====================================================================

def nas_registration_request():
    """Minimal cleartext Registration Request (mandatory IEs only)."""
    RegIEs = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 65},
        'NAS_KSI':    {'TSC': 0, 'Value': 7},
        '5GSRegType': {'FOR': 0, 'Value': 1},
        '5GSID': {'spare': 0, 'Fmt': 0, 'spare': 0, 'Type': 1,
                  'Value': {'PLMN': PLMN, 'RoutingInd': b'\x00\x00',
                            'spare': 0, 'ProtSchemeID': 0, 'HNPKID': 0,
                            'Output': bcd(MSIN)}},
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
    return FGMMRegistrationRequest(val=RegIEs).to_bytes()

def nas_registration_request_full():
    """Full Registration Request (for SMC NAS Container)."""
    RegIEs = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 65},
        'NAS_KSI':    {'TSC': 0, 'Value': 7},
        '5GSRegType': {'FOR': 0, 'Value': 1},
        '5GSID': {'spare': 0, 'Fmt': 0, 'spare': 0, 'Type': 1,
                  'Value': {'PLMN': PLMN, 'RoutingInd': b'\x00\x00',
                            'spare': 0, 'ProtSchemeID': 0, 'HNPKID': 0,
                            'Output': bcd(MSIN)}},
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
        'NSSAI': [{'SNSSAI': {'SST': SST}}],
    }
    msg = FGMMRegistrationRequest(val=RegIEs)
    msg['5GMMCap']['5GMMCap'].disable_from(8)
    return msg.to_bytes()

def nas_auth_response(res_star_hex):
    """Authentication Response as raw bytes: 7e00 57 2d 10 <res*>."""
    return bytes.fromhex(f'7e00572d10{res_star_hex}')

def nas_security_mode_complete(ciph_algo, int_algo, k_nas_enc, k_nas_int):
    """Security Mode Complete with NAS Container (full Reg Request) + IMEISV."""
    # Build inner SMC message with NAS Container
    IEs = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0},
        'IMEISV': {'Type': FGSIDTYPE_IMEISV, 'Digit1': int(IMEISV[0]), 'Digits': IMEISV[1:]},
        'NASContainer': {},
    }
    smc_msg = FGMMSecurityModeComplete(val=IEs)
    smc_msg['NASContainer']['V'].set_val(nas_registration_request_full())

    # Wrap with security header (SecHdr=4 for SMC: new security context)
    sec = FGMMSecProtNASMessage(val={'5GMMHeaderSec': {'EPD': 126, 'spare': 0, 'SecHdr': 4}})
    sec['NASMessage'].set_val(smc_msg)
    if ciph_algo != 0:
        sec.encrypt(key=k_nas_enc, dir=0, fgea=ciph_algo, seqnoff=0, bearer=1)
    sec.mac_compute(key=k_nas_int, dir=0, fgia=int_algo, seqnoff=0, bearer=1)
    return sec.to_bytes()

def nas_registration_complete(k_nas_enc, k_nas_int, ciph_algo, int_algo):
    """Registration Complete with security protection (SecHdr=2)."""
    plain = FGMMRegistrationComplete().to_bytes()
    sec = FGMMSecProtNASMessage(val={'5GMMHeaderSec': {'EPD': 126, 'spare': 0, 'SecHdr': 2}})
    sec['NASMessage'].set_val(plain)
    if ciph_algo != 0:
        sec.encrypt(key=k_nas_enc, dir=0, fgea=ciph_algo, seqnoff=0, bearer=1)
    sec.mac_compute(key=k_nas_int, dir=0, fgia=int_algo, seqnoff=0, bearer=1)
    return sec.to_bytes()

def nas_pdu_session_establishment_request():
    """PDU Session Establishment Request (plain SM NAS)."""
    smIEs = {
        '5GSMHeader':  {'PDUSessID': 1, 'Type': 193, 'PTI': 1},
        'PDUSessType': {'Value': 1},   # IPv4
        'SSCMode':     {'Value': 1},
        '5GSMCap':     {'TPMIC': 0, 'ATSSS-ST': 0, 'EPT-S1': 0, 'MH6-PDU': 0, 'RQoS': 0},
        'ExtProtConfig': {'Ext': 1, 'spare': 0, 'Prot': 0},
    }
    return FGSMPDUSessionEstabRequest(val=smIEs).to_bytes()

def nas_ul_nas_transport_with_pdu(pdu_est_req):
    """UL NAS Transport carrying PDU Session Est Req + DNN."""
    ulIEs = {
        '5GMMHeader': {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 103},
        'PDUSessID':  1,
        'RequestType': 1,
        'SNSSAI':     {'SST': SST},
    }
    msg = FGMMULNASTransport(val=ulIEs)
    msg['PayloadContainer']['V'].set_val(pdu_est_req)
    # Append DNN manually (pycrate bug workaround)
    dnn_msg = bytes.fromhex(f'25{len(DNN)+1:02x}{len(DNN):02x}') + DNN
    return msg.to_bytes() + dnn_msg

def nas_ul_nas_transport_secured(inner_nas, k_nas_enc, k_nas_int, ciph_algo, int_algo):
    """Wrap a plain UL NAS Transport in security protection (SecHdr=2)."""
    sec = FGMMSecProtNASMessage(val={'5GMMHeaderSec': {'EPD': 126, 'spare': 0, 'SecHdr': 2}})
    sec['NASMessage'].set_val(inner_nas)
    if ciph_algo != 0:
        sec.encrypt(key=k_nas_enc, dir=0, fgea=ciph_algo, seqnoff=0, bearer=1)
    sec.mac_compute(key=k_nas_int, dir=0, fgia=int_algo, seqnoff=0, bearer=1)
    return sec.to_bytes()

# =====================================================================
# 4. AUTH: Milenage + RES* computation
# =====================================================================
def compute_res_star(nas_pdu):
    """Extract RAND/AUTN from Auth Request NAS, compute KSEAF and RES*."""
    rand_val  = nas_pdu[8:24]
    autn      = nas_pdu[24:]
    sqn_xor_ak = autn[2:8]
    amf_field  = autn[8:10]

    SNN = f"5G:mnc{MNC.zfill(3)}.mcc{MCC.zfill(3)}.3gppnetwork.org".encode()
    k_bytes = bytes.fromhex(K)
    opc_bytes = bytes.fromhex(OPC)

    mil = Milenage(opc_bytes)
    mil.set_opc(opc_bytes)
    RES, CK, IK, AK = mil.f2345(k_bytes, rand_val)
    SQN = xor_bytes(AK, sqn_xor_ak)
    mil.f1(k_bytes, rand_val, SQN=SQN, AMF=amf_field)
    res_star = conv_501_A4(CK, IK, SNN, rand_val, RES)
    kseaf    = conv_501_A6(conv_501_A2(CK, IK, SNN, sqn_xor_ak), SNN)
    return kseaf, res_star.hex()

def derive_nas_keys(kseaf, ciph_algo, int_algo):
    """Derive K_AMF → K_NAS_enc, K_NAS_int."""
    k_amf     = conv_501_A7(kseaf, SUPI.encode(), ABBA)
    k_nas_enc = conv_501_A8(k_amf, alg_type=1, alg_id=ciph_algo)[16:]
    k_nas_int = conv_501_A8(k_amf, alg_type=2, alg_id=int_algo)[16:]
    return k_nas_enc, k_nas_int

# =====================================================================
# 5. MAIN FLOW
# =====================================================================
def run(amf_ip, gnb_ip, amf_port=38412):
    logger.remove()
    logger.add(sys.stdout, level="INFO",
               format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | <level>{message}</level>")

    logger.info(f"SUPI={SUPI}  AMF={amf_ip}:{amf_port}  gNB={gnb_ip}")

    # ── Step 1: SCTP connect ──────────────────────────────────────────
    logger.info("Step 1: SCTP connect + NG Setup")
    sock = sctp.sctpsocket_tcp(socket.AF_INET)
    sock.bind((gnb_ip, 0))
    sock.connect((amf_ip, amf_port))

    send_ngap(sock, ngap_ng_setup_request())
    _, pdu = recv_ngap(sock)
    assert pdu is not None, "No NG Setup Response!"
    pdu_type = pdu.get('value', (None,))[0]
    assert pdu_type != 'unsuccessfulOutcome', f"NG Setup failed: {pdu}"
    ies = pdu['value'][1]['protocolIEs']
    amf_name = next((ie['value'][1] for ie in ies if ie['value'][0] == 'AMFName'), '?')
    logger.info(f"  NG Setup OK  AMF={amf_name}")

    # ── Step 2: Initial UE Message (Registration Request) ─────────────
    logger.info("Step 2: Initial UE Message (Registration Request)")
    reg_req = nas_registration_request()
    logger.info(f"  NAS-PDU ({len(reg_req)}B): {reg_req.hex()}")
    send_ngap(sock, ngap_initial_ue_message(reg_req))

    # ── Step 3: Authentication Request → Response ─────────────────────
    logger.info("Step 3: Authentication")
    _, pdu = recv_ngap(sock)
    proc = pdu['procedureCode']
    msg_type = get_msg_type(pdu)
    assert msg_type == 0x56, f"Expected Auth Request (0x56), got 0x{msg_type:02x}"
    amf_id = extract_amf_id(pdu)
    nas = extract_nas(pdu)
    kseaf, res_star = compute_res_star(nas)
    logger.info(f"  AMF_UE_ID={amf_id}  RES*={res_star}")

    auth_resp = nas_auth_response(res_star)
    send_ngap(sock, ngap_uplink_nas_transport(amf_id, auth_resp))

    # ── Step 4: Security Mode Command → Complete ──────────────────────
    logger.info("Step 4: Security Mode")
    _, pdu = recv_ngap(sock)
    msg_type = get_msg_type(pdu)
    assert msg_type == 0x5d, f"Expected SMC (0x5d), got 0x{msg_type:02x}"
    nas = extract_nas(pdu)
    # Parse algorithm selection from SMC NAS (after 7-byte security header)
    from pycrate_mobile.TS24501_FGMM import FGMMSecurityModeCommand
    smc = FGMMSecurityModeCommand()
    smc.from_bytes(nas[7:])
    ciph_algo = smc['NASSecAlgo']['NASSecAlgo']['CiphAlgo'].get_val()
    int_algo  = smc['NASSecAlgo']['NASSecAlgo']['IntegAlgo'].get_val()
    logger.info(f"  CiphAlgo={ciph_algo}  IntAlgo={int_algo}")

    k_nas_enc, k_nas_int = derive_nas_keys(kseaf, ciph_algo, int_algo)
    smc_complete_nas = nas_security_mode_complete(ciph_algo, int_algo, k_nas_enc, k_nas_int)
    send_ngap(sock, ngap_uplink_nas_transport(amf_id, smc_complete_nas))

    # ── Step 5: Initial Context Setup (Registration Accept) ───────────
    logger.info("Step 5: Registration Accept")
    _, pdu = recv_ngap(sock)
    proc = pdu['procedureCode']
    assert proc == 14, f"Expected InitialContextSetup (14), got proc={proc}"
    logger.info(f"  ✓ Registered  (proc=InitialContextSetupRequest)")

    # Send Initial Context Setup Response
    send_ngap(sock, ngap_initial_ctx_setup_response(amf_id))

    # Send Registration Complete
    reg_complete = nas_registration_complete(k_nas_enc, k_nas_int, ciph_algo, int_algo)
    send_ngap(sock, ngap_uplink_nas_transport(amf_id, reg_complete))

    # ── Step 6: PDU Session Establishment ─────────────────────────────
    logger.info("Step 6: PDU Session Establishment Request")
    pdu_est_req = nas_pdu_session_establishment_request()
    ul_transport = nas_ul_nas_transport_with_pdu(pdu_est_req)
    secured_ul = nas_ul_nas_transport_secured(ul_transport, k_nas_enc, k_nas_int, ciph_algo, int_algo)
    send_ngap(sock, ngap_uplink_nas_transport(amf_id, secured_ul))

    # ── Step 7: PDU Session Resource Setup → Response ─────────────────
    logger.info("Step 7: PDU Session Resource Setup")
    # May receive ConfigurationUpdateCommand first, skip it
    for _ in range(5):
        _, pdu = recv_ngap(sock, timeout=15)
        if pdu is None:
            logger.error("  Timeout waiting for PDU Session Resource Setup")
            break
        proc = pdu['procedureCode']
        if proc == 29:  # PDUSessionResourceSetup
            break
        logger.info(f"  Skipping proc={proc}")

    if pdu and pdu['procedureCode'] == 29:
        # Parse UE IP and TEID from PDU Session Resource Setup Request
        setup_list = None
        for ie in pdu['value'][1]['protocolIEs']:
            if ie['value'][0] == 'PDUSessionResourceSetupListSUReq':
                setup_list = ie['value'][1]
                break

        if setup_list:
            pdu_sess_id = setup_list[0]['pDUSessionID']
            transfer = setup_list[0]['pDUSessionResourceSetupRequestTransfer'][1]['protocolIEs']
            ie_139 = next(ie for ie in transfer if ie['id'] == 139)
            teid_bytes = ie_139['value'][1][1]['gTP-TEID']
            upf_addr = ie_139['value'][1][1].get('transportLayerAddress')
            ie_136 = next(ie for ie in transfer if ie['id'] == 136)
            qos_flow_id = ie_136['value'][1][0]['qosFlowIdentifier']

            # Parse UPF IP from tuple format
            upf_ip = None
            if isinstance(upf_addr, tuple):
                upf_ip = str(ipaddress.IPv4Address(upf_addr[0]))

            # Parse UE IP from NAS PDU
            nas_pdu = extract_nas(pdu)
            from pycrate_mobile.TS24501_FGMM import FGMMDLNASTransport
            from pycrate_mobile.TS24501_FGSM import FGSMPDUSessionEstabAccept
            dlnas = FGMMDLNASTransport()
            dlnas.from_bytes(nas_pdu[7:])
            estab_accept = FGSMPDUSessionEstabAccept()
            estab_accept.from_bytes(dlnas['PayloadContainer']['V'].get_val())
            pdu_addr = estab_accept['PDUAddress']['PDUAddress']['Addr'].get_val()
            ue_ipv4 = str(ipaddress.IPv4Address(pdu_addr))

            logger.info(f"  ✓ PDU Session OK")
            logger.info(f"    UE IPv4:  {ue_ipv4}")
            logger.info(f"    TEID:     0x{teid_bytes.hex()}")
            logger.info(f"    UPF IP:   {upf_ip}")
            logger.info(f"    QoS Flow: {qos_flow_id}")
            logger.info(f"    PDU Sess: {pdu_sess_id}")

            # Send PDU Session Resource Setup Response
            resp = ngap_pdu_sess_resource_setup_response(
                amf_id, qos_flow_id, pdu_sess_id, gnb_ip=gnb_ip)
            send_ngap(sock, resp)
            logger.info(f"  PDU Session Resource Setup Response sent")
    else:
        logger.warning("  PDU Session Resource Setup not received")

    # ── Done ──────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 50)
    logger.info("  Registration + PDU Session COMPLETE")
    logger.info("=" * 50)

    # Keep connection alive briefly to receive any remaining messages
    time.sleep(2)
    sock.close()


# =====================================================================
# CLI
# =====================================================================
if __name__ == '__main__':
    p = argparse.ArgumentParser(description="Standalone 5G UE Registration + PDU session")
    p.add_argument('--amf-ip', default='192.168.55.53', help='AMF IP address')
    p.add_argument('--gnb-ip', default='192.168.100.10', help='gNB source IP')
    p.add_argument('--amf-port', type=int, default=38412)
    p.add_argument('--plmn', default=PLMN)
    p.add_argument('--msin', default=MSIN)
    p.add_argument('--ki', default=K)
    p.add_argument('--opc', default=OPC)
    p.add_argument('--dnn', default=DNN.decode())
    p.add_argument('--tac', default=TAC)
    p.add_argument('--sst', type=int, default=SST)
    args = p.parse_args()

    # Override globals from CLI
    PLMN = args.plmn;  MCC = PLMN[:3];  MNC = PLMN[3:]
    MSIN = args.msin;  SUPI = f"{PLMN}{MSIN}"
    K = args.ki;  OPC = args.opc
    DNN = args.dnn.encode();  TAC = args.tac;  SST = args.sst
    PLMN_BCD = plmn_bcd_encode(PLMN)

    run(args.amf_ip, args.gnb_ip, args.amf_port)
