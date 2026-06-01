#!/usr/bin/env python3
"""
Integrated 4G Messages module for LTE registration and PDN session establishment.

This module contains:
- NAS security functions (key derivation, integrity, encryption) per 3GPP 33.401
- NAS message constructors (auth response, security mode complete, attach complete, etc.)
- NAS codec wrappers (using eNAS module)
- S1AP message constructors (InitialUEMessage, UplinkNASTransport, etc.)

All implementations are written from scratch using pycrate and CryptoMobile.
"""

import sys
import os
import socket
import struct
import time
from binascii import hexlify, unhexlify

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Add pycrate and CryptoMobile to path
WORKSPACE_ROOT = '/root'
PYCRATE_PATH = os.path.join(WORKSPACE_ROOT, 'pycrate')
CRYPTOMOBILE_PATH = os.path.join(WORKSPACE_ROOT, 'CryptoMobile')

if PYCRATE_PATH not in sys.path:
    sys.path.insert(0, PYCRATE_PATH)
if CRYPTOMOBILE_PATH not in sys.path:
    sys.path.insert(0, CRYPTOMOBILE_PATH)

try:
    from pycrate_asn1dir import S1AP
    from pycrate_asn1rt.utils import *
    from CryptoMobile.CM import *
    from CryptoMobile.Milenage import Milenage
    from Crypto.Hash import HMAC
    from Crypto.Hash import SHA256
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please run: bash setup.sh")
    sys.exit(1)

# Import local eNAS module for encode/decode
from eNAS import nas_encode, nas_decode, encode_imsi, encode_imei, encode_guti, bcd
from eNAS import decode_pdn_address, decode_apn, decode_eps_mobile_identity
from integrated_messages import plmn_bcd_encode


# ============================================================================
# Utility Functions
# ============================================================================

def ip2int(addr):
    """Convert IP address string to integer."""
    return struct.unpack("!I", socket.inet_aton(addr))[0]


def return_plmn_s1ap(plmn):
    """
    Return PLMN in S1AP BCD format.
    
    Handles both 5-digit (MCC+2-digit MNC) and 6-digit (MCC+3-digit MNC) PLMN.
    """
    plmn = str(plmn)
    if len(plmn) == 5:
        chars = plmn[0] + plmn[1] + plmn[2] + 'f' + plmn[3] + plmn[4]
    elif len(plmn) == 6:
        chars = plmn[0] + plmn[1] + plmn[2] + plmn[3] + plmn[4] + plmn[5]
    else:
        raise ValueError(f"PLMN must be 5 or 6 digits, got {len(plmn)} digits: {plmn}")

    bcd_string = ""
    for i in range(len(chars) // 2):
        bcd_string += chars[1 + 2 * i] + chars[2 * i]
    return bytes(bytearray.fromhex(bcd_string))


def encode_apn(apn):
    """Encode APN in DNS label format."""
    apn_bytes = bytes()
    for word in apn.split("."):
        apn_bytes += struct.pack("!B", len(word)) + word.encode()
    return apn_bytes


# ============================================================================
# NAS Security Functions (3GPP 33.401)
# ============================================================================

def return_key(kasme, algo, key_type):
    """
    Derive NAS encryption/integrity key from KASME (3GPP 33.401 Annex A.7).
    
    Args:
        kasme: KASME root key (32 bytes)
        algo: Algorithm ID (1-3)
        key_type: 'NAS-ENC' for encryption, 'NAS-INT' for integrity
        
    Returns:
        16-byte derived key
    """
    if key_type == 'NAS-ENC':
        type_byte = '01'
    elif key_type == 'NAS-INT':
        type_byte = '02'
    else:
        type_byte = '01'

    algo_str = '0' + str(algo)
    message = unhexlify('15' + type_byte + '0001' + algo_str + '0001')
    h = HMAC.new(kasme, msg=message, digestmod=SHA256)
    return h.digest()[-16:]


def return_kasme(plmn, autn, ck, ik):
    """
    Derive KASME from CK, IK, PLMN and AUTN (3GPP 33.401 Annex A.2).
    
    Args:
        plmn: PLMN string
        autn: AUTN bytes (hex string or bytes)
        ck: Cipher Key (hex string)
        ik: Integrity Key (hex string)
        
    Returns:
        32-byte KASME
    """
    if isinstance(autn, bytes):
        sqn_xor_ak = hexlify(autn[0:6]).decode()
    else:
        sqn_xor_ak = autn[0:12]

    key = unhexlify(ck + ik)
    plmn_bytes = return_plmn_s1ap(plmn)
    message = unhexlify('10') + plmn_bytes + unhexlify('0003') + unhexlify(sqn_xor_ak) + unhexlify('0006')
    h = HMAC.new(key, msg=message, digestmod=SHA256)
    return h.digest()[-32:]


def milenage_res_ck_ik(ki, opc, rand_hex):
    """
    Compute RES, CK, IK using Milenage algorithm.
    
    Args:
        ki: Subscriber key (bytes)
        opc: OPc value (bytes)
        rand_hex: RAND value (hex string)
        
    Returns:
        Tuple of (res_hex, ck_hex, ik_hex)
    """
    rand_bytes = unhexlify(rand_hex)
    m = Milenage(16 * b'\x00')
    m.set_opc(opc)
    res, ck, ik, ak = m.f2345(ki, rand_bytes)
    return hexlify(res).decode(), hexlify(ck).decode(), hexlify(ik).decode()


def nas_encrypt_func(nas, count, direction, key, algo):
    """
    Encrypt NAS message using EEA1/EEA2/EEA3.
    
    Args:
        nas: Plain NAS bytes
        count: Sequence counter
        direction: 0=uplink, 1=downlink
        key: Encryption key (16 bytes), None for algo 0
        algo: Algorithm (0=null, 1=EEA1, 2=EEA2, 3=EEA3)
        
    Returns:
        Encrypted NAS bytes (or original if algo=0)
    """
    if algo == 0 or key is None:
        return nas
    elif algo == 1:
        return EEA1(key, count, 0, direction, nas)
    elif algo == 2:
        return EEA2(key, count, 0, direction, nas)
    elif algo == 3:
        return EEA3(key, count, 0, direction, nas)
    return nas


def nas_hash_func(nas, count, direction, key, algo):
    """
    Compute NAS integrity MAC using EIA1/EIA2/EIA3.
    
    Args:
        nas: NAS message bytes (after encryption)
        count: Sequence counter
        direction: 0=uplink, 1=downlink
        key: Integrity key (16 bytes), None for algo 0
        algo: Algorithm (0=null, 1=EIA1, 2=EIA2, 3=EIA3)
        
    Returns:
        4-byte MAC
    """
    sqn = bytes([count % 256])
    if algo == 0 or key is None:
        return b'\x00\x00\x00\x00'
    elif algo == 1:
        return EIA1(key, count, 0, direction, sqn + nas)
    elif algo == 2:
        return EIA2(key, count, 0, direction, sqn + nas)
    elif algo == 3:
        return EIA3(key, count, 0, direction, sqn + nas)
    return b'\x00\x00\x00\x00'


def nas_security_protected_nas_message(security_header, mac, sequence_number, nas_message):
    """
    Wrap a NAS message with security header (MAC + SQN + encrypted NAS).
    
    Args:
        security_header: Security header type (1-4)
        mac: 4-byte message authentication code
        sequence_number: 1-byte sequence number
        nas_message: Encrypted NAS message bytes
        
    Returns:
        Security-protected NAS message bytes
    """
    emm_list = []
    emm_list.append((7, security_header))
    emm_list.append((0, 'V', mac))
    emm_list.append((0, 'V', sequence_number))
    emm_list.append((0, 'V', nas_message))
    return nas_encode(emm_list)


def set_key(enc_alg, int_alg, nas_keys):
    """
    Select the active encryption and integrity keys based on algorithm selection.
    
    Args:
        enc_alg: Encryption algorithm (0-3)
        int_alg: Integrity algorithm (0-3)
        nas_keys: Dict with 'NAS-KEY-EEA1..3' and 'NAS-KEY-EIA1..3'
        
    Returns:
        Tuple of (enc_key, int_key) - each 16 bytes or None
    """
    enc_key = None
    int_key = None
    if enc_alg == 1:
        enc_key = nas_keys.get('NAS-KEY-EEA1')
    elif enc_alg == 2:
        enc_key = nas_keys.get('NAS-KEY-EEA2')
    elif enc_alg == 3:
        enc_key = nas_keys.get('NAS-KEY-EEA3')

    if int_alg == 1:
        int_key = nas_keys.get('NAS-KEY-EIA1')
    elif int_alg == 2:
        int_key = nas_keys.get('NAS-KEY-EIA2')
    elif int_alg == 3:
        int_key = nas_keys.get('NAS-KEY-EIA3')

    return enc_key, int_key


def derive_all_nas_keys(kasme):
    """
    Derive all 6 NAS keys from KASME.
    
    Returns:
        Dict with keys NAS-KEY-EEA1..3 and NAS-KEY-EIA1..3
    """
    return {
        'NAS-KEY-EEA1': return_key(kasme, 1, 'NAS-ENC'),
        'NAS-KEY-EEA2': return_key(kasme, 2, 'NAS-ENC'),
        'NAS-KEY-EEA3': return_key(kasme, 3, 'NAS-ENC'),
        'NAS-KEY-EIA1': return_key(kasme, 1, 'NAS-INT'),
        'NAS-KEY-EIA2': return_key(kasme, 2, 'NAS-INT'),
        'NAS-KEY-EIA3': return_key(kasme, 3, 'NAS-INT'),
    }


# ============================================================================
# NAS Message Constructors
# ============================================================================

def nas_attach_request(type_tuple, esm_information_transfer_flag, eps_identity,
                       pdp_type, attach_type, tmsi, lai, sms_update,
                       pcscf_restoration, pdn_request_type, ksi=0):
    """
    Create NAS Attach Request message.
    
    Args:
        type_tuple: (session_type, session_session_type) e.g. ("4G", "NONE")
        esm_information_transfer_flag: ESM info transfer flag
        eps_identity: Encoded EPS mobile identity (IMSI BCD)
        pdp_type: PDP type (1=IPv4, 2=IPv6, 3=IPv4v6)
        attach_type: Attach type (1=EPS, 2=combined, 6=emergency)
        tmsi: TMSI bytes or None
        lai: LAI bytes or None
        sms_update: SMS update flag
        pcscf_restoration: P-CSCF restoration flag
        pdn_request_type: PDN request type
        ksi: NAS Key Set Identifier (default 0)
        
    Returns:
        Encoded NAS Attach Request bytes
    """
    session_type = type_tuple[0]
    session_session_type = type_tuple[1] if len(type_tuple) > 1 else "NONE"

    emm_list = []
    emm_list.append((7, 0))  # protocol discriminator
    emm_list.append((0, 'V', bytes([65])))  # message type: attach request
    emm_list.append((0, 'V', bytes([(ksi << 4) + attach_type])))
    emm_list.append((0, 'LV', eps_identity))

    # UE network capability
    if session_type == "4G":
        emm_list.append((0, 'LV', unhexlify('f0f0c04009')))
    elif session_type == "NBIOT":
        emm_list.append((0, 'LV', unhexlify('f0f0000008a4')))
    elif session_type == "5G":
        emm_list.append((0, 'LV', unhexlify('f0f0c0c0000010')))

    pco = nas_pco(pdp_type, pcscf_restoration)
    if attach_type == 6:
        emm_list.append((0, 'LV-E', nas_pdn_connectivity(0, 1, pdp_type, None, pco, esm_information_transfer_flag, 4)))
    else:
        emm_list.append((0, 'LV-E', nas_pdn_connectivity(0, 1, pdp_type, None, pco, esm_information_transfer_flag, pdn_request_type)))

    if session_type == "4G":
        emm_list.append((0x31, 'TLV', unhexlify('65a03e')))
        if attach_type == 2 and lai is not None:
            emm_list.append((0x13, 'TV', lai))
        if attach_type == 2 and tmsi is None:
            emm_list.append((0x9, 'TV', 0))
        if sms_update:
            emm_list.append((0xF, 'TV', 1))
        emm_list.append((0xC, 'TV', 1))
        if attach_type == 2 and tmsi is not None:
            emm_list.append((0x10, 'TLV', tmsi[-3:-2] + bytes([(tmsi[-2] // 64) * 64])))
        if session_session_type in ("PSM", "BOTH"):
            emm_list.append((0x6A, 'TLV', b'\x0f'))
            emm_list.append((0x5E, 'TLV', b'\x41'))
        if session_session_type in ("EDRX", "BOTH"):
            emm_list.append((0x6E, 'TLV', b'\x75'))
    elif session_type == "NBIOT":
        if attach_type == 2 and lai is not None:
            emm_list.append((0x13, 'TV', lai))
        if attach_type == 2 and tmsi is None:
            emm_list.append((0x9, 'TV', 0))
        if sms_update:
            emm_list.append((0xF, 'TV', 5))
        else:
            emm_list.append((0xF, 'TV', 4))
        emm_list.append((0xC, 'TV', 1))
        if attach_type == 2 and tmsi is not None:
            emm_list.append((0x10, 'TLV', tmsi[-3:-2] + bytes([(tmsi[-2] // 64) * 64])))
        if session_session_type in ("PSM", "BOTH"):
            emm_list.append((0x6A, 'TLV', b'\x0f'))
            emm_list.append((0x5E, 'TLV', b'\x41'))
        if session_session_type in ("EDRX", "BOTH"):
            emm_list.append((0x6E, 'TLV', b'\x75'))
    elif session_type == "5G":
        if attach_type == 2 and lai is not None:
            emm_list.append((0x13, 'TV', lai))
        if attach_type == 2 and tmsi is None:
            emm_list.append((0x9, 'TV', 0))
        if sms_update:
            emm_list.append((0xF, 'TV', 1))
        if attach_type == 2 and tmsi is not None:
            emm_list.append((0x10, 'TLV', tmsi[-3:-2] + bytes([(tmsi[-2] // 64) * 64])))
        emm_list.append((0x6F, 'TLV', b'\xf0\x00\xf0\x00'))

    return nas_encode(emm_list)


def nas_pco(pdp_type, pcscf_restoration):
    """Create Protocol Configuration Options."""
    if pdp_type == 1:
        if not pcscf_restoration:
            return b'\x80\x80\x21\x1c\x01\x00\x00\x1c\x81\x06\x00\x00\x00\x00\x82\x06\x00\x00\x00\x00\x83\x06\x00\x00\x00\x00\x84\x06\x00\x00\x00\x00\x00\x0c\x00\x00\x0e\x00'
        else:
            return b'\x80\x80\x21\x1c\x01\x00\x00\x1c\x81\x06\x00\x00\x00\x00\x82\x06\x00\x00\x00\x00\x83\x06\x00\x00\x00\x00\x84\x06\x00\x00\x00\x00\x00\x0c\x00\x00\x12\x00\x00\x0e\x00'
    elif pdp_type == 2:
        if not pcscf_restoration:
            return b'\x80\x00\x03\x00\x00\x01\x00\x00\x0e\x00'
        else:
            return b'\x80\x00\x03\x00\x00\x01\x00\x00\x12\x00\x00\x0e\x00'
    elif pdp_type == 3:
        if not pcscf_restoration:
            return b'\x80\x80\x21\x1c\x01\x00\x00\x1c\x81\x06\x00\x00\x00\x00\x82\x06\x00\x00\x00\x00\x83\x06\x00\x00\x00\x00\x84\x06\x00\x00\x00\x00\x00\x03\x00\x00\x0c\x00\x00\x01\x00\x00\x0e\x00'
        else:
            return b'\x80\x80\x21\x1c\x01\x00\x00\x1c\x81\x06\x00\x00\x00\x00\x82\x06\x00\x00\x00\x00\x83\x06\x00\x00\x00\x00\x84\x06\x00\x00\x00\x00\x00\x03\x00\x00\x0c\x00\x00\x01\x00\x00\x12\x00\x00\x0e\x00'
    return b'\x80'


def nas_pdn_connectivity(eps_bearer_identity, pti, pdp_type, apn, pco,
                         esm_information_transfer_flag, request_type=1):
    """
    Create PDN Connectivity Request NAS message.
    
    Args:
        eps_bearer_identity: EPS bearer identity (0 for initial)
        pti: Procedure Transaction Identity
        pdp_type: PDP type (1=IPv4, 2=IPv6, 3=IPv4v6)
        apn: APN bytes or None
        pco: Protocol Configuration Options bytes or None
        esm_information_transfer_flag: ESM info transfer flag or None
        request_type: Request type (1=initial, 2=handover, 4=emergency)
        
    Returns:
        Encoded NAS PDN Connectivity Request bytes
    """
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([pti])))
    esm_list.append((0, 'V', bytes([208])))  # PDN connectivity request
    esm_list.append((0, 'V', bytes([(pdp_type << 4) + request_type])))

    if esm_information_transfer_flag is not None:
        esm_list.append((0xD, 'TV', esm_information_transfer_flag))
    if apn is not None:
        esm_list.append((0x28, 'TLV', apn))
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))

    return nas_encode(esm_list)


def nas_authentication_response(xres):
    """
    Create NAS Authentication Response.
    
    Args:
        xres: Authentication response (bytes, typically 8 bytes)
        
    Returns:
        Encoded NAS Authentication Response bytes
    """
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([83])))  # message type: authentication response
    emm_list.append((0, 'LV', xres))
    return nas_encode(emm_list)


def nas_identity_response(identity_bytes):
    """
    Create NAS Identity Response.
    
    Args:
        identity_bytes: BCD-encoded identity (IMSI or IMEISV)
        
    Returns:
        Encoded NAS Identity Response bytes
    """
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([86])))  # message type: identity response
    emm_list.append((0, 'LV', identity_bytes))
    return nas_encode(emm_list)


def nas_security_mode_complete(imeisv=None):
    """
    Create NAS Security Mode Complete.
    
    Args:
        imeisv: IMEISV string (e.g., '4370816125816151') or None
        
    Returns:
        Plain (unprotected) NAS Security Mode Complete bytes
    """
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([94])))  # message type: security mode complete
    if imeisv is not None:
        emm_list.append((0x23, 'TLV', bcd('3' + imeisv + 'f')))
    return nas_encode(emm_list)


def nas_attach_complete(eps_bearer_identity):
    """
    Create NAS Attach Complete with embedded Activate Default Bearer Accept.
    
    Args:
        eps_bearer_identity: EPS bearer identity from attach accept
        
    Returns:
        Plain (unprotected) NAS Attach Complete bytes
    """
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([67])))  # message type: attach complete
    emm_list.append((0, 'LV-E', nas_activate_default_eps_bearer_context_accept(eps_bearer_identity, None)))
    return nas_encode(emm_list)


def nas_activate_default_eps_bearer_context_accept(eps_bearer_identity, pco=None):
    """
    Create Activate Default EPS Bearer Context Accept (ESM message).
    
    Args:
        eps_bearer_identity: EPS bearer identity
        pco: Protocol Configuration Options or None
        
    Returns:
        Encoded ESM message bytes
    """
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([0])))  # PTI = 0
    esm_list.append((0, 'V', bytes([194])))  # message type
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))
    return nas_encode(esm_list)


def nas_activate_dedicated_eps_bearer_context_accept(eps_bearer_identity, pco=None):
    """Create Activate Dedicated EPS Bearer Context Accept."""
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([0])))
    esm_list.append((0, 'V', bytes([198])))
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))
    return nas_encode(esm_list)


def nas_deactivate_eps_bearer_context_accept(eps_bearer_identity, pti=0, pco=None):
    """Create Deactivate EPS Bearer Context Accept."""
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([pti])))
    esm_list.append((0, 'V', bytes([206])))
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))
    return nas_encode(esm_list)


def nas_esm_information_response(eps_bearer_identity, pti, apn, pco=None):
    """Create ESM Information Response."""
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([pti])))
    esm_list.append((0, 'V', bytes([218])))  # ESM information response
    if apn is not None:
        esm_list.append((0x28, 'TLV', apn))
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))
    return nas_encode(esm_list)


def nas_pdn_connectivity_request(eps_bearer_identity, pti, pdp_type, apn, pco=None):
    """
    Create PDN Connectivity Request for additional PDN.
    
    Args:
        eps_bearer_identity: EPS bearer identity (0)
        pti: Procedure Transaction Identity
        pdp_type: PDP type (1=IPv4)
        apn: Encoded APN bytes
        pco: Protocol Configuration Options or None
        
    Returns:
        Encoded NAS PDN Connectivity Request bytes
    """
    esm_list = []
    esm_list.append((2, eps_bearer_identity))
    esm_list.append((0, 'V', bytes([pti])))
    esm_list.append((0, 'V', bytes([208])))
    esm_list.append((0, 'V', bytes([(pdp_type << 4) + 1])))  # PDN type + initial request
    if apn is not None:
        esm_list.append((0x28, 'TLV', apn))
    if pco is not None:
        esm_list.append((0x27, 'TLV', pco))
    return nas_encode(esm_list)


def nas_detach_accept():
    """Create NAS Detach Accept."""
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([70])))
    return nas_encode(emm_list)


def nas_tracking_area_update_complete():
    """Create NAS Tracking Area Update Complete."""
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([74])))
    return nas_encode(emm_list)


def nas_guti_reallocation_complete():
    """Create NAS GUTI Reallocation Complete."""
    emm_list = []
    emm_list.append((7, 0))
    emm_list.append((0, 'V', bytes([81])))
    return nas_encode(emm_list)


# ============================================================================
# S1AP Message Constructors
# ============================================================================

def S1SetupRequest(dic):
    """Create S1 Setup Request message."""
    IEs = []
    IEs.append({'id': 59, 'value': ('Global-ENB-ID', {
        'pLMNidentity': dic['ENB-PLMN'],
        'eNB-ID': ('macroENB-ID', (dic['ENB-ID'], 20))
    }), 'criticality': 'reject'})
    IEs.append({'id': 60, 'value': ('ENBname', dic['ENB-NAME']), 'criticality': 'ignore'})

    if dic.get('S1-TYPE', "4G") == "4G":
        IEs.append({'id': 64, 'value': ('SupportedTAs', [
            {'tAC': dic['ENB-TAC1'], 'broadcastPLMNs': [dic['ENB-PLMN']]},
            {'tAC': dic['ENB-TAC2'], 'broadcastPLMNs': [dic['ENB-PLMN']]}
        ]), 'criticality': 'reject'})
    elif dic['S1-TYPE'] == "NBIOT":
        IEs.append({'id': 64, 'value': ('SupportedTAs', [
            {'tAC': dic['ENB-TAC-NBIOT'], 'broadcastPLMNs': [dic['ENB-PLMN']],
             'iE-Extensions': [{'id': 232, 'criticality': 'reject',
                                'extensionValue': ('RAT-Type', 'nbiot')}]}
        ]), 'criticality': 'reject'})
    elif dic['S1-TYPE'] == "BOTH":
        IEs.append({'id': 64, 'value': ('SupportedTAs', [
            {'tAC': dic['ENB-TAC'], 'broadcastPLMNs': [dic['ENB-PLMN']]},
            {'tAC': dic['ENB-TAC-NBIOT'], 'broadcastPLMNs': [dic['ENB-PLMN']],
             'iE-Extensions': [{'id': 232, 'criticality': 'reject',
                                'extensionValue': ('RAT-Type', 'nbiot')}]}
        ]), 'criticality': 'reject'})

    IEs.append({'id': 137, 'value': ('PagingDRX', 'v128'), 'criticality': 'ignore'})
    if dic.get('S1-TYPE') in ("NBIOT", "BOTH"):
        IEs.append({'id': 234, 'value': ('NB-IoT-DefaultPagingDRX', 'v256'), 'criticality': 'ignore'})

    return ('initiatingMessage', {
        'procedureCode': 17,
        'value': ('S1SetupRequest', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })


def S1SetupResponseProcessing(IEs, dic):
    """Process S1 Setup Response."""
    for i in IEs:
        if i['id'] == 61:
            dic['MME-NAME'] = i['value'][1]
        elif i['id'] == 105:
            dic['MME-PLMN'] = i['value'][1][0]['servedPLMNs'][0]
            dic['MME-GROUP-ID'] = i['value'][1][0]['servedGroupIDs'][0]
            dic['MME-CODE'] = i['value'][1][0]['servedMMECs'][0]
        elif i['id'] == 87:
            dic['MME-RELATIVE-CAPACITY'] = i['value'][1]
    dic['STATE'] = 1
    return dic


def InitialUEMessage(dic):
    """Create Initial UE Message."""
    IEs = []
    IEs.append({'id': 8, 'value': ('ENB-UE-S1AP-ID', dic['ENB-UE-S1AP-ID']), 'criticality': 'reject'})
    IEs.append({'id': 26, 'value': ('NAS-PDU', dic['NAS']), 'criticality': 'reject'})

    if dic.get('SESSION-TYPE', "4G") in ("4G", "5G"):
        IEs.append({'id': 67, 'value': ('TAI', {
            'pLMNidentity': dic['ENB-PLMN'], 'tAC': dic['ENB-TAC']
        }), 'criticality': 'reject'})
    elif dic.get('SESSION-TYPE') == "NBIOT":
        IEs.append({'id': 67, 'value': ('TAI', {
            'pLMNidentity': dic['ENB-PLMN'], 'tAC': dic['ENB-TAC-NBIOT']
        }), 'criticality': 'reject'})

    IEs.append({'id': 100, 'value': ('EUTRAN-CGI', {
        'cell-ID': (dic['ENB-CELLID'], 28), 'pLMNidentity': dic['ENB-PLMN']
    }), 'criticality': 'ignore'})

    if dic.get('ATTACH-TYPE', 1) == 6:
        IEs.append({'id': 134, 'value': ('RRC-Establishment-Cause', 'emergency'), 'criticality': 'ignore'})
    else:
        IEs.append({'id': 134, 'value': ('RRC-Establishment-Cause', 'mo-Signalling'), 'criticality': 'ignore'})

    if dic.get('S-TMSI') is not None:
        IEs.append({'id': 96, 'value': ('S-TMSI', {
            'mMEC': dic['S-TMSI'][0:1], 'm-TMSI': dic['S-TMSI'][1:5]
        }), 'criticality': 'reject'})

    return ('initiatingMessage', {
        'procedureCode': 12,
        'value': ('InitialUEMessage', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })


def UplinkNASTransport(dic):
    """Create Uplink NAS Transport message."""
    IEs = []
    IEs.append({'id': 0, 'value': ('MME-UE-S1AP-ID', dic['MME-UE-S1AP-ID']), 'criticality': 'reject'})
    IEs.append({'id': 8, 'value': ('ENB-UE-S1AP-ID', dic['ENB-UE-S1AP-ID']), 'criticality': 'reject'})
    IEs.append({'id': 26, 'value': ('NAS-PDU', dic['NAS']), 'criticality': 'reject'})
    IEs.append({'id': 100, 'value': ('EUTRAN-CGI', {
        'cell-ID': (dic['ENB-CELLID'], 28), 'pLMNidentity': dic['ENB-PLMN']
    }), 'criticality': 'ignore'})

    if dic.get('SESSION-TYPE', "4G") in ("4G", "5G"):
        IEs.append({'id': 67, 'value': ('TAI', {
            'pLMNidentity': dic['ENB-PLMN'], 'tAC': dic['ENB-TAC']
        }), 'criticality': 'ignore'})
    elif dic.get('SESSION-TYPE') == "NBIOT":
        IEs.append({'id': 67, 'value': ('TAI', {
            'pLMNidentity': dic['ENB-PLMN'], 'tAC': dic['ENB-TAC-NBIOT']
        }), 'criticality': 'ignore'})

    return ('initiatingMessage', {
        'procedureCode': 13,
        'value': ('UplinkNASTransport', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })


def InitialContextSetupResponse(mme_ue_s1ap_id, enb_ue_s1ap_id, erab_setup_list, enb_gtp_address_int):
    """
    Create Initial Context Setup Response.
    
    Args:
        mme_ue_s1ap_id: MME UE S1AP ID
        enb_ue_s1ap_id: ENB UE S1AP ID
        erab_setup_list: List of dicts with 'e-RAB-ID' for each E-RAB
        enb_gtp_address_int: ENB GTP address as integer
        
    Returns:
        S1AP PDU value dict
    """
    IEs = []
    IEs.append({'id': 0, 'value': ('MME-UE-S1AP-ID', mme_ue_s1ap_id), 'criticality': 'ignore'})
    IEs.append({'id': 8, 'value': ('ENB-UE-S1AP-ID', enb_ue_s1ap_id), 'criticality': 'ignore'})

    erab_items = []
    for erab in erab_setup_list:
        e_rab_id = erab['e-RAB-ID']
        erab_items.append({
            'id': 50,
            'value': ('E-RABSetupItemCtxtSURes', {
                'e-RAB-ID': e_rab_id,
                'transportLayerAddress': (enb_gtp_address_int, 32),
                'gTP-TEID': b'\x00\x00\x00' + bytes([e_rab_id])
            }),
            'criticality': 'ignore'
        })

    IEs.append({'id': 51, 'value': ('E-RABSetupListCtxtSURes', erab_items), 'criticality': 'ignore'})

    return ('successfulOutcome', {
        'procedureCode': 9,
        'value': ('InitialContextSetupResponse', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })


def ERABSetupResponse(mme_ue_s1ap_id, enb_ue_s1ap_id, erab_setup_list, enb_gtp_address_int):
    """
    Create E-RAB Setup Response.
    
    Args:
        mme_ue_s1ap_id: MME UE S1AP ID
        enb_ue_s1ap_id: ENB UE S1AP ID
        erab_setup_list: List of dicts with 'e-RAB-ID'
        enb_gtp_address_int: ENB GTP address as integer
        
    Returns:
        S1AP PDU value dict
    """
    IEs = []
    IEs.append({'id': 0, 'value': ('MME-UE-S1AP-ID', mme_ue_s1ap_id), 'criticality': 'ignore'})
    IEs.append({'id': 8, 'value': ('ENB-UE-S1AP-ID', enb_ue_s1ap_id), 'criticality': 'ignore'})

    erab_items = []
    for erab in erab_setup_list:
        e_rab_id = erab['e-RAB-ID']
        erab_items.append({
            'id': 39,
            'value': ('E-RABSetupItemBearerSURes', {
                'e-RAB-ID': e_rab_id,
                'transportLayerAddress': (enb_gtp_address_int, 32),
                'gTP-TEID': b'\x00\x00\x00' + bytes([e_rab_id])
            }),
            'criticality': 'ignore'
        })

    IEs.append({'id': 28, 'value': ('E-RABSetupListBearerSURes', erab_items), 'criticality': 'ignore'})

    return ('successfulOutcome', {
        'procedureCode': 5,
        'value': ('E-RABSetupResponse', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })


def UEContextReleaseComplete(mme_ue_s1ap_id, enb_ue_s1ap_id):
    """Create UE Context Release Complete."""
    IEs = []
    IEs.append({'id': 0, 'value': ('MME-UE-S1AP-ID', mme_ue_s1ap_id), 'criticality': 'ignore'})
    IEs.append({'id': 8, 'value': ('ENB-UE-S1AP-ID', enb_ue_s1ap_id), 'criticality': 'ignore'})
    return ('successfulOutcome', {
        'procedureCode': 23,
        'value': ('UEContextReleaseComplete', {'protocolIEs': IEs}),
        'criticality': 'ignore'
    })
