#!/usr/bin/env python3
"""
Integrated UE - Simulated User Equipment for multi-UE concurrent testing.

This module integrates the UE simulation logic from 5gregpdu/ue.py into CoreSimRunner,
providing enhanced multi-UE concurrent registration and PDU session establishment capabilities.
"""

import sys
import os
import time
import threading
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

try:
    from Crypto.Cipher import AES
    from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
    # Import ProcedureCode and MessageType from integrated_messages
    from coresimrunner.integration.integrated_messages import ProcedureCode, MessageType
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please run: bash setup.sh")
    sys.exit(1)


class IntegratedUE:
    """
    Simulated User Equipment for 5G registration and PDU session testing.
    
    This class handles the complete 5G registration procedure including:
    - Initial UE Message
    - Authentication
    - Security Mode Command
    - Registration Accept
    - PDU Session Establishment
    """
    
    def __init__(self, 
                 mcc: str,
                 mnc: str,
                 imsi_suffix10: str,
                 ran_ue_ngap_id: int,
                 gnb_nr_cell_id: int,
                 gnb_address: str,
                 slices: dict = {"SST": 1},
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 dnn: str = "internet",
                 tac: str = "000001",
                 imeisv: str = "4370816125816151",
                 op: bool = False,
                 ABBA: bytes = b"\x00\x00",
                 ciphAlgo: int = 0,
                 ntegAlgo: int = 2,
                 logging_level: str = 'INFO',
                 enable_ims: bool = False):
        """
        Initialize the simulated UE.
        
        Args:
            mcc: Mobile Country Code
            mnc: Mobile Network Code
            imsi_suffix10: IMSI suffix (10 digits)
            ran_ue_ngap_id: RAN UE NGAP ID
            gnb_nr_cell_id: NR Cell ID
            gnb_address: gNodeB address
            slices: Network slice configuration
            ki: Subscriber authentication key (hex)
            opc: Operator ciphered variant (hex)
            dnn: Data Network Name
            tac: Tracking Area Code
            imeisv: IMEI Software Version
            op: Use OP instead of OPC
            ABBA: Authentication Bearer Binding Assurance
            ciphAlgo: Ciphering algorithm
            ntegAlgo: Integrity algorithm
            logging_level: Logging level
        """
        # UE identity
        self.mcc = mcc
        self.mnc = mnc
        self.tac = tac
        self.slices = slices
        self.ki = bytes.fromhex(ki)
        self.opc = bytes.fromhex(opc)
        if op:
            self._calc_opc_from_k_op()
        self.imsi_suffix10 = imsi_suffix10
        self.supi = f"{mcc}{mnc}{imsi_suffix10.zfill(10)}"
        self.imeisv = imeisv
        
        # Import utility functions
        from coresimrunner.integration.integrated_messages import plmn_bcd_encode
        self.plmn_bcd = plmn_bcd_encode(self.mcc + self.mnc)
        
        self.dnn = dnn.encode() if isinstance(dnn, str) else dnn
        self.dnn2 = "ims".encode()
        self.enable_ims = enable_ims
        self.ran_ue_ngap_id = ran_ue_ngap_id
        
        # gNB information
        self.gnb_nr_cell_id = gnb_nr_cell_id
        self.gnb_address = gnb_address
        self.ABBA = ABBA
        self.paging = False
        
        # UE state tracking
        # 0x1 = Authentication Request received
        # 0x2 = Security Mode Command received  
        # 0x4 = Registration Accept received
        # 0x8 = PDU Session Established
        self.ue_state = 0x0
        
        # Security algorithms
        self.ciphAlgo = None
        self.ntegAlgo = None
        
        # Security keys and identifiers
        self.kseaf = None
        self.res = None
        self.amf_ue_ngap_id = None
        self.k_nas_int = None
        self.k_nas_enc = None
        
        # PDU session information
        self.gtp_teid = None
        self.dnn_ipv4 = None
        self.dnn_ipv6 = None
        self.upf_ip = None  # UPF N3 tunnel endpoint IP
        self.dnn_internet_qos = None
        self.dnn_internet_pdu_sess_id = None
        self.dnn2_ipv4 = None
        self.dnn2_ipv6 = None
        self.dnn2_ims_qos = None
        self.dnn2_ims_pdu_sess_id = None
        self.ue_5g_guti = None
        
        # Round 1 captured session info (for GTP-U encapsulation in round 2)
        self.round1_ipv4 = None
        self.round1_teid = None
        self.round1_upf_ip = None

        # Registration failure tracking
        self.registration_rejected = False
        self.registration_reject_cause = None
        
        # Session status flags
        self.registered = False
        self.dnn_internet_connected = False
        self.dnn2_ims_connected = False
        self.ue_release_enabled = True
        self.context_released = False  # Set True when UEContextReleaseCommand processed
        self.service_accepted = False   # Set True when Service Accept received after Service Request
        self.paging_received = False     # Set True when Paging received from AMF (for Open5GS service request flow)
        self.session_info = {}
        
        # Latency tracking - protocol phase timestamps
        self.t_start = None        # Initial UE Message sent (RRC + Registration Request)
        self.t_rrc = None          # First DL NAS response (AMF reachable)
        self.t_auth_sec = None     # Security Mode Complete sent
        self.t_registered = None   # Registration Accept received
        self.t_dnn1_done = None    # DNN1 (internet) PDU session established
        self.t_dnn2_done = None    # DNN2 (ims) PDU session established
        
        # NGAP PDU handler
        self.PDU = NGAP_PDU_Descriptions.NGAP_PDU
        
        # Configure logger
        logger.remove()
        logger.add(
            sink=sys.stdout, 
            level=logging_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
    
    def handle_message(self, type_t, pdu_dict):
        """
        Handle incoming NGAP messages and generate appropriate responses.
        
        Args:
            type_t: Message type ('initiatingMessage', 'successfulOutcome', etc.)
            pdu_dict: Parsed NGAP message dictionary
            
        Returns:
            Tuple of (updated UE object, list of response messages)
        """
        procedureCode = ProcedureCode(pdu_dict['procedureCode'])
        message_type = None
        
        # Extract message type for non-location reporting messages
        if procedureCode != ProcedureCode.ID_LOCATION_REPORTING_CONTROL and procedureCode != ProcedureCode.ID_UE_CONTEXT_RELEASE:
            message_type = self._extract_message_type(pdu_dict)
            if message_type is None:
                return self, []
        
        messages = []
        
        if type_t == 'initiatingMessage':
            # Record first DL response time (RRC phase end)
            if self.t_start and self.t_rrc is None:
                self.t_rrc = time.time()
            
            if procedureCode == ProcedureCode.ID_DOWNLINK_NAS_TRANSPORT:
                if message_type == MessageType.AUTHENTICATION_REQUEST:
                    # Handle Authentication Request
                    from coresimrunner.integration.integrated_messages import AuthRequestMessage, AuthenticationResponseMessage
                    self.kseaf, self.res, self.amf_ue_ngap_id = AuthRequestMessage(
                        pdu_dict, self.ki, self.opc, self.mcc, self.mnc
                    )
                    message = AuthenticationResponseMessage(
                        self.res, self.amf_ue_ngap_id, plmn_bcd=self.plmn_bcd, 
                        tac=self.tac, gnb_nr_cell_id=self.gnb_nr_cell_id, 
                        ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    self.ue_state = self.ue_state | 0x1
                    
                elif message_type == MessageType.SECURITY_MODE_COMMAND:
                    # Handle Security Mode Command
                    from coresimrunner.integration.integrated_messages import SecurityModeCommandMessage, SecurityModeCompleteMessage
                    self.ciphAlgo, self.ntegAlgo = SecurityModeCommandMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x2
                    message, self.k_nas_int, self.k_nas_enc = SecurityModeCompleteMessage(
                        self.amf_ue_ngap_id, self.kseaf, self.plmn_bcd, self.slices, 
                        self.imeisv, self.supi.encode(), self.tac, self.ABBA, 
                        self.ciphAlgo, self.ntegAlgo, ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    self.t_auth_sec = time.time()
                    
                elif message_type == MessageType.CONFIGURATION_UPDATE_COMMNAD:
                    # Handle Configuration Update Command
                    from coresimrunner.integration.integrated_messages import ConfigurationUpdateMessage
                    ConfigurationUpdateMessage(pdu_dict)
                    time.sleep(0.05)
                    
                elif message_type == MessageType.DEREGISTRATION_ACCEPT:
                    # Handle Deregistration Accept (NAS type 0x46)
                    from coresimrunner.integration.integrated_messages import DeregistrationAcceptHandler
                    DeregistrationAcceptHandler(pdu_dict)
                    # Do NOT set registered=False here; wait for UEContextReleaseCommand
                    # so that UEContextReleaseComplete is sent before connection closes.
                    self.dnn_internet_connected = False
                    self.dnn2_ims_connected = False
                    logger.info(f"\u2713 UE {self.supi} deregistration accepted by network")

                elif message_type == MessageType.REGISTRATION_REJECT:
                    # Handle Registration Reject (NAS type 0x44)
                    # Extract 5GMM cause from NAS-PDU
                    nas_pdu = None
                    for ie in pdu_dict['value'][1]['protocolIEs']:
                        if ie['value'][0] == 'NAS-PDU':
                            nas_pdu = ie['value'][1]
                            break
                    cause_val = None
                    if nas_pdu and len(nas_pdu) >= 4:
                        # Try both plain and security-protected NAS formats
                        if nas_pdu[1] == 0:  # plain (no security)
                            cause_val = nas_pdu[3] if len(nas_pdu) > 3 else None
                        else:
                            # Security-protected: EPD(1)+SecHdr(1)+MAC(8)+SeqNo(1)+EPD(1)+SecHdr(1)+Type(1)+Cause(1)
                            offset = 14  # skip security wrapper
                            if len(nas_pdu) > offset:
                                cause_val = nas_pdu[offset]
                    self.registration_rejected = True
                    self.registration_reject_cause = cause_val
                    nas_hex = nas_pdu.hex() if nas_pdu else 'N/A'
                    logger.error(f"\u2717 UE {self.supi} REGISTRATION REJECTED by AMF! "
                                f"5GMM cause={cause_val}, NAS-PDU={nas_hex}")
                    
                elif message_type == MessageType.SERVICE_ACCEPT:
                    # Handle Service Accept via DownlinkNASTransport (proc 4)
                    # Free5GC AMF sends Service Accept in DownlinkNASTransport, NOT InitialContextSetupRequest
                    from coresimrunner.integration.integrated_messages import (
                        InitialContextSetupAmfId
                    )
                    # Extract new AMF UE NGAP ID from NGAP IEs
                    protocolIEs = pdu_dict['value'][1]['protocolIEs']
                    for ie in protocolIEs:
                        if ie['value'][0] == 'AMF-UE-NGAP-ID':
                            val = ie['value'][1]
                            new_amf_id = val.get_val() if hasattr(val, 'get_val') else int(val)
                            if new_amf_id is not None:
                                self.amf_ue_ngap_id = new_amf_id
                    self.service_accepted = True
                    self.registered = True
                    self.context_released = False
                    logger.info(f"\u2713 UE {self.supi} service request accepted (via DownlinkNASTransport)")

                elif message_type == MessageType.PDU_SESSION_RELEASE_COMMAND:
                    # Handle PDU Session Release Command via DownlinkNASTransport (proc 4)
                    # Free5GC sends Release Command in DL NAS Transport instead of PDUSessionResourceReleaseCommand (proc 28)
                    logger.info(f"[PDU Release] Received PDU_SESSION_RELEASE_COMMAND via DownlinkNASTransport")
                    from coresimrunner.integration.integrated_messages import PDUSessionReleaseCompleteUplinkMessage
                    # Extract PDU Session ID from NGAP IE
                    pdu_sess_id = None
                    protocolIEs = pdu_dict['value'][1]['protocolIEs']
                    for ie in protocolIEs:
                        if ie['value'][0] == 'PDUSessionID':
                            val = ie['value'][1]
                            pdu_sess_id = val.get_val() if hasattr(val, 'get_val') else int(val)
                            logger.info(f"[PDU Release] Extracted PDU Session ID from NGAP IE: {pdu_sess_id}")
                            break
                    # Fallback: try to extract from NAS-PDU payload
                    if pdu_sess_id is None:
                        logger.info(f"[PDU Release] PDU Session ID not found in NGAP IE, trying NAS-PDU fallback")
                        for ie in protocolIEs:
                            if ie['value'][0] == 'NAS-PDU':
                                nas_bytes = ie['value'][1]
                                nas_hex = nas_bytes.hex()
                                # EPD(2) + SecHdr(1) + Type(1) + PayloadContainerType(1) + PDUSessID(1)
                                if len(nas_hex) >= 12:
                                    try:
                                        pdu_sess_id = int(nas_hex[10:12], 16)
                                        logger.info(f"[PDU Release] Extracted PDU Session ID from NAS-PDU: {pdu_sess_id}")
                                    except ValueError:
                                        pass
                                break
                    if pdu_sess_id is None:
                        pdu_sess_id = self.dnn_internet_pdu_sess_id or 1
                        logger.info(f"[PDU Release] Using default PDU Session ID: {pdu_sess_id}")

                    logger.info(f"UE {self.supi} received PDU Session Release Command (via DownlinkNASTransport) for session {pdu_sess_id}")
                    if pdu_sess_id == self.dnn_internet_pdu_sess_id:
                        self.dnn_internet_connected = False
                        logger.info(f"[PDU Release] Set dnn_internet_connected = False")
                    elif pdu_sess_id == self.dnn2_ims_pdu_sess_id:
                        self.dnn2_ims_connected = False
                    self.ue_state = self.ue_state & ~0x8

                    # Send PDU Session Release Complete via UplinkNASTransport
                    msg = PDUSessionReleaseCompleteUplinkMessage(
                        self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc,
                        self.plmn_bcd, self.tac, self.ciphAlgo, self.ntegAlgo,
                        self.gnb_nr_cell_id, self.ran_ue_ngap_id,
                        pdu_sess_id=pdu_sess_id
                    )
                    messages.append(msg)
                    logger.info(f"\u2713 UE {self.supi} PDU session {pdu_sess_id} released (via DownlinkNASTransport)")
                    
            elif procedureCode == ProcedureCode.ID_INITIAL_CONTEXT_SETUP:
                if message_type == MessageType.REGISTRATION_ACCEPT:
                    # Handle Registration Accept
                    from coresimrunner.integration.integrated_messages import InitialContextSetupRequestMessage, InitialContextSetupResponseMessage, RegistrationCompleteMessage
                    self.ue_5g_guti = InitialContextSetupRequestMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x4
                    self.registered = True
                    self.t_registered = time.time()
                    
                    # Send Initial Context Setup Response
                    message = InitialContextSetupResponseMessage(
                        self.amf_ue_ngap_id, ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    
                    # Send Registration Complete
                    message = RegistrationCompleteMessage(
                        self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc, 
                        self.plmn_bcd, tac=self.tac, ciphAlgo=self.ciphAlgo, 
                        ntegAlgo=self.ntegAlgo, ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    
                    # Initiate PDU Session Establishment for internet DNN
                    message = self.send_pdusession_establishment_request(self.dnn, pdu_sess_id=1)
                    messages.append(message)
                    
                    logger.info(f"✓ UE {self.supi} registered successfully")
                    
                elif message_type == MessageType.SERVICE_ACCEPT:
                    # Handle Service Accept (arrives via InitialContextSetupRequest after Service Request)
                    from coresimrunner.integration.integrated_messages import (
                        InitialContextSetupAmfId,
                        InitialContextSetupResponseMessage
                    )
                    # Extract new AMF UE NGAP ID (AMF may assign a new one after context release)
                    new_amf_id = InitialContextSetupAmfId(pdu_dict)
                    if new_amf_id is not None:
                        self.amf_ue_ngap_id = new_amf_id
                    self.registered = True
                    self.context_released = False
                    
                    # Send Initial Context Setup Response
                    message = InitialContextSetupResponseMessage(
                        self.amf_ue_ngap_id, ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    self.dnn_internet_connected = True
                    logger.info(f"✓ UE {self.supi} service request accepted")
                    
                else:
                    logger.warn(f"Unknown or Unsupported message type: {message_type}")
                    
            elif procedureCode == ProcedureCode.ID_PDU_SESSION_RESOURCE_SETUP:
                if message_type == MessageType.DL_NAS_TRANSPORT:
                    # Handle PDU Session Resource Setup Request
                    from coresimrunner.integration.integrated_messages import PDUSessionResourceSetupRequestMessage, PDUSessResourceSetupResponseMessage
                    ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID, upf_ip_str = PDUSessionResourceSetupRequestMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x8
                    
                    # Configure DNN session
                    extra_messages = self._configure_dnn_session(
                        ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID, upf_ip_str
                    )
                    
                    # Send PDU Session Resource Setup Response
                    message = PDUSessResourceSetupResponseMessage(
                        self.amf_ue_ngap_id, qosFlowIdentifier, self.plmn_bcd, 
                        gnb_ip=self.gnb_address, gnb_teid=2, ran_ue_ngap_id=self.ran_ue_ngap_id, 
                        tac=self.tac, pdu_sess_id=PDUSessID
                    )
                    messages.append(message)
                    
                    # Append any extra messages (e.g., DNN2 PDU session trigger)
                    if extra_messages:
                        messages.extend(extra_messages)
                    
                    logger.info(f"✓ UE {self.supi} PDU session established: IPv4={ipv4_str}")
                    
                elif message_type == MessageType.SERVICE_ACCEPT:
                    # Service Accept after Service Request is handled under ID_INITIAL_CONTEXT_SETUP (proc 14)
                    logger.debug(f"Service Accept received under PDU Session Resource Setup (unexpected)")
                    
                else:
                    logger.warn(f"Unknown or Unsupported message type: {message_type}")
                    
            elif procedureCode == ProcedureCode.ID_PDU_SESSION_RESOURCE_RELEASE:
                # Handle PDUSessionResourceReleaseCommand (proc 28)
                # Contains NAS-PDU with DL NAS Transport wrapping PDU Session Release Command
                from coresimrunner.integration.integrated_messages import (
                    PDUSessionReleaseCommandHandler,
                    PDUSessionResourceReleaseResponseMessage,
                    PDUSessionReleaseCompleteUplinkMessage
                )
                pdu_sess_id = PDUSessionReleaseCommandHandler(pdu_dict)
                if pdu_sess_id is not None:
                    logger.info(f"UE {self.supi} received PDU Session Release Command for session {pdu_sess_id}")
                    # Mark session as released
                    if pdu_sess_id == self.dnn_internet_pdu_sess_id:
                        self.dnn_internet_connected = False
                    elif pdu_sess_id == self.dnn2_ims_pdu_sess_id:
                        self.dnn2_ims_connected = False
                    self.ue_state = self.ue_state & ~0x8  # Clear PDU established bit

                    # Send PDUSessionResourceReleaseResponse (proc 28)
                    msg = PDUSessionResourceReleaseResponseMessage(
                        self.amf_ue_ngap_id, self.ran_ue_ngap_id, pdu_sess_id,
                        self.plmn_bcd, self.tac, self.gnb_nr_cell_id
                    )
                    messages.append(msg)

                    # Send PDU Session Release Complete via UplinkNASTransport
                    msg = PDUSessionReleaseCompleteUplinkMessage(
                        self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc,
                        self.plmn_bcd, self.tac, self.ciphAlgo, self.ntegAlgo,
                        self.gnb_nr_cell_id, self.ran_ue_ngap_id,
                        pdu_sess_id=pdu_sess_id
                    )
                    messages.append(msg)
                    logger.info(f"\u2713 UE {self.supi} PDU session {pdu_sess_id} released")
                else:
                    logger.warning(f"UE {self.supi} could not extract PDU Session ID from Release Command")

            elif procedureCode == ProcedureCode.ID_LOCATION_REPORTING_CONTROL:
                # Handle Location Reporting Control
                from coresimrunner.integration.integrated_messages import LocationReportingControlMessage
                LocationReportingControlMessage(pdu_dict)
                
            elif procedureCode == ProcedureCode.ID_UE_CONTEXT_RELEASE:
                # Handle UE Context Release Command
                from coresimrunner.integration.integrated_messages import UEContextReleaseCommandMessage, UEContextReleaseCompleteMessage
                self.amf_ue_ngap_id, self.ran_ue_ngap_id = UEContextReleaseCommandMessage(pdu_dict)
                # Collect active PDU session IDs for dynamic PDUSessionResourceListCxtRelCpl
                active_sessions = []
                if self.dnn_internet_pdu_sess_id is not None and self.dnn_internet_connected:
                    active_sessions.append(self.dnn_internet_pdu_sess_id)
                if self.dnn2_ims_pdu_sess_id is not None and self.dnn2_ims_connected:
                    active_sessions.append(self.dnn2_ims_pdu_sess_id)
                message = UEContextReleaseCompleteMessage(
                    self.amf_ue_ngap_id, self.ran_ue_ngap_id, self.plmn_bcd,
                    self.tac, self.gnb_nr_cell_id, pdu_session_ids=active_sessions if active_sessions else None
                )
                messages.append(message)
                self.ue_release_enabled = False
                self.registered = False
                self.context_released = True
                self.dnn_internet_connected = False
                self.dnn2_ims_connected = False
                self.ue_state = 0x0
                logger.info(f"\u2713 UE {self.supi} context released")
                
        return self, messages

    def _extract_message_type(self, pdu_dict):
        """Extract the NAS message type from the NGAP PDU."""
        nas_pdu = ""
        protocolIEs = pdu_dict['value'][1]['protocolIEs']
        logger.debug(f"Protocol IEs: {protocolIEs}")
        for ie in protocolIEs:
            if ie['value'][0] == 'NAS-PDU':
                nas_pdu = ie['value'][1]
                break
            if ie['value'][0] == 'PDUSessionResourceSetupListSUReq':
                nas_pdu = ie["value"][1][0]['pDUSessionNAS-PDU']
            # Handle PDUSessionResourceToReleaseListRelCmd (proc 28) - NAS-PDU is in top-level IE
            # but we also check here for completeness

        # For PDUSessionResourceReleaseCommand, the NAS-PDU is a separate IE (id=38)
        # so the loop above will find it. But if not found, check release list
        if not nas_pdu:
            for ie in protocolIEs:
                if ie['value'][0] == 'PDUSessionResourceToReleaseListRelCmd':
                    # The release command has its own NAS-PDU in the top-level IE (id=38)
                    # If we reach here, there's no NAS-PDU IE - just return None
                    break
                
        nas_pdu_hex = nas_pdu.hex()
        
        # Skip extended protocol discriminator and security header if present
        if len(nas_pdu_hex) >= 6:
            if nas_pdu_hex[3] != "0":
                nas_pdu_hex = nas_pdu_hex[14:]
            message_type_str = nas_pdu_hex[4:6]
            if message_type_str:
                try:
                    return MessageType(int(message_type_str, 16))
                except ValueError:
                    return None
        return None

    def _configure_dnn_session(self, ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID, upf_ip_str=None):
        """Configure DNN session based on the returned DNN value and store session information.
        
        Returns a list of extra messages to send (e.g., DNN2 PDU session trigger after DNN1).
        """
        extra_messages = []
        
        if isinstance(DNN, bytes):
            DNN = DNN.decode('utf-8', errors='ignore')
            
        # Convert TEID to hexadecimal string format as requested
        teid_hex = gTP_TEID.hex()
        logger.info(f"TEID conversion: raw={repr(gTP_TEID)}, type={type(gTP_TEID).__name__}, hex={teid_hex}, int=0x{int(teid_hex, 16):08x}")
        
        # Create session information entry
        session_entry = {
            'imsi': self.supi,
            'dnn': DNN,
            'ipv4': ipv4_str,
            'ipv6': None,
            'teid': teid_hex,
            'qos_flow_id': qosFlowIdentifier,
            'pdu_session_id': PDUSessID,
            'snssai': SNSSAI
        }
        
        # Store session info by DNN
        self.session_info[DNN] = session_entry
        
        if DNN == self.dnn.decode('utf-8'):  # "internet"
            self.dnn_ipv4 = ipv4_str
            self.dnn_ipv6 = None
            self.dnn_gtp_teid = teid_hex
            self.upf_ip = upf_ip_str
            self.dnn_internet_connected = True
            self.dnn_internet_qos = qosFlowIdentifier
            self.dnn_internet_pdu_sess_id = PDUSessID
            self.t_dnn1_done = time.time()
            logger.debug(f"Configured internet DNN session - IMSI: {self.supi}, DNN: {DNN}, IPv4: {ipv4_str}, TEID: {teid_hex}")
            
            # Trigger DNN2 (ims) PDU session if enabled
            if self.enable_ims:
                logger.info(f"UE {self.supi} triggering DNN2 (ims) PDU session establishment")
                dnn2_msg = self.send_pdusession_establishment_request(self.dnn2, pdu_sess_id=2)
                extra_messages.append(dnn2_msg)
                
        elif DNN == self.dnn2.decode('utf-8'):  # "ims"
            self.dnn2_ipv4 = ipv4_str
            self.dnn2_ipv6 = None
            self.dnn2_gtp_teid = teid_hex
            self.dnn2_ims_connected = True
            self.dnn2_ims_qos = qosFlowIdentifier
            self.dnn2_ims_pdu_sess_id = PDUSessID
            self.t_dnn2_done = time.time()
            logger.debug(f"Configured IMS DNN session - IMSI: {self.supi}, DNN: {DNN}, IPv4: {ipv4_str}, TEID: {teid_hex}")
        else:
            logger.warn(f"Unknown DNN received: {DNN}")
            
        # Log comprehensive session information after each session establishment
        self._log_session_info()
        return extra_messages
    
    def _log_session_info(self):
        """Log session information with phase-based latency statistics."""
        # Build the log message
        log_msg = f"PDU Session Establishment Complete - IMSI: {self.supi};"
        
        # Add DNN1 (internet) information if available
        if self.dnn_internet_connected:
            dnn1_ipv4 = self.dnn_ipv4 or "N/A"
            dnn1_teid = self.dnn_gtp_teid or "N/A"
            log_msg += f"DNN1 (internet): IPv4={dnn1_ipv4}, TEID={dnn1_teid};"
        else:
            log_msg += "DNN1 (internet): Not established;"
            
        # Add DNN2 (ims) information if available  
        if self.dnn2_ims_connected:
            dnn2_ipv4 = self.dnn2_ipv4 or "N/A"
            dnn2_teid = self.dnn2_gtp_teid or "N/A"
            log_msg += f"DNN2 (ims): IPv4={dnn2_ipv4}, TEID={dnn2_teid};"
        elif self.enable_ims:
            log_msg += "DNN2 (ims): Pending;"
        else:
            log_msg += "DNN2 (ims): Disabled;"
        
        # Phase-based latency statistics
        latencies = []
        # Phase 1: RRC 连接建立 (Initial UE Message → First DL response)
        if self.t_start and self.t_rrc:
            rrc_lat = (self.t_rrc - self.t_start) * 1000
            latencies.append(f"RRC={rrc_lat:.1f}ms")
        # Phase 2: 鉴权+安全模式 (First DL response → Security Mode Complete sent)
        if self.t_rrc and self.t_auth_sec:
            auth_lat = (self.t_auth_sec - self.t_rrc) * 1000
            latencies.append(f"Auth+Sec={auth_lat:.1f}ms")
        # Phase 3: 初始注册完成 (Security Mode Complete → Registration Accept)
        if self.t_auth_sec and self.t_registered:
            reg_lat = (self.t_registered - self.t_auth_sec) * 1000
            latencies.append(f"Registration={reg_lat:.1f}ms")
        # Phase 4: PDU 会话 1 建立 (Registration Accept → DNN1 established)
        if self.t_registered and self.t_dnn1_done:
            dnn1_lat = (self.t_dnn1_done - self.t_registered) * 1000
            latencies.append(f"PDU1={dnn1_lat:.1f}ms")
        # Phase 5: PDU 会话 2 建立 (DNN1 → DNN2 established)
        if self.t_dnn1_done and self.t_dnn2_done:
            dnn2_lat = (self.t_dnn2_done - self.t_dnn1_done) * 1000
            latencies.append(f"PDU2={dnn2_lat:.1f}ms")
        # Total time
        if self.t_start and self.t_dnn2_done:
            total_lat = (self.t_dnn2_done - self.t_start) * 1000
            latencies.append(f"Total={total_lat:.1f}ms")
        elif self.t_start and self.t_dnn1_done:
            total_lat = (self.t_dnn1_done - self.t_start) * 1000
            latencies.append(f"Total={total_lat:.1f}ms")
        
        if latencies:
            log_msg += "Latency: " + ", ".join(latencies) + ";"
            
        logger.info(log_msg)

    def get_session_info(self):
        """Return session information for all established sessions."""
        return self.session_info

    def _calc_opc_from_k_op(self):
        """Calculate OPC from OP using AES encryption."""
        cipher = AES.new(self.ki, AES.MODE_ECB)
        self.opc = bytes(a ^ b for a, b in zip(cipher.encrypt(self.opc), self.opc))

    def send_initial_ue_message(self):
        """Send Initial UE Message to start registration."""
        from coresimrunner.integration.integrated_messages import InitialUEMessage
        self.t_start = time.time()
        message = InitialUEMessage(
            self.plmn_bcd, self.tac,
            nr_cell_id=self.gnb_nr_cell_id,
            ran_ue_ngap_id=self.ran_ue_ngap_id,
            slices=[self.slices],
            supi=self.supi
        )
        return message
    
    def send_service_request(self):
        """Send Service Request via InitialUEMessage (after context release)."""
        from coresimrunner.integration.integrated_messages import ServiceRequestMessage
        message = ServiceRequestMessage(
            self.plmn_bcd, self.tac, self.ue_5g_guti, self.k_nas_enc, 
            self.k_nas_int, self.ciphAlgo, self.ntegAlgo, 
            self.gnb_nr_cell_id, self.ran_ue_ngap_id
        )
        return message

    def release_ue_context(self):
        """Send UE Context Release Request."""
        from coresimrunner.integration.integrated_messages import UEContextReleaseRequestMessage
        message = UEContextReleaseRequestMessage(
            self.amf_ue_ngap_id, self.ran_ue_ngap_id
        )
        return message

    def send_pdusession_establishment_request(self, dnn, pdu_sess_id=1):
        """Send PDU Session Establishment Request."""
        from coresimrunner.integration.integrated_messages import PDUSessionEstablishmentRequestMessage
        message = PDUSessionEstablishmentRequestMessage(
            self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc, 
            self.plmn_bcd, slices=self.slices, dnn=dnn, 
            ran_ue_ngap_id=self.ran_ue_ngap_id, tac=self.tac, 
            ciphAlgo=self.ciphAlgo, ntegAlgo=self.ntegAlgo, 
            gnb_id=self.gnb_nr_cell_id,
            pdu_sess_id=pdu_sess_id
        )
        return message

    def send_deregistration_request(self):
        """Send Deregistration Request (UE originating, NAS type 0x45)."""
        from coresimrunner.integration.integrated_messages import DeregistrationRequestMessage
        message = DeregistrationRequestMessage(
            self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc,
            self.plmn_bcd, self.tac, self.ciphAlgo, self.ntegAlgo,
            self.gnb_nr_cell_id, self.ran_ue_ngap_id,
            guti=self.ue_5g_guti
        )
        return message

    def send_pdu_session_release_request(self, pdu_sess_id=1):
        """Send PDU Session Release Request (NAS type 0xd1)."""
        from coresimrunner.integration.integrated_messages import PDUSessionReleaseRequestMessage
        message = PDUSessionReleaseRequestMessage(
            self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc,
            self.plmn_bcd, self.tac, self.ciphAlgo, self.ntegAlgo,
            self.gnb_nr_cell_id, self.ran_ue_ngap_id,
            pdu_sess_id=pdu_sess_id
        )
        return message
    
    def save_round1_session(self):
        """Save round 1 session info (IP, TEID, UPF IP) for GTP-U encapsulation in round 2."""
        self.round1_ipv4 = self.dnn_ipv4
        self.round1_teid = self.dnn_gtp_teid
        self.round1_upf_ip = self.upf_ip
        logger.info(f"UE {self.supi} saved round1 session: IPv4={self.round1_ipv4}, TEID={self.round1_teid}, UPF_IP={self.round1_upf_ip}")

    def reset_for_reregistration(self):
        """Reset UE state for re-registration while preserving round 1 session info."""
        self.ue_state = 0x0
        self.kseaf = None
        self.res = None
        self.amf_ue_ngap_id = None
        self.k_nas_int = None
        self.k_nas_enc = None
        self.gtp_teid = None
        self.dnn_ipv4 = None
        self.dnn_ipv6 = None
        self.upf_ip = None
        self.dnn_internet_qos = None
        self.dnn_internet_pdu_sess_id = None
        self.dnn2_ipv4 = None
        self.dnn2_ipv6 = None
        self.dnn2_ims_qos = None
        self.dnn2_ims_pdu_sess_id = None
        self.ue_5g_guti = None
        self.registered = False
        self.dnn_internet_connected = False
        self.dnn2_ims_connected = False
        self.context_released = False
        self.service_accepted = False
        self.paging_received = False
        self.ue_release_enabled = True
        self.session_info = {}
        self.t_start = None
        self.t_rrc = None
        self.t_auth_sec = None
        self.t_registered = None
        self.t_dnn1_done = None
        self.t_dnn2_done = None
        logger.info(f"UE {self.supi} reset for re-registration (round1 info preserved)")

    def build_gtpu_packet(self, payload, teid, msg_type=0xFF):
        """Build a GTP-U packet with the given payload.
        
        Args:
            payload: The inner payload bytes (e.g., NAS message)
            teid: Tunnel Endpoint Identifier (hex string or int)
            msg_type: GTP-U message type (0xFF = G-PDU)
        
        Returns:
            bytes: Complete GTP-U packet
        """
        import struct
        # Convert TEID to int if hex string
        if isinstance(teid, str):
            teid_int = int(teid, 16)
        else:
            teid_int = teid
        
        # GTP-U header (8 bytes):
        # Version(3b)=1, PT(1b)=1, Reserved(1b)=0, E(1b)=0, S(1b)=0, PN(1b)=0
        # => first byte = 0x30
        flags = 0x30
        length = len(payload)
        header = struct.pack('!BBHI', flags, msg_type, length, teid_int)
        return header + payload

    def send_gtpu_encapsulated_registration(self, target_ip, target_port=2152):
        """Send registration request encapsulated in GTP-U using round 1 IP/TEID.
        
        This sends the NAS Registration Request wrapped in a GTP-U header via UDP
        to simulate user-plane tunneling with the previously assigned credentials.
        
        Args:
            target_ip: UPF/target IP address for GTP-U tunnel
            target_port: UDP port (default 2152 for GTP-U)
        
        Returns:
            Tuple of (ngap_message, gtpu_packet_bytes, target_ip, target_port)
        """
        import socket as sock
        
        # Build NAS Registration Request
        from coresimrunner.integration.integrated_messages import fgmm_registration_request_message, plmn_bcd_decode
        plmn = plmn_bcd_decode(self.plmn_bcd)
        msin = self.supi[-10:]
        nas_pdu = fgmm_registration_request_message(
            msin=msin, plmn=plmn, nssai=[self.slices]
        )
        
        # Build GTP-U packet with NAS as payload
        teid = self.round1_teid
        gtpu_packet = self.build_gtpu_packet(nas_pdu, teid)
        
        # Send GTP-U packet via UDP
        try:
            udp_sock = sock.socket(sock.AF_INET, sock.SOCK_DGRAM)
            udp_sock.sendto(gtpu_packet, (target_ip, target_port))
            udp_sock.close()
            logger.info(f"UE {self.supi} sent GTP-U encapsulated registration to {target_ip}:{target_port} "
                       f"(TEID=0x{teid if isinstance(teid, int) else teid}, payload={len(nas_pdu)}B, total={len(gtpu_packet)}B)")
        except Exception as e:
            logger.error(f"UE {self.supi} failed to send GTP-U packet: {e}")
        
        return gtpu_packet
    
    def __repr__(self):
        return f"IntegratedUE(imsi={self.imsi_suffix10}, ran_ue_ngap_id={self.ran_ue_ngap_id}, amf_ue_ngap_id={self.amf_ue_ngap_id})"