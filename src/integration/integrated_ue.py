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

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from Crypto.Cipher import AES
    from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
    # Import ProcedureCode and MessageType from integrated_messages
    from integrated_messages import ProcedureCode, MessageType
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
                 logging_level: str = 'INFO'):
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
        from integrated_messages import plmn_bcd_encode
        self.plmn_bcd = plmn_bcd_encode(self.mcc + self.mnc)
        
        self.dnn = dnn.encode() if isinstance(dnn, str) else dnn
        self.dnn2 = "ims".encode()
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
        self.dnn_internet_qos = None
        self.dnn_internet_pdu_sess_id = None
        self.dnn2_ipv4 = None
        self.dnn2_ipv6 = None
        self.dnn2_ims_qos = None
        self.dnn2_ims_pdu_sess_id = None
        self.ue_5g_guti = None
        
        # Session status flags
        self.registered = False
        self.dnn_internet_connected = False
        self.dnn2_ims_connected = False
        self.ue_release_enabled = True
        self.session_info = {}
        
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
            if procedureCode == ProcedureCode.ID_DOWNLINK_NAS_TRANSPORT:
                if message_type == MessageType.AUTHENTICATION_REQUEST:
                    # Handle Authentication Request
                    from integrated_messages import AuthRequestMessage, AuthenticationResponseMessage
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
                    from integrated_messages import SecurityModeCommandMessage, SecurityModeCompleteMessage
                    self.ciphAlgo, self.ntegAlgo = SecurityModeCommandMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x2
                    message, self.k_nas_int, self.k_nas_enc = SecurityModeCompleteMessage(
                        self.amf_ue_ngap_id, self.kseaf, self.plmn_bcd, self.slices, 
                        self.imeisv, self.supi.encode(), self.tac, self.ABBA, 
                        self.ciphAlgo, self.ntegAlgo, ran_ue_ngap_id=self.ran_ue_ngap_id
                    )
                    messages.append(message)
                    
                elif message_type == MessageType.CONFIGURATION_UPDATE_COMMNAD:
                    # Handle Configuration Update Command
                    from integrated_messages import ConfigurationUpdateMessage
                    ConfigurationUpdateMessage(pdu_dict)
                    time.sleep(0.05)
                    
            elif procedureCode == ProcedureCode.ID_INITIAL_CONTEXT_SETUP:
                if message_type == MessageType.REGISTRATION_ACCEPT:
                    # Handle Registration Accept
                    from integrated_messages import InitialContextSetupRequestMessage, InitialContextSetupResponseMessage, RegistrationCompleteMessage
                    self.ue_5g_guti = InitialContextSetupRequestMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x4
                    self.registered = True
                    
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
                    message = self.send_pdusession_establishment_request(self.dnn)
                    messages.append(message)
                    
                    logger.info(f"✓ UE {self.supi} registered successfully")
                    
                else:
                    logger.warn(f"Unknown or Unsupported message type: {message_type}")
                    
            elif procedureCode == ProcedureCode.ID_PDU_SESSION_RESOURCE_SETUP:
                if message_type == MessageType.DL_NAS_TRANSPORT:
                    # Handle PDU Session Resource Setup Request
                    from integrated_messages import PDUSessionResourceSetupRequestMessage, PDUSessResourceSetupResponseMessage
                    ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID = PDUSessionResourceSetupRequestMessage(pdu_dict)
                    self.ue_state = self.ue_state | 0x8
                    
                    # Configure DNN session
                    self._configure_dnn_session(
                        ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID
                    )
                    
                    # Send PDU Session Resource Setup Response
                    message = PDUSessResourceSetupResponseMessage(
                        self.amf_ue_ngap_id, qosFlowIdentifier, self.plmn_bcd, 
                        gnb_ip=self.gnb_address, gnb_teid=2, ran_ue_ngap_id=self.ran_ue_ngap_id, 
                        tac=self.tac
                    )
                    messages.append(message)
                    
                    logger.info(f"✓ UE {self.supi} PDU session established: IPv4={ipv4_str}")
                    
                elif message_type == MessageType.SERVICE_ACCEPT:
                    # Handle Service Accept
                    from integrated_messages import ServiceAcceptMessage, InitialContextSetupResponseMessage2
                    self.amf_ue_ngap_id = ServiceAcceptMessage(pdu_dict)
                    message = InitialContextSetupResponseMessage2(
                        self.amf_ue_ngap_id, self.ran_ue_ngap_id, self.gnb_address, 
                        self.dnn_internet_qos, self.dnn_internet_pdu_sess_id, self.dnn_gtp_teid
                    )
                    messages.append(message)
                    self.ue_release_enabled = True
                    
                else:
                    logger.warn(f"Unknown or Unsupported message type: {message_type}")
                    
            elif procedureCode == ProcedureCode.ID_LOCATION_REPORTING_CONTROL:
                # Handle Location Reporting Control
                from integrated_messages import LocationReportingControlMessage
                LocationReportingControlMessage(pdu_dict)
                
            elif procedureCode == ProcedureCode.ID_UE_CONTEXT_RELEASE:
                # Handle UE Context Release Command
                from integrated_messages import UEContextReleaseCommandMessage, UEContextReleaseCompleteMessage
                self.amf_ue_ngap_id, self.ran_ue_ngap_id = UEContextReleaseCommandMessage(pdu_dict)
                message = UEContextReleaseCompleteMessage(
                    self.amf_ue_ngap_id, self.ran_ue_ngap_id, self.plmn_bcd, 
                    self.tac, self.gnb_nr_cell_id
                )
                messages.append(message)
                self.ue_release_enabled = False
                
        return self, messages

    def _extract_message_type(self, pdu_dict):
        """Extract the NAS message type from the NGAP PDU."""
        nas_pdu = ""
        protocolIEs = pdu_dict['value'][1]['protocolIEs']
        
        for ie in protocolIEs:
            if ie['value'][0] == 'NAS-PDU':
                nas_pdu = ie['value'][1]
                break
            if ie['value'][0] == 'PDUSessionResourceSetupListSUReq':
                nas_pdu = ie["value"][1][0]['pDUSessionNAS-PDU']
                
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

    def _configure_dnn_session(self, ipv4_str, gTP_TEID, qosFlowIdentifier, SNSSAI, DNN, PDUSessID):
        """Configure DNN session based on the returned DNN value and store session information."""
        if isinstance(DNN, bytes):
            DNN = DNN.decode('utf-8', errors='ignore')
            
        # Convert TEID to hexadecimal string format as requested
        teid_hex = gTP_TEID.hex()
        
        # Create session information entry
        session_entry = {
            'imsi': self.supi,
            'dnn': DNN,
            'ipv4': ipv4_str,
            'ipv6': None,  # IPv6 is not provided in current implementation, could be added if available
            'teid': teid_hex,
            'qos_flow_id': qosFlowIdentifier,
            'pdu_session_id': PDUSessID,
            'snssai': SNSSAI
        }
        
        # Store session info by DNN
        self.session_info[DNN] = session_entry
        
        if DNN == self.dnn.decode('utf-8'):  # "internet"
            self.dnn_ipv4 = ipv4_str
            self.dnn_ipv6 = None  # Not provided in current implementation
            self.dnn_gtp_teid = teid_hex
            self.dnn_internet_connected = True
            self.dnn_internet_qos = qosFlowIdentifier
            self.dnn_internet_pdu_sess_id = PDUSessID
            logger.debug(f"Configured internet DNN session - IMSI: {self.supi}, DNN: {DNN}, IPv4: {ipv4_str}, TEID: {teid_hex}")
        elif DNN == self.dnn2.decode('utf-8'):  # "ims"
            self.dnn2_ipv4 = ipv4_str
            self.dnn2_ipv6 = None  # Not provided in current implementation
            self.dnn2_gtp_teid = teid_hex
            self.dnn2_ims_connected = True
            self.dnn2_ims_qos = qosFlowIdentifier
            self.dnn2_ims_pdu_sess_id = PDUSessID
            logger.debug(f"Configured IMS DNN session - IMSI: {self.supi}, DNN: {DNN}, IPv4: {ipv4_str}, TEID: {teid_hex}")
        else:
            logger.warn(f"Unknown DNN received: {DNN}")
            
        # Log comprehensive session information after each session establishment
        self._log_session_info()
    
    def _log_session_info(self):
        """Log session information in the requested format after session establishment."""
        # Build the log message
        log_msg = f"PDU Session Establishment Complete - IMSI: {self.supi};"
        
        # Add DNN1 (internet) information if available
        if self.dnn_internet_connected:
            dnn1_ipv4 = self.dnn_ipv4 or "N/A"
            dnn1_ipv6 = self.dnn_ipv6 or "N/A" 
            dnn1_teid = self.dnn_gtp_teid or "N/A"
            log_msg += f"DNN1 (internet): IPv4={dnn1_ipv4}, IPv6={dnn1_ipv6}, TEID={dnn1_teid};"
        else:
            log_msg += "DNN1 (internet): Not established;"
            
        # Add DNN2 (ims) information if available  
        if self.dnn2_ims_connected:
            dnn2_ipv4 = self.dnn2_ipv4 or "N/A"
            dnn2_ipv6 = self.dnn2_ipv6 or "N/A"
            dnn2_teid = self.dnn2_gtp_teid or "N/A"
            log_msg += f"DNN2 (ims): IPv4={dnn2_ipv4}, IPv6={dnn2_ipv6}, TEID={dnn2_teid};"
        else:
            log_msg += "DNN2 (ims): Not established;"
            
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
        from integrated_messages import InitialUEMessage, bcd
        imsi_bcd = bcd(self.imsi_suffix10)
        message = InitialUEMessage(
            self.plmn_bcd, self.tac, imsi_bcd, 
            ran_ue_ngap_id=self.ran_ue_ngap_id
        )
        return message
    
    def send_service_request(self):
        """Send Service Request message."""
        from integrated_messages import ServiceRequestMessage
        message = ServiceRequestMessage(
            self.plmn_bcd, self.tac, self.ue_5g_guti, self.k_nas_enc, 
            self.k_nas_int, self.ciphAlgo, self.ntegAlgo, 
            self.gnb_nr_cell_id, self.ran_ue_ngap_id
        )
        return message

    def release_ue_context(self):
        """Send UE Context Release Request."""
        from integrated_messages import UEContextReleaseRequestMessage
        message = UEContextReleaseRequestMessage(
            self.amf_ue_ngap_id, self.ran_ue_ngap_id
        )
        return message

    def send_pdusession_establishment_request(self, dnn):
        """Send PDU Session Establishment Request."""
        from integrated_messages import PDUSessionEstablishmentRequestMessage
        message = PDUSessionEstablishmentRequestMessage(
            self.amf_ue_ngap_id, self.k_nas_int, self.k_nas_enc, 
            self.plmn_bcd, slices=self.slices, dnn=dnn, 
            ran_ue_ngap_id=self.ran_ue_ngap_id, tac=self.tac, 
            ciphAlgo=self.ciphAlgo, ntegAlgo=self.ntegAlgo, 
            gnb_id=self.gnb_nr_cell_id
        )
        return message
    
    def __repr__(self):
        return f"IntegratedUE(imsi={self.imsi_suffix10}, ran_ue_ngap_id={self.ran_ue_ngap_id}, amf_ue_ngap_id={self.amf_ue_ngap_id})"