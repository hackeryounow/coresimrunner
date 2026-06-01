#!/usr/bin/env python3
"""
Integrated Messages - NGAP and NAS message construction and parsing.

This module integrates the message handling logic from 5gregpdu/message/message.py
and related modules into CoreSimRunner for multi-UE testing.
"""

import sys
import os

# Add workspace libraries to Python path
WORKSPACE_ROOT = '/root'
PYCRATE_PATH = os.path.join(WORKSPACE_ROOT, 'pycrate')
CRYPTOMOBILE_PATH = os.path.join(WORKSPACE_ROOT, 'CryptoMobile')

if PYCRATE_PATH not in sys.path:
    sys.path.insert(0, PYCRATE_PATH)
if CRYPTOMOBILE_PATH not in sys.path:
    sys.path.insert(0, CRYPTOMOBILE_PATH)

import time
import struct
import ipaddress
from enum import Enum
from typing import Dict, List, Tuple, Optional, Any


# ============================================================================
# Enums and Constants (from 5gregpdu/message/code.py)
# ============================================================================

class ProcedureCode(Enum):
    ID_DOWNLINK_NAS_TRANSPORT = 4
    ID_ERROR_INDICATION = 9
    ID_INITIAL_CONTEXT_SETUP = 14
    ID_INITIAL_UE_MESSAGE = 15
    ID_LOCATION_REPORTING_CONTROL = 16
    ID_NGSetup = 21
    ID_PAGING = 24
    ID_PDU_SESSION_RESOURCE_SETUP = 29
    ID_UE_CONTEXT_RELEASE = 41
    ID_UE_CONTEXT_RELEASE_REQUEST = 42
    ID_UPLINK_NAS_TRANSPORT = 46
    ID_HO_REQUIRED = 49
    ID_HANDOVER_COMMAND = 50
    
    def __str__(self):
        return f"{self.name} ({self.value})"


class MessageType(Enum):
    AUTHENTICATION_REQUEST = 0x56
    SECURITY_MODE_COMMAND = 0x5d
    REGISTRATION_ACCEPT = 0x42
    REGISTRATION_COMPLETE = 0x43
    CONFIGURATION_UPDATE_COMMNAD = 0x54
    UL_NAS_TRANSPORT = 0x67
    DL_NAS_TRANSPORT = 0x68
    PDU_SESSION_ESTABLISHMENT_REQUEST = 0xc1
    SERVICE_REQUEST = 0x4c
    SERVICE_ACCEPT = 0x4e


RAN_UE_NGAP_LEN_LABLES = {
    '00': 1,
    '04': 2,
    '08': 3,
    '0c': 4
}


# ============================================================================
# Identity Classes (from 5gregpdu/message/identity.py)
# ============================================================================

class FGGUTI:
    """5G GUTI (Globally Unique Temporary Identifier)"""
    
    def __init__(self, plmn, amf_region_id, amf_set_id, amf_ptr, tmsi):
        self.plmn = plmn
        self.amf_region_id = amf_region_id
        self.amf_set_id = amf_set_id
        self.amf_ptr = amf_ptr
        self.tmsi = tmsi
    
    def __str__(self):
        return str({
            "5G-GUTI": {
                "PLMN": self.plmn,
                "AMFRegionID": self.amf_region_id,
                "AMFSetID": self.amf_set_id,
                "AMFPtr": self.amf_ptr,
                "5GTMSI": hex(self.tmsi)
            }
        })


# ============================================================================
# Utility Functions (from 5gregpdu/utils/cryproutils.py)
# ============================================================================

def int_to_bin_str(n, width):
    return bin(n)[2:].zfill(width)

def int_to_hex8(n: int, upper=False) -> str:
    fmt = '{:08X}' if upper else '{:08x}'
    return fmt.format(n & 0xFFFFFFFF)

def int_to_hex4(n: int, upper=False) -> str:
    fmt = '{:04X}' if upper else '{:04x}'
    return fmt.format(n & 0xFFFFFFFF)

def bcd(chars):  
    bcd_string = ""
    for i in range(len(chars) // 2):
        bcd_string += chars[1+2*i] + chars[2*i]
    bcd_bytes = bytes(bytearray.fromhex(bcd_string))
    return bcd_bytes

def byte_xor(ba1, ba2):
    """ XOR two byte strings """
    return bytes([_a ^ _b for _a, _b in zip(ba1, ba2)])

def calculateRes(opc, k, rand: bytes, sqn_xor_ak: bytes, mnc="099", mcc="460", amf=b"8000"):
    """
    Calculate KSEAF and RES based on the provided parameters using the Milenage algorithm.
    """
    SNN = f"5G:mnc{mnc.zfill(3)}.mcc{mcc.zfill(3)}.3gppnetwork.org".encode()
    
    try:
        from CryptoMobile.conv import conv_501_A4, conv_501_A2, conv_501_A6
        from CryptoMobile.Milenage import Milenage
    except ImportError:
        # Fallback imports for different CryptoMobile versions
        from CryptoMobile import conv
        from CryptoMobile import Milenage
        conv_501_A4 = conv.conv_501_A4
        conv_501_A2 = conv.conv_501_A2
        conv_501_A6 = conv.conv_501_A6
    
    Mil = Milenage(opc)
    Mil.set_opc(opc)
    RES, CK, IK, AK = Mil.f2345(k, rand)
    SQN = byte_xor(AK, sqn_xor_ak)
    mac_a = Mil.f1(k, rand, SQN=SQN, AMF=amf)
    Res = conv_501_A4(CK, IK, SNN, rand, RES)
    KAUSF = conv_501_A2(CK, IK, SNN, sqn_xor_ak)
    KSEAF = conv_501_A6(KAUSF,SNN)
    return KSEAF, Res.hex()

def plmn_bcd_encode(mccmnc):
    mccmnc = str(mccmnc)
    if len(mccmnc) == 5:
        return bcd(mccmnc[0] + mccmnc[1] + mccmnc[2] + 'f' + mccmnc[3] + mccmnc[4]) 
    elif len(mccmnc) == 6:
        return bcd(mccmnc[0] + mccmnc[1] + mccmnc[2] + mccmnc[3] + mccmnc[4] + mccmnc[5])
    else:
        return b''

def plmn_bcd_decode(bcd_bytes):
    """
    Decode PLMN from BCD encoded bytes.
    """
    plmn = ""
    for byte in bcd_bytes:
       high = (byte >> 4) & 0xF
       low = byte & 0xF
       plmn += str(low) 
       if high != 0xF:
           plmn += str(high)
    return plmn


# ============================================================================
# Helper Functions (from 5gregpdu/message/message.py)
# ============================================================================

def fgmm_security_protected_nas_message(CiphAlgo, IntegAlgo, k_nas_enc, k_nas_int, secModeMsg, is_pdu=False, is_service_request=False):
    """
    Create security protected NAS message with proper header and encryption/integrity protection.
    """
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMSecProtNASMessage
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMSecProtNASMessage
    
    IEs = {}
    if is_service_request:
        IEs['5GMMHeaderSec'] = {'EPD': 126, 'spare': 0, 'SecHdr': 1}
    elif CiphAlgo != 0 or is_pdu:
        IEs['5GMMHeaderSec'] = {'EPD': 126, 'spare': 0, 'SecHdr': 2}
    else:
        IEs['5GMMHeaderSec'] = {'EPD': 126, 'spare': 0, 'SecHdr': 4}
    
    SecMsg = FGMMSecProtNASMessage(val=IEs)
    SecMsg['NASMessage'].set_val(secModeMsg)
    
    # Apply encryption if ciphering algorithm is enabled
    if CiphAlgo != 0:
        SecMsg.encrypt(key=k_nas_enc, dir=0, fgea=CiphAlgo, seqnoff=0, bearer=1)
    
    # Apply integrity protection
    SecMsg.mac_compute(key=k_nas_int, dir=0, fgia=IntegAlgo, seqnoff=0, bearer=1)
    return SecMsg.to_bytes()


def fgmm_registration_request_message(msin="0112345038", plmn="46099", nssai=[{'SST': 1}]):
    """
    Create registration request message with proper NSSAI handling.
    """
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMRegistrationRequest
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMRegistrationRequest
    
    RegIEs = {}
    RegIEs['5GMMHeader'] = {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 65}
    RegIEs['NAS_KSI'] = {'TSC': 0, 'Value': 7}
    RegIEs['5GSRegType'] = {'FOR': 1, 'Value': 1}
    RegIEs['5GSID'] = {'spare': 0, 'Fmt': 0, 'spare': 0, 'Type': 1, 'Value': {'PLMN': plmn, 'RoutingInd': b'\x00\x00', 'spare': 0, 'ProtSchemeID': 0, 'HNPKID': 0, 'Output': bcd(msin)}}
    RegIEs['UESecCap'] = {'5G-EA0': 1, '5G-EA1_128': 1, '5G-EA2_128': 1, '5G-EA3_128': 1, '5G-EA4': 0, '5G-EA5': 0, '5G-EA6': 0, '5G-EA7': 0, '5G-IA0': 1, '5G-IA1_128': 1, '5G-IA2_128': 1, '5G-IA3_128': 1, '5G-IA4': 0, '5G-IA5': 0, '5G-IA6': 0, '5G-IA7': 0, 'EEA0': 1, 'EEA1_128': 1, 'EEA2_128': 1, 'EEA3_128': 1, 'EEA4': 0, 'EEA5': 0, 'EEA6': 0, 'EEA7': 0, 'EIA0': 1, 'EIA1_128': 1, 'EIA2_128': 1, 'EIA3_128': 1, 'EIA4': 0, 'EIA5': 0, 'EIA6': 0, 'EIA7': 0}
    RegIEs['5GSUpdateType'] = {'EPS-PNB-CIoT': 0, '5GS-PNB-CIoT': 0, 'NG-RAN-RCU': 0, 'SMSRequested': 0}
    RegIEs['5GMMCap'] = {'SGC': 0, '5G-HC-CP-CIoT': 0, 'N3Data': 0, '5G-CP-CIoT': 0, 'RestrictEC': 0, 'LPP': 0, 'HOAttach': 0, 'S1Mode': 0}
    RegIEs['NSSAI'] = [{'SNSSAI': s} for s in nssai]
    
    RegMsg = FGMMRegistrationRequest(val=RegIEs)
    RegMsg['5GMMCap']['5GMMCap'].disable_from(8)
    return RegMsg.to_bytes()


def fgmm_security_mode_command_message(regReqMsg, imeisv):
    """
    Create security mode command message with IMEISV.
    """
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMSecurityModeComplete
        from pycrate_mobile.TS24501_IE import FGSIDTYPE_IMEISV
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMSecurityModeComplete, FGSIDTYPE_IMEISV
    
    IEs = {}
    IEs['5GMMHeader'] = {'EPD': 126, 'spare': 0, 'SecHdr': 0}
    IEs['IMEISV'] = {'Type': FGSIDTYPE_IMEISV, 'Digit1': int(imeisv[0]), 'Digits': imeisv[1:]}
    IEs['NASContainer'] = {}
    
    SMC_Msg = FGMMSecurityModeComplete(val=IEs)
    SMC_Msg['NASContainer']['V'].set_val(regReqMsg)
    return SMC_Msg.to_bytes()


def fgmm_registration_complete_message():
    """
    Create registration complete message.
    """
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMRegistrationComplete
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMRegistrationComplete
    
    RegCompleteMsg = FGMMRegistrationComplete()
    return RegCompleteMsg.to_bytes()


def fgsm_pdu_session_establishment_request_message():
    """
    Create PDU session establishment request message.
    """
    try:
        from pycrate_mobile.TS24501_FGSM import FGSMPDUSessionEstabRequest
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGSMPDUSessionEstabRequest
    
    smIEs = {}
    # TODO: PTI 是用户事务的唯一标识，不同用户需要不同的 PTI，以确保事务的唯一性和关联性。
    smIEs['5GSMHeader'] = {'Type': 193, 'PTI': 1}
    smIEs['PDUSessType'] = {'Value': 1}  # PDU Session Type: IPv4
    smIEs['SSCMode'] = {'Value': 1}
    smIEs['5GSMCap'] = {'TPMIC': 0, 'ATSSS-ST': 0, 'EPT-S1': 0, 'MH6-PDU': 0, 'RQoS': 0}
    smIEs['ExtProtConfig'] = {'Ext': 1, 'spare': 0, 'Prot': 0} 
    # smIEs['IntegrityProtMaxDataRate'] = {}  # Request accepted

    PduSessEstabReq = FGSMPDUSessionEstabRequest(val=smIEs)
    return PduSessEstabReq.to_bytes()


def fgmm_ul_nas_transport_message(pduSessEstablishmentReq, dnn=b'internet', snssai={'SST': 1}): 
    """
    Create UL NAS transport message with proper SNSSAI and DNN handling.
    """
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMULNASTransport
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMULNASTransport
    
    ulIEs = {}
    ulIEs['5GMMHeader'] = {'EPD': 126, 'spare': 0, 'SecHdr': 0, 'Type': 103}
    ulIEs['PDUSessID'] = 1
    ulIEs['RequestType'] = 1
    ulIEs['SNSSAI'] = {'SST': snssai["SST"]}  # Service Data
    if snssai.get("SD"):
        ulIEs['SNSSAI']['SD'] = snssai["SD"]        
 
    ULNasTransportMsg = FGMMULNASTransport(val=ulIEs)
    ULNasTransportMsg['PayloadContainer']['V'].set_val(pduSessEstablishmentReq)
    # ULNasTransportMsg['DNN'].set_val({'T': 0x25, 'V': dnn})

    # mamually set DNN, because of the bug in to_bytes method makes dnn information lost
    # fomat is 25[length of the DNN + length of the Length field)][length of the DNN][DNN]
    # for example, if DNN is "internet", the length of the DNN is 8, the length of the Length field is 1, 
    # the hex of DNN is 696e7465726e6574, so the DNN message is 250908696e7465726e6574
    dnn = b"internet"
    dnn_str_len = len(dnn)
    dnn_msg = f"25{hex(dnn_str_len + 1)[2:].zfill(2)}{hex(dnn_str_len)[2:].zfill(2)}" + dnn.hex()
    dnn_msg = bytes.fromhex(dnn_msg)
    return ULNasTransportMsg.to_bytes() + dnn_msg


# ============================================================================
# Message Construction Functions (from 5gregpdu/message/message.py)
# ============================================================================

def NGAPSetupReqeust(plmn, gnb_name, gnb_id, gnb_id_len, tac, sst=0x1, sd=None):
    IEs = []
    IEs.append({'id': 27, 'criticality': 'reject', 'value': ('GlobalRANNodeID', ('globalGNB-ID', {'pLMNIdentity': plmn_bcd_encode(plmn), 'gNB-ID': ('gNB-ID', (gnb_id, gnb_id_len))}))})
    IEs.append({'id': 82, 'criticality': 'ignore', 'value': ('RANNodeName', gnb_name)})
    IEs.append({'id': 102, 'criticality': 'reject', 'value': ('SupportedTAList', [{'tAC': bytes.fromhex(tac), 'broadcastPLMNList': [{'pLMNIdentity': plmn_bcd_encode(plmn), 'tAISliceSupportList': [{'s-NSSAI': {'sST': bytes.fromhex(hex(sst)[2:].zfill(2)), **({'sD': bytes.fromhex(hex(sd)[2:].zfill(6))} if sd is not None else {})}}]}]}])})
    IEs.append({'id': 21, 'criticality': 'ignore', 'value': ('PagingDRX', 'v128')})
    val = ('initiatingMessage', {'procedureCode': 21, 'criticality': 'reject', 'value': ('NGSetupRequest', {'protocolIEs': IEs})})
    return val  

def InitialUEMessage(plmn_bcd: bytes, tac: str, imsi_bcd: bytes, nr_cell_id=1, ran_ue_ngap_id=1):
    """
    gNB->AMF, Initial UE Message
    """
    IEs = []
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', bytes.fromhex(f'7e00417c000d01{plmn_bcd.hex()}00000000{imsi_bcd.hex()}2e0480c0f0f0'))})
    IEs.append({'id': 121, 'criticality': 'reject', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (nr_cell_id, 36)}}))})
    IEs.append({'id': 90, 'criticality': 'ignore', 'value': ('RRCEstablishmentCause', 'mo-Signalling')})
    IEs.append({'id': 112, 'criticality': 'ignore', 'value': ('UEContextRequest', "requested")})
    val = ('initiatingMessage', {'procedureCode': 15, 'criticality': 'ignore', 'value': ('InitialUEMessage', {'protocolIEs': IEs})})
    return val

def AuthRequestMessage(pdu_dict, k, opc, mcc, mnc, amf=b"8000"):
    """
    AMF->gNB, Authentication Request.
    """
    amf_ue_ngap_id = pdu_dict['value'][1]['protocolIEs'][0]['value'][1]
    ran_ue_ngap_id = pdu_dict['value'][1]['protocolIEs'][1]['value'][1]
    nas_pdu = pdu_dict['value'][1]['protocolIEs'][2]['value'][1]
    rand = nas_pdu[8:24]
    autn = nas_pdu[24:]
    autn_sqn_xor_ak = autn[2:8]
    amf = autn[8:10]
    mac = autn[10:18]
    KSEAF, res_star = calculateRes(opc, k, rand, autn_sqn_xor_ak, mnc, mcc, amf)
    return KSEAF, res_star, amf_ue_ngap_id

def AuthenticationResponseMessage(res_star, amf_ue_ngap_id, plmn_bcd: bytes, tac="000001", gnb_nr_cell_id=1, ran_ue_ngap_id=1):
    """
    gNB->AMF, UplinkNASTransport, NAS-PDU message_type is 0x57.
    """
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', bytes.fromhex(f'7e00572d10{res_star}'))})
    IEs.append({'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'timeStamp': (int(time.time()) + 2208988800).to_bytes(4, byteorder='big'), 'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (gnb_nr_cell_id, 36)}}))})
    val = ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore', 'value': ('UplinkNASTransport', {'protocolIEs': IEs})})
    return val

def SecurityModeCommandMessage(pdu_dict):
    for IE in pdu_dict['value'][1]['protocolIEs']:
        if IE['value'][0] == 'NAS-PDU':
            nas_pdu = IE['value'][1]
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMSecurityModeCommand
    except ImportError:
        # Handle different pycrate structure
        from pycrate_mobile.TS24501_IE import FGMMSecurityModeCommand
        
    SecModeMsg = FGMMSecurityModeCommand()
    SecModeMsg.from_bytes(nas_pdu[7:])
    ciphAlgo = SecModeMsg['NASSecAlgo']['NASSecAlgo']['CiphAlgo']
    ntegAlgo = SecModeMsg['NASSecAlgo']['NASSecAlgo']['IntegAlgo']
    return ciphAlgo.get_val(), ntegAlgo.get_val()

def SecurityModeCompleteMessage(amf_ue_ngap_id, kseaf, plmn_bcd: bytes, slices, imeisv, SUPI=b"460991234567893", tac="000001", ABBA=b"\x00\x00", ciphAlgo=0, ntegAlgo=2, ran_ue_ngap_id=1):
    try:
        from CryptoMobile.conv import conv_501_A7, conv_501_A8
    except ImportError:
        from CryptoMobile import conv
        conv_501_A7 = conv.conv_501_A7
        conv_501_A8 = conv.conv_501_A8
    
    k_amf = conv_501_A7(kseaf, SUPI, ABBA)
    k_nas_enc = conv_501_A8(k_amf, alg_type=1, alg_id=ciphAlgo)
    k_nas_enc = k_nas_enc[16:]
    k_nas_int = conv_501_A8(k_amf, alg_type=2, alg_id=ntegAlgo)
    k_nas_int = k_nas_int[16:]
    
    # Use the helper functions for cleaner implementation
    regReqMsg = fgmm_registration_request_message(
        msin=SUPI.decode()[-10:], 
        plmn=plmn_bcd_decode(plmn_bcd), 
        nssai=[slices]
    )
    secModeMsg = fgmm_security_mode_command_message(regReqMsg, imeisv)
    secProtNasMsg = fgmm_security_protected_nas_message(ciphAlgo, ntegAlgo, k_nas_enc, k_nas_int, secModeMsg)
    nas_encoded = secProtNasMsg.hex()
    
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', bytes.fromhex(nas_encoded))})
    IEs.append({'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'timeStamp': (int(time.time()) + 2208988800).to_bytes(4, byteorder='big'), 'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (1, 36)}}))})
    
    val = ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore', 'value': ('UplinkNASTransport', {'protocolIEs': IEs})})
    return val, k_nas_int, k_nas_enc

def InitialContextSetupRequestMessage(pdu_dict):
    for IE in pdu_dict['value'][1]['protocolIEs']:
        if IE['value'][0] == 'NAS-PDU':
            nas_pdu = IE['value'][1]
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMRegistrationAccept
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMRegistrationAccept
        
    RegAcceptMsg = FGMMRegistrationAccept()
    RegAcceptMsg.from_bytes(nas_pdu[7:])
    GUTI = RegAcceptMsg['GUTI']['5GSID']
    ue_5g_guti = FGGUTI(GUTI['PLMN'], GUTI['AMFRegionID'], GUTI['AMFSetID'],GUTI['AMFPtr'], GUTI['5GTMSI'])
    return ue_5g_guti

def InitialContextSetupResponseMessage(amf_ue_ngap_id, ran_ue_ngap_id=1):
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    val = ('successfulOutcome', {'procedureCode': 14, 'criticality': 'ignore', 'value': ('InitialContextSetupResponse', {'protocolIEs': IEs})})
    return val

def RegistrationCompleteMessage(amf_ue_ngap_id, k_nas_int, k_nas_enc, plmn_bcd, ran_ue_ngap_id=1, tac="000001", ciphAlgo=0, ntegAlgo=2):
    # Use the helper functions for cleaner implementation
    regCompleteMsg = fgmm_registration_complete_message()
    secProtNasMsg = fgmm_security_protected_nas_message(ciphAlgo, ntegAlgo, k_nas_enc, k_nas_int, regCompleteMsg)
    nas_encoded = secProtNasMsg.hex()
    
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', bytes.fromhex(nas_encoded))})
    IEs.append({'id': 121, 'criticality': 'reject', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (1, 36)}}))})

    val = ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore', 'value': ('UplinkNASTransport', {'protocolIEs': IEs})})
    return val

def PDUSessionEstablishmentRequestMessage(amf_ue_ngap_id, k_nas_int, k_nas_enc, plmn_bcd, slices, dnn, ran_ue_ngap_id=1, tac="000001", ciphAlgo=0, ntegAlgo=2, gnb_id=1):
    # Use the helper functions for cleaner implementation following original pattern
    pduSessEstablishmentReq = fgsm_pdu_session_establishment_request_message()
    ulNasTransportMsg = fgmm_ul_nas_transport_message(pduSessEstablishmentReq, dnn=dnn, snssai=slices)
    secProtNasMsg = fgmm_security_protected_nas_message(ciphAlgo, ntegAlgo, k_nas_enc, k_nas_int, ulNasTransportMsg, is_pdu=True)
    
    nas_encoded = secProtNasMsg.hex()
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 38, 'criticality': 'reject', 'value': ('NAS-PDU', bytes.fromhex(nas_encoded))})
    IEs.append({'id': 121, 'criticality': 'reject', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (gnb_id, 36)}}))})

    val = ('initiatingMessage', {'procedureCode': 46, 'criticality': 'ignore', 'value': ('UplinkNASTransport', {'protocolIEs': IEs})})
    return val

def PDUSessionResourceSetupRequestMessage(pdu_dict):
    PDUSessionResourceSetupListSUReq = None
    for IE in pdu_dict['value'][1]['protocolIEs']:
        if IE['value'][0] == 'PDUSessionResourceSetupListSUReq':
            PDUSessionResourceSetupListSUReq = IE['value'][1]
            break
    if PDUSessionResourceSetupListSUReq is None:
        return None, None, None, None, None, None
        
    PDUSessID = PDUSessionResourceSetupListSUReq[0]['pDUSessionID']
    pDUSessionNAS_PDU = PDUSessionResourceSetupListSUReq[0]['pDUSessionNAS-PDU'][7:]
    
    try:
        from pycrate_mobile.TS24501_FGMM import FGMMDLNASTransport
        from pycrate_mobile.TS24501_FGSM import FGSMPDUSessionEstabAccept
    except ImportError:
        from pycrate_mobile.TS24501_IE import FGMMDLNASTransport, FGSMPDUSessionEstabAccept
        
    DLNasTransport = FGMMDLNASTransport()
    DLNasTransport.from_bytes(pDUSessionNAS_PDU)
    PDUSessEstabAccept = FGSMPDUSessionEstabAccept()
    PDUSessEstabAccept.from_bytes(DLNasTransport['PayloadContainer']['V'].get_val())
    PDUAddress = PDUSessEstabAccept['PDUAddress']['PDUAddress']['Addr'].get_val()
    
    # Fix SNSSAI handling to properly handle cases where SD may not exist
    SNSSAI_field = PDUSessEstabAccept['SNSSAI']['SNSSAI']
    snssai_dict = {'SST': SNSSAI_field['SST'].get_val()}
    if 'SD' in SNSSAI_field:
        snssai_dict['SD'] = SNSSAI_field['SD'].get_val()
    else:
        snssai_dict['SD'] = None  # or omit if not needed
    
    DNN = PDUSessEstabAccept['DNN']['DNN'].get_val()[0][1]
    
    oct1, oct2, oct3, oct4 = struct.unpack('!BBBB', PDUAddress)
    ipv4_str = f'{oct1}.{oct2}.{oct3}.{oct4}'
    
    PDUSessionResourceSetupRequestTransfer = PDUSessionResourceSetupListSUReq[0]['pDUSessionResourceSetupRequestTransfer'][1]['protocolIEs']
    ie_139 = next(ie for ie in PDUSessionResourceSetupRequestTransfer if ie['id'] == 139)
    gTP_TEID = ie_139['value'][1][1]['gTP-TEID']
    ie_136 = next(ie for ie in PDUSessionResourceSetupRequestTransfer if ie['id'] == 136)
    qosFlowIdentifier = ie_136['value'][1][0]['qosFlowIdentifier']
    return ipv4_str, gTP_TEID, qosFlowIdentifier, snssai_dict, DNN, PDUSessID

def PDUSessResourceSetupResponseMessage(amf_ue_ngap_id, qosFlowIdentifier, plmn_bcd, gnb_ip="192.168.55.9", gnb_teid=2, ran_ue_ngap_id=1, tac="000001"):
    ip_obj = ipaddress.ip_address(gnb_ip)
    IEs = []
    IEs.append({'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 75, 'criticality': 'ignore', 'value':   ('PDUSessionResourceSetupListSURes', [{'pDUSessionID': 1, 'pDUSessionResourceSetupResponseTransfer': bytes.fromhex(f'0003e0{ip_obj.packed.hex()}{int_to_hex8(2)}{int_to_hex4(qosFlowIdentifier)}')}])})

    val = ('successfulOutcome', {'procedureCode': 29, 'criticality': 'reject', 'value': ('PDUSessionResourceSetupResponse', {'protocolIEs': IEs})})
    return val 

def UEContextReleaseRequestMessage(amf_ue_ngap_id, ran_ue_ngap_id, pdu_session_id=None):
    IEs = []
    IEs.append({'id': 10, 'criticality': 'reject', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'reject', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 133, 'criticality': 'reject', 'value': ('PDUSessionResourceListCxtRelReq', [{'pDUSessionID': 1}, {'pDUSessionID': 2}])})
    IEs.append({'id': 15, 'criticality': 'ignore', 'value': ('Cause', ('radioNetwork', 'user-inactivity'))})
    val = ('initiatingMessage', {'procedureCode': 42, 'criticality': 'ignore', 'value': ('UEContextReleaseRequest', {'protocolIEs': IEs})})
    return val

def UEContextReleaseCommandMessage(pdu_dict):
    protocolIEs = pdu_dict['value'][1]['protocolIEs']
    
    for ie in protocolIEs:
        if ie['id'] == 114 and ie['value'][0] == 'UE-NGAP-IDs':
            if ie['value'][1][0] == 'uE-NGAP-ID-pair':
                ue_ngap_id_pair = ie['value'][1][1]
                amf_ue_ngap_id = ue_ngap_id_pair['aMF-UE-NGAP-ID']
                ran_ue_ngap_id = ue_ngap_id_pair['rAN-UE-NGAP-ID'] 
                return amf_ue_ngap_id, ran_ue_ngap_id
    return None, None

def UEContextReleaseCompleteMessage(amf_ue_ngap_id, ran_ue_ngap_id, plmn_bcd, tac, gnb_id):
    IEs = []
    IEs.append({'id': 10, 'criticality': 'ignore', 'value': ('AMF-UE-NGAP-ID', amf_ue_ngap_id)})
    IEs.append({'id': 85, 'criticality': 'ignore', 'value': ('RAN-UE-NGAP-ID', ran_ue_ngap_id)})
    IEs.append({'id': 121, 'criticality': 'ignore', 'value': ('UserLocationInformation', ('userLocationInformationNR', {'tAI': {'pLMNIdentity': plmn_bcd, 'tAC': bytes.fromhex(tac)},'nR-CGI': {'pLMNIdentity': plmn_bcd, 'nRCellIdentity': (gnb_id, 36)}}))})
    IEs.append({'id': 60, 'criticality': 'reject', 'value': ('PDUSessionResourceListCxtRelCpl', [{'pDUSessionID': 1}, {'pDUSessionID': 2}])})
    val = ('successfulOutcome', {'procedureCode': 41, 'criticality': 'reject', 'value': ('UEContextReleaseComplete', {'protocolIEs': IEs})})
    return val

def ConfigurationUpdateMessage(pdu_dict):
    pass