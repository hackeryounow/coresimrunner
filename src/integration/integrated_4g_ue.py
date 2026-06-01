#!/usr/bin/env python3
"""
Integrated 4G UE (User Equipment) for LTE registration and PDN session establishment.

This module simulates a 4G UE using an event-driven handler pattern (mirroring IntegratedUE
from integrated_ue.py). All MME responses are processed via handle_message() which returns
response messages to be queued by the eNB's sender thread.
"""

import sys
import os
import socket
import struct
import time
from binascii import hexlify, unhexlify
from typing import List, Tuple, Optional
from loguru import logger


# Add workspace libraries to Python path
WORKSPACE_ROOT = '/root'
PYCRATE_PATH = os.path.join(WORKSPACE_ROOT, 'pycrate')
CRYPTOMOBILE_PATH = os.path.join(WORKSPACE_ROOT, 'CryptoMobile')

if PYCRATE_PATH not in sys.path:
    sys.path.insert(0, PYCRATE_PATH)
if CRYPTOMOBILE_PATH not in sys.path:
    sys.path.insert(0, CRYPTOMOBILE_PATH)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

from integrated_4g_messages import (
    return_plmn_s1ap, ip2int, encode_apn,
    return_key, return_kasme, milenage_res_ck_ik,
    nas_encrypt_func, nas_hash_func, nas_security_protected_nas_message,
    set_key, derive_all_nas_keys,
    nas_attach_request, nas_authentication_response, nas_identity_response,
    nas_security_mode_complete, nas_attach_complete,
    nas_activate_default_eps_bearer_context_accept,
    nas_activate_dedicated_eps_bearer_context_accept,
    nas_deactivate_eps_bearer_context_accept,
    nas_esm_information_response, nas_pdn_connectivity_request,
    nas_pco, nas_detach_accept, nas_tracking_area_update_complete,
    nas_guti_reallocation_complete,
    InitialUEMessage, UplinkNASTransport,
    InitialContextSetupResponse, ERABSetupResponse, UEContextReleaseComplete,
)
from eNAS import (
    nas_encode, nas_decode, encode_imsi, encode_imei, encode_guti, bcd,
    decode_pdn_address, decode_apn, decode_eps_mobile_identity,
)
from integrated_messages import plmn_bcd_encode
import socket as _socket


def _format_sgw_addr(addr):
    """Convert SGW transport address to human-readable IP string."""
    if addr is None:
        return 'N/A'
    if isinstance(addr, int):
        try:
            return _socket.inet_ntoa(struct.pack('!I', addr))
        except (struct.error, OSError):
            return str(addr)
    if isinstance(addr, bytes):
        if len(addr) == 4:
            return _socket.inet_ntoa(addr)
        return addr.hex()
    return str(addr)


def _format_teid(teid):
    """Convert GTP TEID to human-readable hex string."""
    if teid is None:
        return 'N/A'
    if isinstance(teid, bytes):
        return '0x' + teid.hex()
    if isinstance(teid, int):
        return f'0x{teid:08x}'
    return str(teid)


class Integrated4GUE:
    """
    Simulated 4G UE using event-driven message handling.

    Flow:
        1. eNB calls send_initial_ue_message() to get the first S1AP message (Attach Request).
        2. MME responds with DownlinkNASTransport / InitialContextSetupRequest / E-RABSetupRequest.
        3. eNB calls handle_message(type_t, procedure, IEs) which returns (self, [response_pdus]).
        4. eNB queues all response PDUs for the sender thread.
    """

    def __init__(self,
                 mcc: str,
                 mnc: str,
                 imsi_suffix10: str,
                 enb_ue_s1ap_id: int,
                 enb_address: str,
                 mme_address: str,
                 plmn: str = "46692",
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 apn: str = "internet",
                 tac: str = "0001",
                 imeisv: str = "4370816125816151",
                 op: bool = False,
                 attach_type: int = 1,
                 pdp_type: int = 1,
                 enb_cell_id: int = 1000000,
                 logging_level: str = 'INFO'):
        # UE identity
        self.mcc = mcc
        self.mnc = mnc
        self.plmn = plmn
        self.plmn_bcd = plmn_bcd_encode(plmn)
        self.tac = tac
        self.ki = unhexlify(ki)
        self.opc = unhexlify(opc)
        if op:
            self._calc_opc_from_k_op()
        self.imsi_suffix10 = imsi_suffix10
        self.supi = f"{mcc}{mnc}{imsi_suffix10.zfill(10)}"
        self.imeisv = imeisv
        self.apn = apn
        self.attach_type = attach_type
        self.pdp_type = pdp_type

        # eNB information
        self.enb_ue_s1ap_id = enb_ue_s1ap_id
        self.enb_address = enb_address
        self.mme_address = mme_address

        # State tracking
        self.ue_state = 0x0
        self.registered = False
        self.pdn_connected = False
        self.ue_release_enabled = True

        # NAS security
        self.enc_alg = 0
        self.int_alg = 0
        self.enc_key = None
        self.int_key = None
        self.kasme = b'\x00' * 32
        self.nas_key_eea1 = None
        self.nas_key_eea2 = None
        self.nas_key_eea3 = None
        self.nas_key_eia1 = None
        self.nas_key_eia2 = None
        self.nas_key_eia3 = None

        # NAS counters (UP-COUNT starts at -1 so first increment makes it 0,
        # matching eNB reference: SMC Complete uses count=0)
        self.up_count = -1
        self.down_count = -1
        self.dir = 0  # 0=uplink, 1=downlink

        # S1AP IDs
        self.mme_ue_s1ap_id = None

        # MME info
        self.mme_name = None
        self.mme_plmn = None
        self.mme_group_id = None
        self.mme_code = None
        self.mme_relative_capacity = 0

        # PDN / bearer info
        self.rab_id = []
        self.sgw_gtp_address = []
        self.sgw_teid = []
        self.eps_bearer_identity = []
        self.eps_bearer_type = []
        self.eps_bearer_state = []
        self.eps_bearer_apn = []
        self.pdn_address = []
        self.pdn_address_ipv4 = None
        self.pdn_address_ipv6 = None

        # Identity
        self.encoded_imsi = encode_imsi(self.supi)
        self.encoded_imei = encode_imei(imeisv)
        self.encoded_guti = None
        self.s_tmsi = None
        self.tmsi = None
        self.lai = None
        self.guti = None

        # Session types
        self.s1_type = "4G"
        self.mobile_identity = self.encoded_imsi
        self.mobile_identity_type = "IMSI"
        self.session_session_type = "NONE"
        self.session_type = "4G"
        self.sms_update_type = False
        self.pcscf_restoration = False
        self.pdn_connectivity_request_type = 1
        self.ue_radio_capability = b'\x00' * 16

        # eNB info for S1AP messages
        self.enb_name = 'Integrated-eNB'
        self.enb_plmn = return_plmn_s1ap(self.plmn)

        # TAC handling
        if isinstance(self.tac, bytes):
            tac_int = struct.unpack('!H', self.tac)[0]
        else:
            tac_int = int(str(self.tac), 16)
        self.enb_tac = struct.pack('!H', tac_int)
        self.enb_tac_nbiot = struct.pack('!H', tac_int + 1)
        self.enb_cellid = enb_cell_id
        self.enb_gtp_address_int = ip2int(self.enb_address)
        self.enb_gtp_address = socket.inet_aton(self.enb_address)

        # S1AP PDU
        self.PDU = S1AP.S1AP_PDU_Descriptions.S1AP_PDU

        # IMEISV request flag from Security Mode Command
        self.imeisv_requested = False

        # Logging
        logger.remove()
        logger.add(
            sink=sys.stdout,
            level=logging_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        logger.debug(f"4G UE initialized: IMSI={self.supi}, ENB-UE-S1AP-ID={self.enb_ue_s1ap_id}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_initial_ue_message(self):
        """Generate the Initial UE Message (Attach Request) S1AP PDU tuple."""
        try:
            nas_msg = nas_attach_request(
                type_tuple=(self.session_type, self.session_session_type),
                esm_information_transfer_flag=0,
                eps_identity=self.encoded_imsi,
                pdp_type=self.pdp_type,
                attach_type=self.attach_type,
                tmsi=self.tmsi,
                lai=self.lai,
                sms_update=self.sms_update_type,
                pcscf_restoration=self.pcscf_restoration,
                pdn_request_type=self.pdn_connectivity_request_type,
            )
            pdu_value = InitialUEMessage({
                'ENB-UE-S1AP-ID': self.enb_ue_s1ap_id,
                'NAS': nas_msg,
                'SESSION-TYPE': self.session_type,
                'ENB-PLMN': self.enb_plmn,
                'ENB-TAC': self.enb_tac,
                'ENB-TAC-NBIOT': self.enb_tac_nbiot,
                'ENB-CELLID': self.enb_cellid,
                'ATTACH-TYPE': self.attach_type,
                'S-TMSI': self.s_tmsi,
            })
            logger.info(f"4G UE {self.supi} generated Initial UE Message (Attach Request)")
            return pdu_value
        except Exception as e:
            logger.error(f"4G UE {self.supi} failed to generate Initial UE Message: {e}")
            import traceback; traceback.print_exc()
            return None

    def handle_message(self, type_t, procedure, IEs):
        """
        Handle an incoming S1AP message from the MME.

        Args:
            type_t: 'initiatingMessage' or 'successfulOutcome' etc.
            procedure: S1AP procedure name string (e.g. 'DownlinkNASTransport')
            IEs: List of protocol IE dicts from the S1AP PDU

        Returns:
            Tuple of (self, [response_pdu_values])
        """
        messages = []

        if type_t == 'initiatingMessage':
            if procedure == 'DownlinkNASTransport':
                messages = self._handle_downlink_nas_transport(IEs)
            elif procedure == 'InitialContextSetupRequest':
                messages = self._handle_initial_context_setup(IEs)
            elif procedure == 'E-RABSetupRequest':
                messages = self._handle_erab_setup(IEs)
            elif procedure == 'UEContextReleaseCommand':
                messages = self._handle_ue_context_release(IEs)
            elif procedure == 'Paging':
                pass
            else:
                logger.warning(f"4G UE {self.supi} unhandled procedure: {procedure}")

        elif type_t == 'successfulOutcome':
            if procedure == 'InitialUEMessage':
                logger.debug(f"4G UE {self.supi} Initial UE Message acknowledged")

        return self, messages

    # ------------------------------------------------------------------
    # S1AP-Level Handlers
    # ------------------------------------------------------------------

    def _handle_downlink_nas_transport(self, IEs):
        """Handle DownlinkNASTransport – extract NAS-PDU, process, wrap response in UplinkNASTransport."""
        mme_ue_s1ap_id = None
        nas_pdu = None

        for ie in IEs:
            if ie['id'] == 0:
                mme_ue_s1ap_id = ie['value'][1]
            elif ie['id'] == 26:
                nas_pdu = ie['value'][1]

        if mme_ue_s1ap_id is not None:
            self.mme_ue_s1ap_id = mme_ue_s1ap_id

        if nas_pdu is None:
            return []

        # Process the NAS PDU and get response NAS messages
        nas_responses = self._process_downlink_nas(nas_pdu)

        # Wrap each NAS response in UplinkNASTransport
        messages = []
        for nas_resp in nas_responses:
            pdu_value = UplinkNASTransport({
                'MME-UE-S1AP-ID': self.mme_ue_s1ap_id,
                'ENB-UE-S1AP-ID': self.enb_ue_s1ap_id,
                'NAS': nas_resp,
                'SESSION-TYPE': self.session_type,
                'ENB-PLMN': self.enb_plmn,
                'ENB-TAC': self.enb_tac,
                'ENB-TAC-NBIOT': self.enb_tac_nbiot,
                'ENB-CELLID': self.enb_cellid,
            })
            messages.append(pdu_value)
        return messages

    def _handle_initial_context_setup(self, IEs):
        """Handle InitialContextSetupRequest – parse E-RAB list, build response, process NAS."""
        mme_ue_s1ap_id = None
        erab_list = []
        nas_pdu = None
        ue_security_capabilities = None

        for ie in IEs:
            if ie['id'] == 0:   # MME-UE-S1AP-ID
                mme_ue_s1ap_id = ie['value'][1]
            elif ie['id'] == 24:  # E-RAB To Be Setup List
                erab_items = ie['value'][1]
                for item in erab_items:
                    erab_ie = item
                    erab_id = None
                    sgw_addr = None
                    sgw_teid = None
                    # Each item is a SEQUENCE with protocolIEs
                    if 'value' in erab_ie:
                        erab_val = erab_ie['value'][1]
                        erab_id = erab_val.get('e-RAB-ID')
                        sgw_transport = erab_val.get('transportLayerAddress')
                        sgw_teid_val = erab_val.get('gTP-TEID')
                        if sgw_transport:
                            if isinstance(sgw_transport, tuple):
                                sgw_addr = sgw_transport[0]
                            else:
                                sgw_addr = sgw_transport
                        if sgw_teid_val:
                            sgw_teid = sgw_teid_val
                    erab_list.append({'e-RAB-ID': erab_id, 'sgw_addr': sgw_addr, 'sgw_teid': sgw_teid})
            elif ie['id'] == 26:  # NAS-PDU (optional in InitialContextSetupRequest)
                nas_pdu = ie['value'][1]
            elif ie['id'] == 107:  # UE Security Capabilities
                ue_security_capabilities = ie['value'][1]

        if mme_ue_s1ap_id is not None:
            self.mme_ue_s1ap_id = mme_ue_s1ap_id

        # Store bearer info
        for erab in erab_list:
            if erab['e-RAB-ID'] is not None:
                self.rab_id.append(erab['e-RAB-ID'])
                self.sgw_gtp_address.append(erab.get('sgw_addr'))
                self.sgw_teid.append(erab.get('sgw_teid'))
                logger.info(
                    f"[4G UE {self.supi}] EPS session established: "
                    f"E-RAB={erab['e-RAB-ID']}, "
                    f"SGW-TEID={_format_teid(erab.get('sgw_teid'))}, "
                    f"SGW-Addr={_format_sgw_addr(erab.get('sgw_addr'))}"
                )

        messages = []

        # Process embedded NAS if present
        if nas_pdu is not None:
            nas_responses = self._process_downlink_nas(nas_pdu)
            for nas_resp in nas_responses:
                pdu_value = UplinkNASTransport({
                    'MME-UE-S1AP-ID': self.mme_ue_s1ap_id,
                    'ENB-UE-S1AP-ID': self.enb_ue_s1ap_id,
                    'NAS': nas_resp,
                    'SESSION-TYPE': self.session_type,
                    'ENB-PLMN': self.enb_plmn,
                    'ENB-TAC': self.enb_tac,
                    'ENB-TAC-NBIOT': self.enb_tac_nbiot,
                    'ENB-CELLID': self.enb_cellid,
                })
                messages.append(pdu_value)

        # Build InitialContextSetupResponse
        if erab_list:
            response_pdu = InitialContextSetupResponse(
                self.mme_ue_s1ap_id,
                self.enb_ue_s1ap_id,
                erab_list,
                self.enb_gtp_address_int,
            )
            messages.append(response_pdu)

        return messages

    def _handle_erab_setup(self, IEs):
        """Handle E-RABSetupRequest – parse E-RAB list, build response, process NAS."""
        mme_ue_s1ap_id = None
        erab_list = []
        nas_pdu = None

        for ie in IEs:
            if ie['id'] == 0:   # MME-UE-S1AP-ID
                mme_ue_s1ap_id = ie['value'][1]
            elif ie['id'] == 16:  # E-RAB To Be Setup List (BearerSUReq)
                erab_items = ie['value'][1]
                for item in erab_items:
                    erab_val = item['value'][1] if 'value' in item else item
                    erab_id = erab_val.get('e-RAB-ID')
                    sgw_transport = erab_val.get('transportLayerAddress')
                    sgw_teid_val = erab_val.get('gTP-TEID')
                    sgw_addr = None
                    sgw_teid = None
                    if sgw_transport:
                        if isinstance(sgw_transport, tuple):
                            sgw_addr = sgw_transport[0]
                        else:
                            sgw_addr = sgw_transport
                    if sgw_teid_val:
                        sgw_teid = sgw_teid_val
                    erab_list.append({'e-RAB-ID': erab_id, 'sgw_addr': sgw_addr, 'sgw_teid': sgw_teid})
            elif ie['id'] == 26:  # NAS-PDU
                nas_pdu = ie['value'][1]

        if mme_ue_s1ap_id is not None:
            self.mme_ue_s1ap_id = mme_ue_s1ap_id

        # Store bearer info
        for erab in erab_list:
            if erab['e-RAB-ID'] is not None:
                self.rab_id.append(erab['e-RAB-ID'])
                self.sgw_gtp_address.append(erab.get('sgw_addr'))
                self.sgw_teid.append(erab.get('sgw_teid'))
                logger.info(
                    f"[4G UE {self.supi}] E-RAB setup: "
                    f"E-RAB={erab['e-RAB-ID']}, "
                    f"SGW-TEID={_format_teid(erab.get('sgw_teid'))}, "
                    f"SGW-Addr={_format_sgw_addr(erab.get('sgw_addr'))}"
                )

        messages = []

        # Process embedded NAS if present
        if nas_pdu is not None:
            nas_responses = self._process_downlink_nas(nas_pdu)
            for nas_resp in nas_responses:
                pdu_value = UplinkNASTransport({
                    'MME-UE-S1AP-ID': self.mme_ue_s1ap_id,
                    'ENB-UE-S1AP-ID': self.enb_ue_s1ap_id,
                    'NAS': nas_resp,
                    'SESSION-TYPE': self.session_type,
                    'ENB-PLMN': self.enb_plmn,
                    'ENB-TAC': self.enb_tac,
                    'ENB-TAC-NBIOT': self.enb_tac_nbiot,
                    'ENB-CELLID': self.enb_cellid,
                })
                messages.append(pdu_value)

        # Build E-RABSetupResponse
        if erab_list:
            response_pdu = ERABSetupResponse(
                self.mme_ue_s1ap_id,
                self.enb_ue_s1ap_id,
                erab_list,
                self.enb_gtp_address_int,
            )
            messages.append(response_pdu)

        return messages

    def _handle_ue_context_release(self, IEs):
        """Handle UEContextReleaseCommand."""
        mme_ue_s1ap_id = None
        for ie in IEs:
            if ie['id'] == 0:
                mme_ue_s1ap_id = ie['value'][1]
        if mme_ue_s1ap_id is not None:
            self.mme_ue_s1ap_id = mme_ue_s1ap_id
        response_pdu = UEContextReleaseComplete(self.mme_ue_s1ap_id, self.enb_ue_s1ap_id)
        self.ue_release_enabled = False
        logger.info(f"4G UE {self.supi} context released")
        return [response_pdu]

    # ------------------------------------------------------------------
    # NAS Processing Pipeline
    # ------------------------------------------------------------------

    def _process_downlink_nas(self, nas_pdu):
        """
        Decode a downlink NAS PDU, decrypt if security-protected, and dispatch to handlers.

        Returns a list of NAS response bytes (already security-protected for uplink).
        """
        if nas_pdu is None or len(nas_pdu) < 2:
            return []

        nas_list = nas_decode(nas_pdu)
        if not nas_list:
            logger.warning(f"4G UE {self.supi} failed to decode NAS PDU")
            return []

        logger.debug(f"4G UE {self.supi} decoded NAS list: {nas_list}")

        protocol_discriminator = None
        security_header = 0
        message_type = None
        ies = []

        for item in nas_list:
            if item[0] == 'protocol discriminator':
                protocol_discriminator = item[1]
            elif item[0] == 'security header':
                security_header = item[1]
            elif item[0] == 'message type':
                message_type = item[1]
            elif item[0] == 'nas message encrypted':
                # Need to decrypt
                encrypted_nas = item[1]
                mac = None
                sqn = None
                for it in nas_list:
                    if it[0] == 'message authentication code':
                        mac = it[1]
                    elif it[0] == 'sequence_number':
                        sqn = it[1]
                if sqn is not None:
                    self.down_count = sqn
                plain_nas = nas_encrypt_func(encrypted_nas, self.down_count, 1, self.enc_key, self.enc_alg)
                # Re-decode the decrypted NAS
                return self._process_downlink_nas(plain_nas)
            else:
                ies.append(item)

        if protocol_discriminator == 7:  # EMM
            return self._dispatch_emm(message_type, ies)
        elif protocol_discriminator == 2:  # ESM
            return self._dispatch_esm(message_type, ies)

        logger.warning(f"4G UE {self.supi} unknown protocol discriminator: {protocol_discriminator}")
        return []

    def _dispatch_emm(self, message_type, ies):
        """Dispatch EMM message to the appropriate handler."""
        if message_type == 82:   # Authentication Request
            return self._handle_auth_request(ies)
        elif message_type == 93:  # Security Mode Command
            return self._handle_security_mode_command(ies)
        elif message_type == 66:  # Attach Accept
            return self._handle_attach_accept(ies)
        elif message_type == 85:  # Identity Request
            return self._handle_identity_request(ies)
        elif message_type == 68:  # Attach Reject
            logger.error(f"4G UE {self.supi} Attach Reject received")
            return []
        elif message_type == 84:  # Authentication Reject
            logger.error(f"4G UE {self.supi} Authentication Reject received")
            return []
        elif message_type == 73:  # TAU Accept
            return [nas_tracking_area_update_complete()]
        elif message_type == 80:  # GUTI Reallocation Command
            self._handle_guti_reallocation(ies)
            return [self._process_uplink_nas(nas_guti_reallocation_complete())]
        elif message_type == 69:  # Detach Request
            return [self._process_uplink_nas(nas_detach_accept())]
        elif message_type == 70:  # Detach Accept
            return []
        elif message_type == 97:  # EMM Information
            return []
        elif message_type == 96:  # EMM Status
            return []
        else:
            logger.warning(f"4G UE {self.supi} unhandled EMM message type: {message_type}")
            return []

    def _dispatch_esm(self, message_type, ies):
        """Dispatch ESM message to the appropriate handler."""
        if message_type == 193:  # Activate Default EPS Bearer Context Request
            return self._handle_activate_default_bearer(ies)
        elif message_type == 197:  # Activate Dedicated EPS Bearer Context Request
            return self._handle_activate_dedicated_bearer(ies)
        elif message_type == 205:  # Deactivate EPS Bearer Context Request
            return self._handle_deactivate_bearer(ies)
        elif message_type == 217:  # ESM Information Request
            return self._handle_esm_information_request(ies)
        elif message_type == 208:  # PDN Connectivity Accept
            return self._handle_pdn_connectivity_accept(ies)
        else:
            logger.warning(f"4G UE {self.supi} unhandled ESM message type: {message_type}")
            return []

    # ------------------------------------------------------------------
    # NAS Message Handlers
    # ------------------------------------------------------------------

    def _handle_auth_request(self, ies):
        """
        Handle Authentication Request (message type 82).
        Extract RAND/AUTN, compute RES/CK/IK via Milenage, derive KASME and all NAS keys.
        """
        rand_hex = None
        autn_hex = None
        ksi = 0

        logger.debug(f"4G UE {self.supi} Auth Request IEs: {ies}")

        for item in ies:
            if item[0] == 'nas key set identifier':
                ksi = item[1]
            elif item[0] == 'rand':
                rand_hex = hexlify(item[1]).decode()
            elif item[0] == 'autn':
                autn_hex = hexlify(item[1]).decode()

        if rand_hex is None or autn_hex is None:
            logger.error(f"4G UE {self.supi} Auth Request missing RAND/AUTN")
            return []

        # Compute RES, CK, IK
        res_hex, ck_hex, ik_hex = milenage_res_ck_ik(self.ki, self.opc, rand_hex)
        xres = unhexlify(res_hex)
        
        # Derive KASME
        self.kasme = return_kasme(self.plmn, autn_hex, ck_hex, ik_hex)
        # self.kasme = hexlify(self.kasme).decode()
        # Derive all NAS keys
        nas_keys = derive_all_nas_keys(self.kasme)
        self.nas_key_eea1 = nas_keys['NAS-KEY-EEA1']
        self.nas_key_eea2 = nas_keys['NAS-KEY-EEA2']
        self.nas_key_eea3 = nas_keys['NAS-KEY-EEA3']
        self.nas_key_eia1 = nas_keys['NAS-KEY-EIA1']
        self.nas_key_eia2 = nas_keys['NAS-KEY-EIA2']
        self.nas_key_eia3 = nas_keys['NAS-KEY-EIA3']
        logger.debug(f"4G UE {self.supi} RES: {res_hex}, CK: {ck_hex}, IK: {ik_hex}, KASME: {self.kasme.hex()}, AUTN: {autn_hex}, RAND: {rand_hex}")
        logger.debug(f"NAS Keys: {hexlify(self.nas_key_eia2).decode()}")
        self.ue_state |= 0x1
        logger.info(f"4G UE {self.supi} processed Authentication Request (KSI={ksi})")

        # Authentication Response is a plain NAS message (no security yet)
        nas_resp = nas_authentication_response(xres)
        return [nas_resp]

    def _handle_security_mode_command(self, ies):
        """
        Handle Security Mode Command (message type 93).
        Parse selected algorithms, set active keys, send Security Mode Complete.
        """
        selected_algos = 0
        imeisv_request = None

        for item in ies:
            if item[0] == 'selected nas security algorithms':
                selected_algos = item[1]
            elif item[0] == 'imeisv request':
                imeisv_request = item[1]
        # Parse algorithms: high nibble = encryption, low nibble = integrity
        self.enc_alg = (selected_algos >> 4) & 0x0F
        self.int_alg = selected_algos & 0x0F

        # Set active keys
        nas_keys = {
            'NAS-KEY-EEA1': self.nas_key_eea1,
            'NAS-KEY-EEA2': self.nas_key_eea2,
            'NAS-KEY-EEA3': self.nas_key_eea3,
            'NAS-KEY-EIA1': self.nas_key_eia1,
            'NAS-KEY-EIA2': self.nas_key_eia2,
            'NAS-KEY-EIA3': self.nas_key_eia3,
        }
        self.enc_key, self.int_key = set_key(self.enc_alg, self.int_alg, nas_keys)

        self.imeisv_requested = imeisv_request is not None

        self.ue_state |= 0x2
        logger.info(f"4G UE {self.supi} Security Mode Command: enc_alg={self.enc_alg}, int_alg={self.int_alg}")

        # Build Security Mode Complete
        imeisv_str = self.imeisv if self.imeisv_requested else None
        logger.debug(f"4G UE {self.supi} building Security Mode Complete (imeisv={self.imeisv})")
        smc_complete_plain = nas_security_mode_complete(imeisv=imeisv_str)

        # Security protect the SMC Complete message (new EPS security context)
        protected = self._process_uplink_nas(smc_complete_plain, new_security_context=True)
        return [protected]

    def _handle_attach_accept(self, ies):
        """
        Handle Attach Accept (message type 66).
        Parse GUTI, PDN info, bearer info, send Attach Complete.
        """
        eps_bearer_id = 0
        logger.debug(f"4G UE {self.supi} ies: {ies}")
        for item in ies:
            if item[0] == 'guti':
                self.guti = item[1]
                guti_decoded = decode_eps_mobile_identity(item[1])
                for g in guti_decoded:
                    if g[0] == 's-tmsi':
                        self.s_tmsi = g[1]
                logger.debug(f"---4G UE {self.supi} received GUTI")
            elif item[0] == 'esm message container':
                # The ESM container holds an Activate Default EPS Bearer Context Request
                esm_decoded = item[1]
                # Extract bearer identity from the ESM message
                for esm_item in esm_decoded:
                    if esm_item[0] == 'eps bearer identity':
                        eps_bearer_id = esm_item[1]
                    elif esm_item[0] == 'pdn address':
                        pdn_info = decode_pdn_address(esm_item[1])
                        
                        for pdn_item in pdn_info:
                            if pdn_item[0] == 'ipv4':
                                self.pdn_address_ipv4 = pdn_item[1]
                            elif pdn_item[0] == 'ipv6':
                                self.pdn_address_ipv6 = pdn_item[1]
                        # PDN address found in ESM container → PDN connected
                        if self.pdn_address_ipv4 or self.pdn_address_ipv6:
                            self.pdn_connected = True
                    elif esm_item[0] == 'access point name':
                        apn_info = decode_apn(esm_item[1])
                        if apn_info:
                            logger.debug(f"4G UE {self.supi} APN: {apn_info[0][1]}")
            elif item[0] == 'eps attach result':
                pass

        if eps_bearer_id not in self.eps_bearer_identity:
            self.eps_bearer_identity.append(eps_bearer_id)
            self.eps_bearer_type.append(0)  # default bearer
            self.eps_bearer_state.append(1)  # active

        self.ue_state |= 0x4
        self.registered = True
        logger.info(f"4G UE {self.supi} Attach Accept received (bearer={eps_bearer_id}, "
                     f"IPv4={self.pdn_address_ipv4})")
        # Print detailed session information
        logger.info(f"[4G UE {self.supi}] Registration complete")
        logger.info(f"    IMSI:        {self.supi}")
        logger.info(f"    IPv4:        {self.pdn_address_ipv4 or 'N/A'}")
        logger.info(f"    IPv6:        {self.pdn_address_ipv6 or 'N/A'}")
        logger.info(f"    APN/DNN:     {self.apn}")
        logger.info(f"    Bearer ID:   {eps_bearer_id}")

        # Build Attach Complete (with embedded Activate Default Bearer Accept)
        attach_complete_plain = nas_attach_complete(eps_bearer_id)
        protected = self._process_uplink_nas(attach_complete_plain)

        messages = [protected]

        # Optionally send PDN Connectivity Request for additional PDN
        # (for the default bearer, the MME typically assigns it in the Attach Accept)

        return messages

    def _handle_identity_request(self, ies):
        """Handle Identity Request (message type 85)."""
        identity_type = 1  # default IMSI
        for item in ies:
            if item[0] == 'identity type':
                identity_type = item[1]

        if identity_type == 1:  # IMSI
            identity_bytes = self.encoded_imsi
        elif identity_type == 3:  # IMEISV
            identity_bytes = bcd('3' + self.imeisv + 'f')
        else:
            identity_bytes = self.encoded_imsi

        logger.debug(f"4G UE {self.supi} Identity Request type={identity_type}")
        nas_resp = nas_identity_response(identity_bytes)
        return [nas_resp]

    def _handle_activate_default_bearer(self, ies):
        """Handle Activate Default EPS Bearer Context Request (message type 193)."""
        eps_bearer_id = 0

        for item in ies:
            if item[0] == 'eps bearer identity':
                eps_bearer_id = item[1]
            elif item[0] == 'pdn address':
                pdn_info = decode_pdn_address(item[1])
                for pdn_item in pdn_info:
                    if pdn_item[0] == 'ipv4':
                        self.pdn_address_ipv4 = pdn_item[1]
                    elif pdn_item[0] == 'ipv6':
                        self.pdn_address_ipv6 = pdn_item[1]
            elif item[0] == 'access point name':
                apn_info = decode_apn(item[1])
                if apn_info:
                    self.eps_bearer_apn.append(apn_info[0][1])

        if eps_bearer_id not in self.eps_bearer_identity:
            self.eps_bearer_identity.append(eps_bearer_id)
            self.eps_bearer_type.append(0)
            self.eps_bearer_state.append(1)

        self.pdn_connected = True
        self.ue_state |= 0x8
        logger.info(f"4G UE {self.supi} Activate Default Bearer (bearer={eps_bearer_id}, "
                     f"IPv4={self.pdn_address_ipv4})")
        # Print detailed bearer information
        print(f"  [4G UE {self.supi}] Default Bearer activated")
        print(f"    Bearer ID:   {eps_bearer_id}")
        print(f"    IPv4:        {self.pdn_address_ipv4 or 'N/A'}")
        if self.eps_bearer_apn:
            print(f"    APN:         {self.eps_bearer_apn[-1]}")
        for i, (teid, addr) in enumerate(zip(self.sgw_teid, self.sgw_gtp_address)):
            print(f"    SGW-TEID:    {_format_teid(teid)} (E-RAB {i})")
            print(f"    SGW-Addr:    {_format_sgw_addr(addr)} (E-RAB {i})")

        accept = nas_activate_default_eps_bearer_context_accept(eps_bearer_id, None)
        protected = self._process_uplink_nas(accept)
        return [protected]

    def _handle_activate_dedicated_bearer(self, ies):
        """Handle Activate Dedicated EPS Bearer Context Request (message type 197)."""
        eps_bearer_id = 0
        for item in ies:
            if item[0] == 'eps bearer identity':
                eps_bearer_id = item[1]

        if eps_bearer_id not in self.eps_bearer_identity:
            self.eps_bearer_identity.append(eps_bearer_id)
            self.eps_bearer_type.append(1)  # dedicated
            self.eps_bearer_state.append(1)

        logger.debug(f"4G UE {self.supi} Activate Dedicated Bearer (bearer={eps_bearer_id})")
        accept = nas_activate_dedicated_eps_bearer_context_accept(eps_bearer_id, None)
        protected = self._process_uplink_nas(accept)
        return [protected]

    def _handle_deactivate_bearer(self, ies):
        """Handle Deactivate EPS Bearer Context Request (message type 205)."""
        eps_bearer_id = 0
        for item in ies:
            if item[0] == 'eps bearer identity':
                eps_bearer_id = item[1]

        if eps_bearer_id in self.eps_bearer_identity:
            idx = self.eps_bearer_identity.index(eps_bearer_id)
            self.eps_bearer_state[idx] = 0

        logger.debug(f"4G UE {self.supi} Deactivate Bearer (bearer={eps_bearer_id})")
        accept = nas_deactivate_eps_bearer_context_accept(eps_bearer_id)
        protected = self._process_uplink_nas(accept)
        return [protected]

    def _handle_esm_information_request(self, ies):
        """Handle ESM Information Request (message type 217)."""
        eps_bearer_id = 0
        pti = 0
        for item in ies:
            if item[0] == 'eps bearer identity':
                eps_bearer_id = item[1]
            elif item[0] == 'procedure transaction identity':
                pti = item[1]

        apn_encoded = encode_apn(self.apn)
        logger.debug(f"4G UE {self.supi} ESM Information Request")
        response = nas_esm_information_response(eps_bearer_id, pti, apn_encoded, None)
        protected = self._process_uplink_nas(response)
        return [protected]

    def _handle_pdn_connectivity_accept(self, ies):
        """Handle PDN Connectivity Accept (message type 208)."""
        for item in ies:
            if item[0] == 'access point name':
                apn_info = decode_apn(item[1])
                if apn_info:
                    logger.debug(f"4G UE {self.supi} PDN Connectivity Accept APN: {apn_info[0][1]}")
        self.pdn_connected = True
        return []

    def _handle_guti_reallocation(self, ies):
        """Handle GUTI Reallocation Command (message type 80)."""
        for item in ies:
            if item[0] == 'guti':
                self.guti = item[1]
                guti_decoded = decode_eps_mobile_identity(item[1])
                for g in guti_decoded:
                    if g[0] == 's-tmsi':
                        self.s_tmsi = g[1]
                logger.debug(f"4G UE {self.supi} GUTI reallocated")

    # ------------------------------------------------------------------
    # NAS Security: Uplink protection
    # ------------------------------------------------------------------

    def _process_uplink_nas(self, nas_plain, new_security_context=False):
        """
        Encrypt + integrity protect a plain NAS message for uplink.

        Args:
            nas_plain: Plain NAS bytes
            new_security_context: If True, use security header type 4 (new EPS security context)

        Returns security-protected NAS bytes.
        """
        # Increment counter FIRST (matching eNB reference: UP-COUNT += 1 before processing)
        self.up_count += 1

        # Encrypt
        encrypted = nas_encrypt_func(nas_plain, self.up_count, 0, self.enc_key, self.enc_alg)

        # Compute MAC
        mac = nas_hash_func(encrypted, self.up_count, 0, self.int_key, self.int_alg)
        logger.debug(f"NAS MAC: {mac.hex()}")
        # Sequence number
        sqn = bytes([self.up_count % 256])

        # Security header: 4 = integrity+ciphered+new EPS security context, 1 = integrity+ciphered
        security_header = 4 if new_security_context else 1

        # Build the protected message
        protected = nas_security_protected_nas_message(security_header, mac, sqn, encrypted)

        return protected

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calc_opc_from_k_op(self):
        """Calculate OPC from K and OP using AES."""
        from Crypto.Cipher import AES
        cipher = AES.new(self.ki, AES.MODE_ECB)
        self.opc = bytes(a ^ b for a, b in zip(cipher.encrypt(self.opc), self.opc))

    def send_pdn_connectivity_request(self, apn=None, pti=1):
        """Generate a PDN Connectivity Request wrapped in UplinkNASTransport."""
        target_apn = apn or self.apn
        apn_encoded = encode_apn(target_apn)
        pco = nas_pco(self.pdp_type, self.pcscf_restoration)

        nas_msg = nas_pdn_connectivity_request(
            eps_bearer_identity=0,
            pti=pti,
            pdp_type=self.pdp_type,
            apn=apn_encoded,
            pco=pco,
        )

        protected_nas = self._process_uplink_nas(nas_msg)

        pdu_value = UplinkNASTransport({
            'MME-UE-S1AP-ID': self.mme_ue_s1ap_id,
            'ENB-UE-S1AP-ID': self.enb_ue_s1ap_id,
            'NAS': protected_nas,
            'SESSION-TYPE': self.session_type,
            'ENB-PLMN': self.enb_plmn,
            'ENB-TAC': self.enb_tac,
            'ENB-TAC-NBIOT': self.enb_tac_nbiot,
            'ENB-CELLID': self.enb_cellid,
        })
        return pdu_value

    def get_session_info(self):
        """Return session information for established bearers."""
        info = {
            'imsi': self.supi,
            'registered': self.registered,
            'pdn_connected': self.pdn_connected,
            'ipv4': self.pdn_address_ipv4,
            'ipv6': self.pdn_address_ipv6,
            'apn': self.apn,
            'sgw_teid': self.sgw_teid,
            'sgw_gtp_address': self.sgw_gtp_address,
            'enb_address': self.enb_address,
            'bearers': [],
        }
        for i, bid in enumerate(self.eps_bearer_identity):
            bearer = {
                'bearer_id': bid,
                'type': 'default' if (i < len(self.eps_bearer_type) and self.eps_bearer_type[i] == 0) else 'dedicated',
                'state': 'active' if (i < len(self.eps_bearer_state) and self.eps_bearer_state[i] == 1) else 'inactive',
                'apn': self.eps_bearer_apn[i] if i < len(self.eps_bearer_apn) else None,
                'sgw_teid': self.sgw_teid[i] if i < len(self.sgw_teid) else None,
                'sgw_addr': self.sgw_gtp_address[i] if i < len(self.sgw_gtp_address) else None,
            }
            info['bearers'].append(bearer)
        return info

    def __repr__(self):
        return (f"Integrated4GUE(imsi={self.supi}, enb_ue_s1ap_id={self.enb_ue_s1ap_id}, "
                f"mme_ue_s1ap_id={self.mme_ue_s1ap_id})")
