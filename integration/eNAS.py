#!/usr/bin/env python3
"""
NAS (Non-Access Stratum) encoding and decoding functions for 4G LTE.

This module provides NAS message encoding and decoding functionality
following 3GPP 24.301 specification.
"""

import struct
import socket


def nas_encode(nas_list):
    """
    Encode a NAS message from a structured list of information elements.
    
    Args:
        nas_list: List of NAS information elements in format:
            - First element: (protocol_discriminator, security_header)
            - Other elements: (iei, format, value) where format can be
              'V', 'TV', 'LV', 'LV-E', 'TLV', 'TLV-E'
        
    Returns:
        Encoded NAS message bytes
    """
    nas = b''

    # First element: protocol discriminator and security header
    protocol_discriminator = nas_list[0][0]
    security_header = nas_list[0][1]
    nas += bytes([(security_header << 4) + protocol_discriminator])

    # Process remaining elements
    for i in range(1, len(nas_list)):
        iei = nas_list[i][0]
        fmt = nas_list[i][1]
        value = nas_list[i][2]

        if iei == 0:
            # Elements with IEI = 0 use different formats
            if fmt == 'V':
                nas += value
            elif fmt == 'LV':
                nas += bytes([len(value)]) + value
            elif fmt == 'LV-E':
                nas += bytes([len(value) // 256]) + bytes([len(value) % 256]) + value
        else:
            if fmt == 'TV':
                if iei < 16:
                    nas += bytes([(iei << 4) + value])
                else:
                    if isinstance(value, int):
                        nas += bytes([iei, value])
                    else:
                        nas += bytes([iei]) + value
            elif fmt == 'TLV':
                nas += bytes([iei]) + bytes([len(value)]) + value
            elif fmt == 'TLV-E':
                nas += bytes([iei]) + bytes([len(value) // 256]) + bytes([len(value) % 256]) + value

    return nas


def nas_decode(nas):
    """
    Decode a NAS message into a structured list.
    
    Args:
        nas: Raw NAS message bytes
        
    Returns:
        List of tuples describing the parsed NAS message fields
    """
    nas_list = []
    if nas is None or len(nas) < 2:
        return nas_list

    protocol_discriminator = nas[0] % 16
    nas_list.append(('protocol discriminator', protocol_discriminator))

    if protocol_discriminator == 7:  # EMM
        security_header = nas[0] // 16
        nas_list.append(('security header', security_header))
        if security_header == 0:  # plain NAS
            nas_list.append(('message type', nas[1]))
            if len(nas) > 2:
                nas_list += nas_decode_emm(nas[1], nas[2:])
        else:
            # Security-protected NAS: MAC (4 bytes) + SQN (1 byte) + encrypted NAS
            if len(nas) >= 6:
                nas_list.append(('message authentication code', nas[1:5]))
                nas_list.append(('sequence_number', nas[5]))
                nas_list.append(('nas message encrypted', nas[6:]))
            else:
                nas_list.append(('security protected short', nas[1:]))

    elif protocol_discriminator == 2:  # ESM
        eps_bearer_identity = nas[0] // 16
        nas_list.append(('eps bearer identity', eps_bearer_identity))
        nas_list.append(('procedure transaction identity', nas[1]))
        nas_list.append(('message type', nas[2]))
        if len(nas) > 3:
            nas_list += nas_decode_esm(nas[2], nas[3:])

    return nas_list


def nas_decode_emm(message_type, ies):
    """Dispatch EMM message decoding based on message type."""
    if message_type == 66:   # Attach Accept
        return _decode_attach_accept(ies)
    elif message_type == 68: # Attach Reject
        return [('emm cause', ies[0] if len(ies) > 0 else None)]
    elif message_type == 82: # Authentication Request
        return _decode_authentication_request(ies)
    elif message_type == 84: # Authentication Reject
        return []
    elif message_type == 85: # Identity Request
        return _decode_identity_request(ies)
    elif message_type == 93: # Security Mode Command
        return _decode_security_mode_command(ies)
    elif message_type == 69: # Detach Request
        return [('detach type', ies[0] % 16 if len(ies) > 0 else None)]
    elif message_type == 70: # Detach Accept
        return []
    elif message_type == 73: # TAU Accept
        return _decode_tau_accept(ies)
    elif message_type == 80: # GUTI Reallocation Command
        return _decode_guti_reallocation_command(ies)
    elif message_type == 96: # EMM Status
        return [('emm cause', ies[0] if len(ies) > 0 else None)]
    elif message_type == 97: # EMM Information
        return []
    elif message_type == 98: # Downlink NAS Transport
        return _decode_downlink_nas_transport(ies)
    elif message_type == 193: # Activate Default EPS Bearer Context Request (ESM inside EMM container)
        return nas_decode_esm(message_type, ies)
    else:
        return [('unknown emm message type', message_type)]


def nas_decode_esm(message_type, ies):
    """Dispatch ESM message decoding based on message type."""
    if message_type == 193:  # Activate Default EPS Bearer Context Request
        return _decode_activate_default_eps_bearer(ies)
    elif message_type == 194: # Activate Default EPS Bearer Context Accept
        return [('esm message type', 'activate default eps bearer accept')]
    elif message_type == 197: # Activate Dedicated EPS Bearer Context Request
        return _decode_activate_dedicated_eps_bearer(ies)
    elif message_type == 201: # Modify EPS Bearer Context Request
        return [('esm message type', 'modify eps bearer context request')]
    elif message_type == 205: # Deactivate EPS Bearer Context Request
        return [('esm message type', 'deactivate eps bearer context request')]
    elif message_type == 208: # PDN Connectivity Accept (or Request)
        return _decode_pdn_connectivity_accept(ies)
    elif message_type == 209: # PDN Connectivity Reject
        return [('esm message type', 'pdn connectivity reject')]
    elif message_type == 217: # ESM Information Request
        return [('esm message type', 'esm information request')]
    else:
        return [('unknown esm message type', message_type)]


# ---------------------------------------------------------------------------
# EMM Decoders
# ---------------------------------------------------------------------------

def _decode_authentication_request(ies):
    """
    Decode Authentication Request (message type 82).
    Per 3GPP TS 24.301 Table 8.2.7:
      - NAS key set identifier (1 byte: KSI in high nibble, spare in low nibble)
      - RAND (V type, fixed 16 bytes, NO length prefix)
      - AUTN (V type, fixed 16 bytes, NO length prefix)
    """
    result = []
    pos = 0
    if len(ies) > pos:
        ksi = (ies[pos] >> 4) & 0x0F
        result.append(('nas key set identifier', ksi))
        pos += 1
    # RAND: fixed 16 bytes (V type per 3GPP 24.301)
    if len(ies) >= pos + 16:
        result.append(('rand', ies[pos:pos + 16]))
        pos += 16
    # AUTN: fixed 16 bytes (V type per 3GPP 24.301)
    if len(ies) >= pos + 16:
        auth_length = ies[pos + 1]
        result.append(('autn', ies[pos+1:pos + 1 + auth_length]))
        pos += 16
    return result


def _decode_security_mode_command(ies):
    """
    Decode Security Mode Command (message type 93).
    Layout after message type byte:
      - Selected NAS security algorithms (1 byte: enc_algo high nibble, int_algo low nibble)
      - NAS key set identifier (1 byte, half-octet)
      - Replayed UE security capabilities (LV)
      - Optional IEs (IMEISV request, etc.)
    """
    result = []
    pos = 0
    if len(ies) > pos:
        result.append(('selected nas security algorithms', ies[pos]))
        pos += 1
    if len(ies) > pos:
        ksi = (ies[pos] >> 4) & 0x0F
        result.append(('nas key set identifier', ksi))
        pos += 1
    if len(ies) > pos:
        cap_len = ies[pos]
        pos += 1
        result.append(('ue security capabilities', ies[pos:pos + cap_len]))
        pos += cap_len
    # Optional IEs (matching eNB reference for SMC optional field handling)
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x55:  # Replayed nonce UE (TLV, 4 bytes value)
            result.append(('replayed nonce ue', ies[pos + 1:pos + 5]))
            pos += 5
        elif iei == 0x56:  # Nonce MME (TLV, 4 bytes value)
            result.append(('nonce mme', ies[pos + 1:pos + 5]))
            pos += 5
        elif iei // 16 == 0xC:  # IMEISV request (TV, 1 byte: IEI=0xC in high nibble, value in low nibble)
            result.append(('imeisv request', iei % 16))
            pos += 1
        elif iei == 0x4F:  # Hash MME (TLV: 1 byte IEI + 1 byte length + data)
            hash_mme_length = ies[pos + 1]
            hash_mme = ies[pos + 2:pos + 2 + hash_mme_length]
            result.append(('hash mme', hash_mme))
            pos += 2 + hash_mme_length
        elif iei == 0x6F:  # Replayed UE additional security capability (TLV)
            cap_length = ies[pos + 1]
            cap_data = ies[pos + 2:pos + 2 + cap_length]
            result.append(('replayed ue additional security capability', cap_data))
            pos += 2 + cap_length
        else:
            # Unknown IE – stop parsing
            break
    return result


def _decode_attach_accept(ies):
    """
    Decode Attach Accept (message type 66).
    Layout after message type byte:
      - EPS attach result (1 byte, low nibble)
      - T3412 value (1 byte)
      - TAI list (LV: 1-byte length + data)
      - ESM message container (LV-E: 2-byte length + ESM NAS message)
      - Optional IEs: GUTI (0x50), Location Area ID (0x13), MS Identity (0x23), etc.
    """
    result = []
    pos = 0
    if len(ies) > pos:
        result.append(('eps attach result', ies[pos] % 16))
        pos += 1
    if len(ies) > pos:
        result.append(('t3412 value', ies[pos]))
        pos += 1
    if len(ies) > pos:
        tai_len = ies[pos]
        pos += 1
        result.append(('tai list', ies[pos:pos + tai_len]))
        pos += tai_len
    # ESM message container (2-byte length)
    if len(ies) > pos + 1:
        esm_len = ies[pos] * 256 + ies[pos + 1]
        pos += 2
        esm_container = ies[pos:pos + esm_len]
        result.append(('esm message container', nas_decode(esm_container)))
        pos += esm_len
    # Optional IEs
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x50:  # GUTI
            pos += 1
            if pos < len(ies):
                guti_len = ies[pos]
                pos += 1
                result.append(('guti', ies[pos:pos + guti_len]))
                pos += guti_len
        elif iei == 0x13:  # Location Area Identification
            result.append(('location area identification', ies[pos + 1:pos + 6]))
            pos += 6
        elif iei == 0x23:  # MS Identity
            pos += 1
            if pos < len(ies):
                ms_len = ies[pos]
                pos += 1
                result.append(('ms identity', ies[pos:pos + ms_len]))
                pos += ms_len
        elif iei == 0x53:  # EMM Cause
            pos += 1
            result.append(('emm cause', ies[pos] if pos < len(ies) else None))
            pos += 1
        elif iei == 0x4A:  # Equivalent PLMNs
            pos += 1
            if pos < len(ies):
                eplmn_len = ies[pos]
                pos += 1
                result.append(('equivalent plmns', ies[pos:pos + eplmn_len]))
                pos += eplmn_len
        elif iei == 0x34:  # Emergency Number List
            pos += 1
            if pos < len(ies):
                enr_len = ies[pos]
                pos += 1
                result.append(('emergency number list', ies[pos:pos + enr_len]))
                pos += enr_len
        elif iei == 0x64:  # EPS Network Feature Support
            pos += 1
            if pos < len(ies):
                enf_len = ies[pos]
                pos += 1
                result.append(('eps network feature support', ies[pos:pos + enf_len]))
                pos += enf_len
        elif iei == 0x5E:  # T3412 Extended Value
            pos += 1
            if pos < len(ies):
                t_len = ies[pos]
                pos += 1
                result.append(('t3412 extended value', ies[pos:pos + t_len]))
                pos += t_len
        elif iei == 0x6A:  # T3324 Value
            pos += 1
            if pos < len(ies):
                t_len = ies[pos]
                pos += 1
                result.append(('t3324 value', ies[pos:pos + t_len]))
                pos += t_len
        elif iei == 0x6E:  # Extended DRX Parameters
            pos += 1
            if pos < len(ies):
                t_len = ies[pos]
                pos += 1
                result.append(('extended drx parameters', ies[pos:pos + t_len]))
                pos += t_len
        elif iei // 16 == 0xF:  # Additional update result (1-byte TV)
            result.append(('additional update result', ies[pos]))
            pos += 1
        elif iei // 16 == 0xE:  # SMS service status (1-byte TV)
            result.append(('sms service status', ies[pos]))
            pos += 1
        elif iei // 16 == 0xC:  # Network policy (1-byte TV)
            result.append(('network policy', ies[pos]))
            pos += 1
        else:
            # Unknown IEI - try to skip safely
            break
    return result


def _decode_identity_request(ies):
    """Decode Identity Request (message type 85). Contains identity type (1 byte, low nibble)."""
    result = []
    if len(ies) > 0:
        result.append(('identity type', ies[0] % 16))
    return result


def _decode_tau_accept(ies):
    """Decode Tracking Area Update Accept (message type 73)."""
    result = []
    pos = 0
    if len(ies) > pos:
        result.append(('eps update result', ies[pos] % 16))
        pos += 1
    if len(ies) > pos:
        result.append(('t3412 value', ies[pos]))
        pos += 1
    # Optional IEs similar to attach accept
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x50:  # GUTI
            pos += 1
            if pos < len(ies):
                guti_len = ies[pos]
                pos += 1
                result.append(('guti', ies[pos:pos + guti_len]))
                pos += guti_len
        elif iei == 0x23:  # MS Identity
            pos += 1
            if pos < len(ies):
                ms_len = ies[pos]
                pos += 1
                result.append(('ms identity', ies[pos:pos + ms_len]))
                pos += ms_len
        elif iei == 0x13:  # Location Area Identification
            result.append(('location area identification', ies[pos + 1:pos + 6]))
            pos += 6
        else:
            break
    return result


def _decode_guti_reallocation_command(ies):
    """Decode GUTI Reallocation Command (message type 80)."""
    result = []
    pos = 0
    if len(ies) > pos:
        # GUTI is the first mandatory IE (LV format)
        guti_len = ies[pos]
        pos += 1
        result.append(('guti', ies[pos:pos + guti_len]))
        pos += guti_len
    if len(ies) > pos:
        result.append(('tai list', ies[pos:]))
    return result


def _decode_downlink_nas_transport(ies):
    """Decode Downlink NAS Transport (message type 98)."""
    result = []
    pos = 0
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x78:  # NAS Message Container (TLV-E)
            pos += 1
            if pos + 1 < len(ies):
                container_len = ies[pos] * 256 + ies[pos + 1]
                pos += 2
                result.append(('nas message container', ies[pos:pos + container_len]))
                pos += container_len
        else:
            break
    return result


# ---------------------------------------------------------------------------
# ESM Decoders
# ---------------------------------------------------------------------------

def _decode_activate_default_eps_bearer(ies):
    """
    Decode Activate Default EPS Bearer Context Request (message type 193).
    Per 3GPP TS 24.301 section 8.3.6 and eNB reference:
      - 3 mandatory IEs are positional (LV, no IEI byte): EPS QoS, APN, PDN Address
      - Optional IEs use IEI-based matching
    """
    result = []
    pos = 0

    # --- Mandatory IEs (positional, no IEI byte) ---
    # 1) EPS QoS (LV: length + data)
    if pos < len(ies):
        eps_qos_length = ies[pos]
        result.append(('eps qos', ies[pos + 1:pos + 1 + eps_qos_length]))
        pos = pos + 1 + eps_qos_length

    # 2) Access Point Name (LV: length + data)
    if pos < len(ies):
        apn_length = ies[pos]
        result.append(('access point name', ies[pos + 1:pos + 1 + apn_length]))
        pos = pos + 1 + apn_length

    # 3) PDN Address (LV: length + data)
    if pos < len(ies):
        pdn_length = ies[pos]
        result.append(('pdn address', ies[pos + 1:pos + 1 + pdn_length]))
        pos = pos + 1 + pdn_length

    # --- Optional IEs (IEI-based) ---
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x5D:  # Transaction Identifier (TLV)
            tl = ies[pos + 1]
            result.append(('transaction identifier', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x30:  # Negotiated QoS (TLV)
            tl = ies[pos + 1]
            result.append(('negotiated qos', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x34:  # Packet Flow Identifier (TLV)
            tl = ies[pos + 1]
            result.append(('packet flow identifier', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x5E:  # APN-AMBR (TLV)
            tl = ies[pos + 1]
            result.append(('apn-ambr', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x27:  # Protocol Configuration Options (TLV)
            tl = ies[pos + 1]
            result.append(('protocol configuration options', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x32:  # Negotiated LLC SAPI (TLV)
            tl = ies[pos + 1]
            result.append(('negotiated llc sapi', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x58:  # ESM Cause (TLV)
            tl = ies[pos + 1]
            result.append(('esm cause', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei // 16 == 0x8:  # Radio Priority (TV, 1 byte)
            result.append(('radio priority', ies[pos]))
            pos += 1
        elif iei // 16 == 0xB:  # Connectivity Type (TV, 1 byte)
            result.append(('connectivity type', ies[pos] % 16))
            pos += 1
        elif iei // 16 == 0xC:  # WLAN Offload Indication (TV, 1 byte)
            result.append(('wlan offload indication', ies[pos]))
            pos += 1
        elif iei // 16 == 0x9:  # Control Plane Only Indication (TV, 1 byte)
            result.append(('control plane only indication', ies[pos]))
            pos += 1
        elif iei == 0x7B:  # Extended Protocol Configuration Options (TLV-E, 2-byte length)
            tl = ies[pos + 1] * 256 + ies[pos + 2]
            result.append(('extended protocol configuration options', ies[pos + 3:pos + 3 + tl]))
            pos = pos + 3 + tl
        elif iei == 0x6E:  # Serving PLMN Rate Control (TLV)
            tl = ies[pos + 1]
            result.append(('serving plmn rate control', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x5F:  # Extended APN-AMBR (TLV)
            tl = ies[pos + 1]
            result.append(('extended apn-ambr', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        elif iei == 0x5C:  # Extended EPS QoS (TLV)
            tl = ies[pos + 1]
            result.append(('extended eps qos', ies[pos + 2:pos + 2 + tl]))
            pos = pos + 2 + tl
        else:
            break  # Unknown IEI, stop parsing
    return result


def _decode_activate_dedicated_eps_bearer(ies):
    """Decode Activate Dedicated EPS Bearer Context Request (message type 197)."""
    result = []
    result.append(('esm message type', 'activate dedicated eps bearer context request'))
    return result


def _decode_pdn_connectivity_accept(ies):
    """Decode PDN Connectivity Accept / Request (message type 208)."""
    result = []
    pos = 0
    while pos < len(ies):
        iei = ies[pos]
        if iei == 0x28:  # Access Point Name
            pos += 1
            if pos < len(ies):
                apn_len = ies[pos]
                pos += 1
                result.append(('access point name', ies[pos:pos + apn_len]))
                pos += apn_len
        elif iei == 0x27:  # Protocol Configuration Options
            pos += 1
            if pos < len(ies):
                pco_len = ies[pos]
                pos += 1
                result.append(('protocol configuration options', ies[pos:pos + pco_len]))
                pos += pco_len
        else:
            pos += 1
    return result


# ---------------------------------------------------------------------------
# Utility Decoders
# ---------------------------------------------------------------------------

def decode_pdn_address(iei):
    """
    Decode PDN address IE.
    
    Args:
        iei: PDN address bytes (first byte is PDN type in low nibble)
        
    Returns:
        List of tuples: [('pdn type value', int), ('ipv4', str)] and/or [('ipv6', str)]
    """
    result = []
    if len(iei) < 1:
        return result
    pdn_type = iei[0] % 8
    result.append(('pdn type value', pdn_type))
    if pdn_type == 1 and len(iei) >= 5:  # IPv4
        result.append(('ipv4', socket.inet_ntop(socket.AF_INET, iei[1:5])))
    elif pdn_type == 2 and len(iei) >= 9:  # IPv6
        result.append(('ipv6', socket.inet_ntop(socket.AF_INET6, iei[1:9] + 8 * b'\x00')))
    elif pdn_type == 3 and len(iei) >= 13:  # IPv4v6
        result.append(('ipv6', socket.inet_ntop(socket.AF_INET6, iei[1:9] + 8 * b'\x00')))
        result.append(('ipv4', socket.inet_ntop(socket.AF_INET, iei[9:13])))
    return result


def decode_apn(byte_array):
    """
    Decode APN from DNS-format bytes.
    
    Args:
        byte_array: APN encoded as DNS labels (length-prefixed)
        
    Returns:
        List with single tuple: [('apn', 'decoded.apn.string')]
    """
    parts = []
    pos = 0
    while pos < len(byte_array):
        label_len = byte_array[pos]
        if label_len == 0:
            break
        pos += 1
        parts.append(byte_array[pos:pos + label_len].decode('ascii', errors='replace'))
        pos += label_len
    return [('apn', '.'.join(parts))]


def decode_eps_mobile_identity(iei):
    """
    Decode EPS mobile identity IE.
    
    Args:
        iei: Mobile identity bytes
        
    Returns:
        List of tuples with identity fields
    """
    result = []
    if len(iei) < 1:
        return result

    type_of_identity = iei[0] % 8
    result.append(('type of identity', type_of_identity))

    if type_of_identity in (1, 3):  # IMSI or IMEI
        odd_even_indicator = (iei[0] % 16) >> 3
        digits = str(iei[0] // 16)
        for i in range(1, len(iei)):
            digits += str(iei[i] % 16) + str(iei[i] // 16)
        if odd_even_indicator == 0:
            digits = digits[:-1]
        result.append(('digits', digits))

    elif type_of_identity == 6:  # GUTI
        result.append(('mcc', int(str(iei[1] % 16) + str(iei[1] // 16) + str(iei[2] % 16))))
        if iei[2] // 16 == 15:  # 2-digit MNC (0xF padding)
            result.append(('mnc', int(str(iei[3] % 16) + str(iei[3] // 16))))
        else:
            result.append(('mnc', int(str(iei[3] % 16) + str(iei[3] // 16) + str(iei[2] // 16))))
        if len(iei) >= 11:
            result.append(('mme group id', 256 * iei[4] + iei[5]))
            result.append(('mme code', iei[6]))
            result.append(('m-tmsi', struct.unpack('!I', iei[7:11])[0]))
            result.append(('s-tmsi', iei[6:11]))
    return result


def encode_imsi(imsi):
    """
    Encode IMSI in BCD format for NAS messages.
    
    Format: first byte = digit1 + 0x9 (odd indicator), then pairs of digits swapped.
    
    Args:
        imsi: IMSI string (15 digits)
        
    Returns:
        BCD encoded IMSI bytes
    """
    imsi = str(imsi)
    from binascii import unhexlify
    aux = unhexlify(imsi[0] + '9')
    for i in range(1, 15, 2):
        aux += unhexlify(imsi[i + 1] + imsi[i])
    return aux


def encode_imei(imei):
    """
    Encode IMEI/IMEISV in BCD format for NAS messages.
    
    Args:
        imei: IMEI or IMEISV string
        
    Returns:
        BCD encoded IMEI bytes
    """
    from binascii import unhexlify
    imei = str(imei)
    if len(imei) % 2 == 0:
        imei += 'f'
        aux = unhexlify(imei[0] + '3')
    else:
        aux = unhexlify(imei[0] + 'b')
    for i in range(1, len(imei) - 1, 2):
        aux += unhexlify(imei[i + 1] + imei[i])
    return aux


def encode_guti(plmn, mme_group_id, mme_code, m_tmsi):
    """
    Encode GUTI (Globally Unique Temporary Identifier).
    
    Args:
        plmn: PLMN string (5 or 6 digits)
        mme_group_id: MME Group ID (integer)
        mme_code: MME Code (integer)
        m_tmsi: M-TMSI (integer)
        
    Returns:
        Encoded GUTI bytes (11 bytes total)
    """
    from binascii import unhexlify
    guti = b'\xf6'  # type of identity = GUTI
    plmn = str(plmn)
    if len(plmn) == 5:
        plmn += 'f'
    guti += unhexlify(plmn[1] + plmn[0] + plmn[5] + plmn[2] + plmn[4] + plmn[3])
    guti += struct.pack('!H', mme_group_id)
    guti += struct.pack('!B', mme_code)
    guti += struct.pack('!I', m_tmsi)
    return guti


def decode_imsi(bcd_imsi):
    """
    Decode BCD encoded IMSI.
    
    Args:
        bcd_imsi: BCD encoded IMSI bytes
        
    Returns:
        Decoded IMSI string
    """
    imsi = ''
    for byte in bcd_imsi:
        low_nibble = byte & 0x0F
        high_nibble = (byte >> 4) & 0x0F
        imsi += str(low_nibble) + str(high_nibble)
    # Remove padding 'f' if present
    if imsi.endswith('f'):
        imsi = imsi[:-1]
    return imsi


def bcd(chars):
    """
    BCD encode a string of hex characters.
    
    Args:
        chars: String of hex characters (e.g., '46099f')
        
    Returns:
        BCD encoded bytes
    """
    bcd_string = ''
    for i in range(len(chars) // 2):
        bcd_string += chars[1 + 2 * i] + chars[2 * i]
    return bytes(bytearray.fromhex(bcd_string))