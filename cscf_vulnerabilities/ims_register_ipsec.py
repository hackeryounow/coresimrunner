#!/usr/bin/env python3
"""
IMS Registration with IPSec Security (3GPP TS 33.203 / RFC 3329)

================================================================================
网元交互流程 (Network Element Interaction Flow)
================================================================================

    UE                    P-CSCF                  I-CSCF/S-CSCF           UDM/HSS
    |                       |                         |                      |
    |--- REGISTER --------->|                         |                      |
    |    (Security-Client)  |                         |                      |
    |    port-c, port-s     |                         |                      |
    |    spi-c, spi-s       |                         |                      |
    |                       |--- REGISTER ----------->|                      |
    |                       |                         |--- SAA ------------->|
    |                       |                         |    (请求认证向量)      |
    |                       |                         |<-- SAA Answer -------|
    |                       |                         |    (RAND, AUTN,       |
    |                       |                         |     XRES, CK, IK)     |
    |                       |<-- 401 Unauthorized ----|                      |
    |<-- 401 Unauthorized --|                         |                      |
    |    (Security-Server)  |                         |                      |
    |    nonce=RAND||AUTN   |                         |                      |
    |    port-c, port-s     |                         |                      |
    |    spi-c, spi-s       |                         |                      |
    |                       |                         |                      |
    |  [UE计算AKA: RES,CK,IK]                         |                      |
    |  [建立IPSec SA]        |                         |                      |
    |                       |                         |                      |
    |--- REGISTER --------->| (via IPSec ESP)         |                      |
    |    (Security-Verify)  |                         |                      |
    |    (Authorization)    |--- REGISTER ----------->|                      |
    |                       |                         |--- MAR ------------->|
    |                       |                         |    (验证RES)          |
    |                       |                         |<-- MAA Answer -------|
    |                       |                         |    (认证成功)         |
    |                       |<-- 200 OK --------------|                      |
    |<-- 200 OK ------------| (via IPSec ESP)         |                      |
    |    (Service-Route)    |                         |                      |
    |    (P-Associated-URI) |                         |                      |
    |                       |                         |                      |

================================================================================
加解密流程 (Encryption/Decryption Flow)
================================================================================

1. 密钥生成 (Key Generation)
   -------------------------
   输入: Ki (用户密钥), OPc (运营商密钥), RAND (网络随机数)
   
   Milenage算法:
   +-------+     +-------+     +-------+     +-------+
   |  f1   |     |  f2   |     |  f3   |     |  f4   |
   +-------+     +-------+     +-------+     +-------+
      |             |             |             |
      v             v             v             v
   MAC-A          RES           CK            IK
   (验证)      (响应)      (加密密钥)    (完整性密钥)
   
   AK = f5(Ki, RAND)  -> 用于解密SQN
   SQN = AUTN[0:6] XOR AK

2. IPSec SA建立 (Security Association Setup)
   ----------------------------------------
   +------------------+     +------------------+
   |       UE         |     |      P-CSCF      |
   +------------------+     +------------------+
   |                  |     |                  |
   |  Outbound SA:    |     |  Inbound SA:     |
   |  SPI = spi-c     |<--->|  SPI = spi-c     |
   |  Key = IK (auth) |     |  Key = IK (auth) |
   |  Key = CK (enc)  |     |  Key = CK (enc)  |
   |                  |     |                  |
   |  Inbound SA:     |     |  Outbound SA:    |
   |  SPI = spi-s     |<--->|  SPI = spi-s     |
   |  Key = IK (auth) |     |  Key = IK (auth) |
   |  Key = CK (enc)  |     |  Key = CK (enc)  |
   +------------------+     +------------------+

3. ESP包处理 (ESP Packet Processing)
   --------------------------------
   发送 (UE -> P-CSCF):
   +--------+--------+--------+--------+--------+
   | IP Hdr | ESP Hdr| Payload| ESP ICV|        |
   |        | SPI,Seq| (SIP)  | (HMAC) |        |
   +--------+--------+--------+--------+--------+
            |           |          |
            |           |          +-- HMAC-MD5-96(IK, ESP Header + Payload)
            |           +------------- 加密(CK, SIP Message) [ealg!=null时]
            +------------------------- SPI标识SA

   接收 (P-CSCF -> UE):
   +--------+--------+--------+--------+
   | IP Hdr | ESP Hdr| Payload| ESP ICV|
   +--------+--------+--------+--------+
            |           |          |
            |           |          +-- 验证HMAC(IK)
            |           +------------- 解密(CK) [ealg!=null时]
            +------------------------- 查找对应SA

4. 算法映射 (Algorithm Mapping)
   ---------------------------
   +-------------------+-------------------+-------------------+
   | 3GPP Name         | XFRM Name         | Key Source        |
   +-------------------+-------------------+-------------------+
   | hmac-md5-96       | md5               | IK (16 bytes)     |
   | hmac-sha-1-96     | sha1              | IK (20 bytes pad) |
   | aes-cbc           | cbc(aes)          | CK (16 bytes)     |
   | des-ede3-cbc      | cbc(des3_ede)     | CK (24 bytes)     |
   | null              | ecb(cipher_null)  | -                 |
   +-------------------+-------------------+-------------------+

================================================================================
Security Headers 说明
================================================================================

Security-Client (UE -> P-CSCF, 初始REGISTER):
  ipsec-3gpp; alg=hmac-sha-1-96; ealg=aes-cbc; 
  spi-c=<UE_SPI>; spi-s=<UE_SPI>; port-c=<UE_PORT>; port-s=<UE_PORT>
  
  - UE声明支持的算法和参数
  - 按优先级排序

Security-Server (P-CSCF -> UE, 401响应):
  ipsec-3gpp; q=0.1; prot=esp; mod=trans;
  spi-c=<P-CSCF_SPI>; spi-s=<P-CSCF_SPI>; 
  port-c=<P-CSCF_PORT>; port-s=<P-CSCF_PORT>;
  alg=hmac-md5-96; ealg=null
  
  - P-CSCF选择的算法和参数
  - P-CSCF分配的SPI和端口

Security-Verify (UE -> P-CSCF, 认证REGISTER):
  - 完全回显Security-Server内容
  - 确认UE接受P-CSCF的参数

================================================================================
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
import uuid
import subprocess
import os

from CryptoMobile.Milenage import Milenage

# ======================== Configuration ========================
UE_IP = "172.29.0.18"
UE_PORT = 5060           # Initial SIP port (non-IPSec)
PCSCF_IP = "172.22.0.21"
PCSCF_PORT = 5060
IMSI = "460090000000001"
MSISDN = "13300000001"
IMS_DOMAIN = "ims.mnc009.mcc460.3gppnetwork.org"
IMEI = "356938035643803"

# Subscriber credentials
KI_HEX = "12341234123412341234123412340000"
OPC_HEX = "71a121bb69baf3c0cc53fb5038a0131f"

# IPSec parameters (UE side)
CONTACT_UUID = str(uuid.uuid4())
SPI_C = random.randint(0x10000000, 0xFFFFFFFF)  # SPI for UE->P-CSCF
SPI_S = random.randint(0x10000000, 0xFFFFFFFF)  # SPI for P-CSCF->UE
IPSEC_PORT_C = random.randint(40000, 50000)     # UE IPSec port (used for all SIP)
IPSEC_PORT_S = random.randint(50000, 60000)     # P-CSCF IPSec port (will be overridden)

# ======================== Milenage AKA ========================
def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, b))

def compute_aka_response(nonce_b64, ki_hex, opc_hex, username, realm, method, uri, cnonce, nc="00000001"):
    """Compute AKAv1-MD5 digest response per RFC 3310."""
    K = bytes.fromhex(ki_hex)
    OPc = bytes.fromhex(opc_hex)

    nonce_bytes = base64.b64decode(nonce_b64)
    RAND = nonce_bytes[:16]
    AUTN = nonce_bytes[16:32]

    sqn_xor_ak = AUTN[0:6]
    amf_field = AUTN[6:8]

    mil = Milenage(OPc)
    mil.set_opc(OPc)
    RES, CK, IK, AK = mil.f2345(K, RAND)
    SQN = xor_bytes(sqn_xor_ak, AK)

    mac_a = mil.f1(K, RAND, SQN=SQN, AMF=amf_field)
    mac_a_received = AUTN[8:16]
    if mac_a != mac_a_received:
        print(f"  [WARN] MAC-A mismatch!")
    else:
        print(f"  [OK] MAC-A verified: {mac_a.hex()}")

    print(f"  RAND: {RAND.hex()}")
    print(f"  RES:  {RES.hex()}")
    print(f"  CK:   {CK.hex()}")
    print(f"  IK:   {IK.hex()}")

    # HA1 = MD5(username:realm:RES_raw_bytes)
    ha1_input = f"{username}:{realm}:".encode() + RES
    ha1 = hashlib.md5(ha1_input).hexdigest()

    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    response = hashlib.md5(f"{ha1}:{nonce_b64}:{nc}:{cnonce}:auth:{ha2}".encode()).hexdigest()

    return response, RES.hex(), CK.hex(), IK.hex()

# ======================== IPSec SA Management ========================
def get_pcscf_outbound_spi(pcscf_ip, ue_ip, ue_port, pcscf_port):
    """
    Get the SPI that P-CSCF uses for outbound traffic (P-CSCF -> UE).
    The P-CSCF's ims_ipsec_pcscf module creates its own SPIs, which may
    differ from the Security-Server header.
    This function queries the P-CSCF container's XFRM state.
    
    We look for the SA with selector: sport=pcscf_port, dport=ue_port
    and the highest oseq (most recently used).
    """
    try:
        # Query P-CSCF container's XFRM state
        result = subprocess.run(
            ['docker', 'exec', 'pcscf', 'ip', 'xfrm', 'state'],
            capture_output=True, text=True, timeout=5
        )
        # Parse output to find P-CSCF's outbound SA
        # Looking for: src PCSCF_IP dst UE_IP ... sel src PCSCF_IP dst UE_IP sport PCSCF_PORT dport UE_PORT
        lines = result.stdout.split('\n')
        best_spi = None
        best_oseq = -1
        
        i = 0
        while i < len(lines):
            line = lines[i]
            if f'src {pcscf_ip} dst {ue_ip}' in line:
                # Found a P-CSCF -> UE SA, extract details
                sa_spi = None
                sa_oseq = 0
                sa_sport = None
                sa_dport = None
                
                # Parse the next few lines for this SA
                j = i + 1
                while j < len(lines) and not lines[j].startswith('src '):
                    if 'spi 0x' in lines[j]:
                        spi_match = re.search(r'spi (0x[0-9a-f]+)', lines[j])
                        if spi_match:
                            sa_spi = int(spi_match.group(1), 16)
                    if 'oseq 0x' in lines[j]:
                        oseq_match = re.search(r'oseq (0x[0-9a-f]+)', lines[j])
                        if oseq_match:
                            sa_oseq = int(oseq_match.group(1), 16)
                    if f'sel src {pcscf_ip}' in lines[j]:
                        sport_match = re.search(r'sport (\d+)', lines[j])
                        dport_match = re.search(r'dport (\d+)', lines[j])
                        if sport_match:
                            sa_sport = int(sport_match.group(1))
                        if dport_match:
                            sa_dport = int(dport_match.group(1))
                    j += 1
                
                # Check if this SA matches our criteria
                if sa_spi and sa_dport == ue_port:
                    print(f"  [DEBUG] Found P-CSCF SA: SPI=0x{sa_spi:08x}, sport={sa_sport}, dport={sa_dport}, oseq={sa_oseq}")
                    # Prefer SA with matching pcscf_port and highest oseq
                    if sa_sport == pcscf_port and sa_oseq > best_oseq:
                        best_spi = sa_spi
                        best_oseq = sa_oseq
                
                i = j
            else:
                i += 1
        
        if best_spi:
            print(f"  [DEBUG] Selected P-CSCF outbound SPI: 0x{best_spi:08x} (oseq={best_oseq})")
            return best_spi
    except Exception as e:
        print(f"  [WARN] Failed to get P-CSCF SPI: {e}")
    return None

def setup_ipsec_sa(ck_hex, ik_hex, spi_c, spi_s, ue_ip, pcscf_ip, ue_port, pcscf_port, alg, ealg):
    """
    Setup IPSec Security Associations using Linux XFRM.
    CK -> encryption key, IK -> authentication key
    ue_port: UE's source port (IPSEC_PORT_C)
    pcscf_port: P-CSCF's destination port (port-s from Security-Server)
    
    Note: The P-CSCF's ims_ipsec_pcscf module creates its own SPIs for outbound
    traffic, which may differ from the Security-Server header. We query the P-CSCF's
    XFRM state to get the actual SPI.
    """
    print(f"\n[IPSec] Setting up Security Associations...")
    print(f"  CK: {ck_hex}")
    print(f"  IK: {ik_hex}")
    print(f"  SPI_C (UE->P-CSCF): 0x{spi_c:08x}")
    print(f"  SPI_S (P-CSCF->UE): 0x{spi_s:08x}")
    print(f"  Ports: UE={ue_port}, P-CSCF={pcscf_port}")
    print(f"  Algorithms: auth={alg}, enc={ealg}")

    # Map algorithm names to XFRM names
    auth_alg_map = {
        'hmac-md5-96': 'md5',
        'hmac-sha-1-96': 'sha1',
        'hmac-sha-256-128': 'sha256',
    }
    enc_alg_map = {
        'null': 'ecb(cipher_null)',
        'des-ede3-cbc': 'cbc(des3_ede)',
        'aes-cbc': 'cbc(aes)',
    }

    auth_alg = auth_alg_map.get(alg, 'sha1')
    enc_alg = enc_alg_map.get(ealg, 'ecb(cipher_null)')

    # IK is 16 bytes, for hmac-sha-1-96 we need 20 bytes key (pad with zeros)
    ik_bytes = bytes.fromhex(ik_hex)
    if auth_alg == 'sha1':
        ik_key = ik_bytes.ljust(20, b'\x00').hex()
    else:
        ik_key = ik_hex

    # CK for encryption
    ck_bytes = bytes.fromhex(ck_hex)
    if ealg == 'des-ede3-cbc':
        # 3DES needs 24 bytes key
        ck_key = (ck_bytes + ck_bytes[:8]).hex()
    elif ealg == 'aes-cbc':
        ck_key = ck_hex  # AES-128 uses 16 bytes
    else:
        ck_key = ""

    # Flush existing SAs and policies
    subprocess.run(['ip', 'xfrm', 'state', 'flush'], capture_output=True)
    subprocess.run(['ip', 'xfrm', 'policy', 'flush'], capture_output=True)

    try:
        # SA 1: UE -> P-CSCF (outbound)
        cmd_out = [
            'ip', 'xfrm', 'state', 'add',
            'src', ue_ip, 'dst', pcscf_ip,
            'proto', 'esp', 'spi', f'0x{spi_c:08x}',
            'mode', 'transport',
            'reqid', '1',
            'auth', f'{auth_alg}', f'0x{ik_key}',
        ]
        if ealg != 'null':
            cmd_out += ['enc', f'{enc_alg}', f'0x{ck_key}']
        else:
            cmd_out += ['enc', 'ecb(cipher_null)', '']
        
        result = subprocess.run(cmd_out, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [ERROR] SA outbound: {result.stderr}")
        else:
            print(f"  [OK] SA outbound created")

        # SA 2: P-CSCF -> UE (inbound)
        # Query P-CSCF's actual outbound SPI (may differ from Security-Server)
        actual_spi_s = get_pcscf_outbound_spi(pcscf_ip, ue_ip, ue_port, pcscf_port)
        if actual_spi_s is None:
            actual_spi_s = spi_s  # Fallback to Security-Server SPI
            print(f"  [WARN] Using Security-Server SPI: 0x{actual_spi_s:08x}")
        else:
            print(f"  [OK] Using P-CSCF actual SPI: 0x{actual_spi_s:08x}")
        
        cmd_in = [
            'ip', 'xfrm', 'state', 'add',
            'src', pcscf_ip, 'dst', ue_ip,
            'proto', 'esp', 'spi', f'0x{actual_spi_s:08x}',
            'mode', 'transport',
            'reqid', '1',
            'auth', f'{auth_alg}', f'0x{ik_key}',
        ]
        if ealg != 'null':
            cmd_in += ['enc', f'{enc_alg}', f'0x{ck_key}']
        else:
            cmd_in += ['enc', 'ecb(cipher_null)', '']
        
        result = subprocess.run(cmd_in, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [ERROR] SA inbound: {result.stderr}")
        else:
            print(f"  [OK] SA inbound created")

        # Policy: UE -> P-CSCF (out)
        subprocess.run([
            'ip', 'xfrm', 'policy', 'add',
            'src', f'{ue_ip}/32', 'dst', f'{pcscf_ip}/32',
            'proto', 'udp', 'sport', str(ue_port), 'dport', str(pcscf_port),
            'dir', 'out', 'action', 'allow',
            'tmpl', 'src', ue_ip, 'dst', pcscf_ip,
            'proto', 'esp', 'reqid', '1', 'mode', 'transport'
        ], capture_output=True)

        # Policy: P-CSCF -> UE (in)
        subprocess.run([
            'ip', 'xfrm', 'policy', 'add',
            'src', f'{pcscf_ip}/32', 'dst', f'{ue_ip}/32',
            'proto', 'udp', 'sport', str(pcscf_port), 'dport', str(ue_port),
            'dir', 'in', 'action', 'allow',
            'tmpl', 'src', pcscf_ip, 'dst', ue_ip,
            'proto', 'esp', 'reqid', '1', 'mode', 'transport'
        ], capture_output=True)

        print(f"  [OK] XFRM policies created")
        return True

    except Exception as e:
        print(f"  [ERROR] IPSec setup failed: {e}")
        return False

def cleanup_ipsec():
    """Remove IPSec SAs and policies."""
    subprocess.run(['ip', 'xfrm', 'state', 'flush'], capture_output=True)
    subprocess.run(['ip', 'xfrm', 'policy', 'flush'], capture_output=True)
    print("[IPSec] Cleaned up SAs and policies")

# ======================== SIP Message Builders ========================
def rand_hex(n):
    return ''.join(random.choices(string.hexdigits[:16], k=n))

def build_security_client():
    """Build Security-Client header with supported IPSec mechanisms."""
    mechanisms = []
    # List supported mechanisms in preference order
    # Note: port-c = UE's source port, port-s = same as port-c
    # This is a workaround for P-CSCF's ims_ipsec_pcscf module which uses
    # Security-Client's port-s as the SA selector's sport
    for alg in ['hmac-sha-1-96', 'hmac-md5-96']:
        for ealg in ['aes-cbc', 'des-ede3-cbc', 'null']:
            mechanisms.append(
                f'ipsec-3gpp; alg={alg}; ealg={ealg}; '
                f'spi-c={SPI_C}; spi-s={SPI_S}; '
                f'port-c={IPSEC_PORT_C}; port-s={IPSEC_PORT_C}'
            )
    return 'Security-Client: ' + ','.join(mechanisms)

def parse_security_server(header):
    """Parse Security-Server header from 401 response."""
    params = {}
    for part in header.replace('ipsec-3gpp;', '').split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            params[k.strip()] = v.strip()
    return params

def build_initial_register(call_id, from_tag, branch, cseq):
    """Build initial REGISTER with Security-Client."""
    sec_client = build_security_client()
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
        f"User-Agent: CoreSimRunner-VoNR-IPSec/1.0\r\n"
        f"{sec_client}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

def build_auth_register(call_id, from_tag, branch, cseq, nonce, realm,
                        response, cnonce, security_verify, ue_port):
    """Build authenticated REGISTER with Security-Verify."""
    sec_client = build_security_client()
    contact = (f'<sip:{CONTACT_UUID}@{UE_IP}:{ue_port}>;'
               f'+g.3gpp.accesstype="cellular2";audio;+g.3gpp.smsip;video;'
               f'+g.3gpp.icsi-ref="urn%3Aurn-7%3A3gpp-service.ims.icsi.mmtel";'
               f'+sip.instance="<urn:gsma:imei:{IMEI}>"')
    
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
        f"Via: SIP/2.0/UDP {UE_IP}:{ue_port};branch={branch}\r\n"
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
        f"{auth_hdr}\r\n"
        f"Security-Verify: {security_verify}\r\n"
        f"User-Agent: CoreSimRunner-VoNR-IPSec/1.0\r\n"
        f"{sec_client}\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg

# ======================== SIP Parser ========================
def parse_sip(data):
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
    print("IMS Registration with IPSec Security (3GPP TS 33.203)")
    print(f"  UE IP: {UE_IP}:{UE_PORT}")
    print(f"  P-CSCF: {PCSCF_IP}:{PCSCF_PORT}")
    print(f"  IMSI: {IMSI}")
    print(f"  Domain: {IMS_DOMAIN}")
    print("=" * 70)

    # Create UDP socket bound to IPSec port (used for all SIP messages)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"uesimtun0")
    sock.bind((UE_IP, IPSEC_PORT_C))
    sock.settimeout(10.0)
    print(f"  Using IPSec port: {IPSEC_PORT_C}")

    call_id = f"{rand_hex(16)}@{UE_IP}"
    from_tag = rand_hex(8)
    cseq = 1

    # ============ Step 1: Initial REGISTER with Security-Client ============
    print(f"\n[1] Sending initial REGISTER with Security-Client...")
    branch = f"z9hG4bK{rand_hex(16)}"
    msg = build_initial_register(call_id, from_tag, branch, cseq)
    sock.sendto(msg.encode(), (PCSCF_IP, PCSCF_PORT))

    # Wait for 401 with Security-Server
    nonce = None
    realm = None
    security_server = ""
    
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
            resp = parse_sip(data)
            print(f"  <- {resp['status_line']}")
            if resp['status_code'] == 401:
                www_auth = resp['headers'].get('www-authenticate', '')
                security_server = resp['headers'].get('security-server', '')
                m = re.search(r'nonce="([^"]+)"', www_auth)
                if m:
                    nonce = m.group(1)
                m = re.search(r'realm="([^"]+)"', www_auth)
                if m:
                    realm = m.group(1)
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

    # ============ Step 2: Parse Security-Server and Compute AKA ============
    print(f"\n[2] Computing AKA and parsing Security-Server...")
    
    # Parse Security-Server parameters
    sec_params = parse_security_server(security_server)
    pcscf_spi_c = int(sec_params.get('spi-c', '0'))
    pcscf_spi_s = int(sec_params.get('spi-s', '0'))
    pcscf_port_c = int(sec_params.get('port-c', '5100'))
    pcscf_port_s = int(sec_params.get('port-s', '6100'))
    sec_alg = sec_params.get('alg', 'hmac-sha-1-96')
    sec_ealg = sec_params.get('ealg', 'null')

    print(f"  P-CSCF IPSec params:")
    print(f"    spi-c={pcscf_spi_c}, spi-s={pcscf_spi_s}")
    print(f"    port-c={pcscf_port_c}, port-s={pcscf_port_s}")
    print(f"    alg={sec_alg}, ealg={sec_ealg}")

    # Compute AKA
    username = f"{IMSI}@{IMS_DOMAIN}"
    uri = f"sip:{IMS_DOMAIN}"
    cnonce = str(random.randint(1000000000, 9999999999))
    
    response, res_hex, ck_hex, ik_hex = compute_aka_response(
        nonce, KI_HEX, OPC_HEX, username, realm, "REGISTER", uri, cnonce)
    print(f"  Digest response: {response}")

    # ============ Step 3: Setup IPSec SA ============
    print(f"\n[3] Setting up IPSec Security Associations...")
    
    # UE listens on port_c, sends to port_s
    # P-CSCF's port-c is where UE sends, port-s is where P-CSCF sends from
    ue_ipsec_port = pcscf_port_c  # UE uses P-CSCF's port-c as destination
    pcscf_ipsec_port = pcscf_port_s
    
    ipsec_ok = setup_ipsec_sa(
        ck_hex, ik_hex,
        pcscf_spi_c, pcscf_spi_s,  # Use P-CSCF's SPIs
        UE_IP, PCSCF_IP,
        IPSEC_PORT_C, pcscf_port_c,  # UE's port -> P-CSCF's port-c
        sec_alg, sec_ealg
    )

    if not ipsec_ok:
        print("  [WARN] IPSec setup failed, continuing without IPSec")

    # ============ Step 4: Send Authenticated REGISTER via IPSec ============
    print(f"\n[4] Sending authenticated REGISTER with Security-Verify...")
    
    # Reuse the same socket (bound to IPSEC_PORT_C)
    # P-CSCF's XFRM policy expects traffic from the initial REGISTER's source port
    print(f"  Using same port as initial REGISTER: {IPSEC_PORT_C}")

    cseq += 1
    branch = f"z9hG4bK{rand_hex(16)}"
    
    # Security-Verify echoes Security-Server exactly
    security_verify = security_server
    
    msg = build_auth_register(call_id, from_tag, branch, cseq, nonce, realm,
                              response, cnonce, security_verify, IPSEC_PORT_C)
    
    # Send to P-CSCF's IPSec port
    # Note: P-CSCF's XFRM SA expects traffic to port-c, not port-s
    # This is a quirk of the ims_ipsec_pcscf module
    target_port = pcscf_port_c  # Try port-c first
    sock.sendto(msg.encode(), (PCSCF_IP, target_port))
    print(f"  -> Sent to {PCSCF_IP}:{target_port} (IPSec)")

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
                print(f"\n  *** IMS REGISTRATION WITH IPSEC SUCCESSFUL ***")
                break
        except socket.timeout:
            break

    # ============ Summary ============
    print(f"\n{'=' * 70}")
    print(f"IMS IPSec Registration Flow Complete")
    print(f"  Registration: {'OK' if service_route else 'PENDING'}")
    print(f"  IPSec SA: {'Established' if ipsec_ok else 'Failed'}")
    print(f"{'=' * 70}")

    # Cleanup
    sock.close()
    cleanup_ipsec()

if __name__ == "__main__":
    main()
