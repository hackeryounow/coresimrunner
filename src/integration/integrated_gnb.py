#!/usr/bin/env python3
"""
Integrated gNB - Combined gNodeB simulator with UE management for multi-UE testing.

This module integrates the gNB and UE simulation logic from 5gregpdu into CoreSimRunner,
enabling concurrent multi-UE registration and PDU session establishment testing.
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

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import queue
import threading
import socket
import struct
import sctp
from typing import List, Dict, Optional
from tqdm import tqdm
from loguru import logger

# NGAP requires SCTP PPID = 60 per 3GPP TS 38.412
NGAP_PPID = 60

# Import required modules from 5gregpdu structure
try:
    from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please run: bash setup.sh")
    sys.exit(1)

from integrated_messages import NGAPSetupReqeust
from integrated_messages import ProcedureCode
from integrated_ue import IntegratedUE


class IntegratedGNB:
    """
    Integrated gNodeB simulator with UE management.
    
    This class combines the gNB functionality from 5gregpdu/nr.py with
    enhanced multi-UE concurrent testing capabilities for CoreSimRunner.
    """
    
    def __init__(self, 
                 mcc: str,
                 mnc: str,
                 slices: Dict,
                 gnb_address: str,
                 amf_address: str,
                 amf_port: int = 38412,
                 tac: str = "000001",
                 gnb_id: int = 513,
                 gnb_id_len: int = 32,
                 gnb_nr_cell_id: int = 1,
                 gnb_name: str = "gnb1",
                 start_suffix10: str = "0000000001",
                 number_of_ues: int = 1,
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 dnn: str = "internet",
                 imeisv: str = "4370816125816151",
                 op: bool = False,
                 ABBA: bytes = b"\x00\x00",
                 ciphAlgo: int = 0,
                 ntegAlgo: int = 2,
                 logging_level: str = 'INFO',
                 enable_ims: bool = False):
        """
        Initialize the integrated gNB simulator.
        
        Args:
            mcc: Mobile Country Code
            mnc: Mobile Network Code
            slices: Network slice configuration {"SST": 1, "SD": optional}
            gnb_address: gNodeB IP address
            amf_address: AMF IP address
            amf_port: AMF SCTP port (default: 38412)
            tac: Tracking Area Code
            gnb_id: gNodeB ID
            gnb_id_len: gNodeB ID length
            gnb_nr_cell_id: NR Cell ID
            gnb_name: gNodeB name
            start_suffix10: Starting IMSI suffix (10 digits)
            number_of_ues: Number of UEs to simulate
            ki: Subscriber authentication key (hex string)
            opc: Operator ciphered variant (hex string)
            dnn: Data Network Name
            imeisv: IMEI Software Version
            op: Use OP instead of OPC
            ABBA: Authentication Bearer Binding Assurance
            ciphAlgo: Ciphering algorithm
            ntegAlgo: Integrity algorithm
            logging_level: Logging level
        """
        # Network configuration
        self.mcc = mcc
        self.mnc = mnc
        self.slices = slices
        self.gnb_address = gnb_address
        self.amf_address = amf_address
        self.amf_port = amf_port
        self.tac = tac
        self.gnb_id = gnb_id
        self.gnb_id_len = gnb_id_len
        self.gnb_nr_cell_id = gnb_nr_cell_id
        self.gnb_name = gnb_name
        
        # UE configuration
        self.start_suffix10 = start_suffix10
        self.number_of_ues = number_of_ues
        self.ki = ki
        self.opc = opc
        self.op = op
        self.dnn = dnn
        self.imeisv = imeisv
        self.ABBA = ABBA
        self.ciphAlgo = ciphAlgo
        self.ntegAlgo = ntegAlgo
        self.logging_level = logging_level
        self.enable_ims = enable_ims
        
        # Internal state
        self.gnb_amf = None
        self.ues = []
        self.ue_lock = threading.Lock()
        self.socket_lock = threading.Lock()
        self.message_queue = queue.Queue()
        self.running = True
        self.ran_ue_ngap_idx = 1
        
        # SCTP socket and PDU
        self.sctp_socket = None
        self.PDU = NGAP_PDU_Descriptions.NGAP_PDU
        
        # Threads
        self.message_thread = None
        self.sender_thread = None
        
        # Thread pool for message handling
        self.executor = None
        
        # Configure logging
        self._setup_logging(logging_level)
        
        # Setup gNB connection
        self._setup_gnb()
        
        # Start message processing threads
        self._start_threads()

    def _setup_logging(self, logging_level):
        """Configure logging for the gNB."""
        logger.remove()
        logger.add(
            sink=sys.stdout,
            level=logging_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )

    def run(self):
        """Start the gNB and initialize UEs."""
        self._initialize_ues()

    def _initialize_ues(self):
        """Initialize all UEs and send initial messages."""
        start_suffix10 = int(self.start_suffix10)
        logger.info(f"Initializing {self.number_of_ues} UEs...")
        
        for idx, ueid in tqdm(enumerate(range(start_suffix10, start_suffix10 + self.number_of_ues)), desc="Initializing UEs"):
            # Generate IMEI SV for this UE
            current_imeisv = '{:016d}'.format(ueid)
            
            ue = IntegratedUE(
                mcc=self.mcc, 
                mnc=self.mnc, 
                imsi_suffix10='{:010d}'.format(ueid), 
                ran_ue_ngap_id=idx + 1, 
                gnb_nr_cell_id=self.gnb_nr_cell_id, 
                gnb_address=self.gnb_address, 
                slices=self.slices,
                ki=self.ki, 
                opc=self.opc, 
                tac=self.tac, 
                dnn=self.dnn, 
                imeisv=current_imeisv,
                op=self.op,
                ABBA=self.ABBA,
                ciphAlgo=self.ciphAlgo,
                ntegAlgo=self.ntegAlgo,
                logging_level=self.logging_level,
                enable_ims=self.enable_ims
            )
            self.ran_ue_ngap_idx += 1
            with self.ue_lock:
                self.ues.append(ue)
            # Small delay to avoid overwhelming the AMF
            time.sleep(0.002)
        
        logger.info(f"{len(self.ues)} UEs initialized")
        
        # Send initial UE messages
        for ue in self.ues:
            initial_message = ue.send_initial_ue_message()
            self.message_queue.put(initial_message)

    def _setup_gnb(self):
        """Setup gNB connection to AMF."""
        try:
            self.sctp_socket = sctp.sctpsocket_tcp(socket.AF_INET)
            self.sctp_socket.bind((self.gnb_address, 0))
            self.sctp_socket.connect((self.amf_address, self.amf_port))
            
            # Send NG Setup Request
            self.PDU.set_val(NGAPSetupReqeust(
                self.mcc + self.mnc, 
                self.gnb_name, 
                self.gnb_id, 
                self.gnb_id_len, 
                tac=self.tac, 
                sst=self.slices["SST"], 
                sd=self.slices.get("SD", None)
            ))
            self.sctp_socket.sctp_send(self.PDU.to_aper(), ppid=socket.htonl(60))
            
            # Receive NG Setup Response
            data = self.sctp_socket.recv(4096)
            if not data:
                raise Exception("No response from AMF")
                
            self.PDU.from_aper(data)
            _, pdu_dict = self.PDU()
            self.process_ngap_setup_response(pdu_dict)
            logger.info(f"GNB connected to AMF: {self.gnb_amf}")
            
        except Exception as e:
            logger.error(f"Failed to setup gNB connection: {e}")
            raise

    def _set_stream(self, stream):    
        """Set SCTP stream (placeholder for future use)."""
        try:
            sctp_default_send_param = bytearray(self.sctp_socket.getsockopt(132,10,32))
            sctp_default_send_param[0] = stream
            self.sctp_socket.setsockopt(132, 10, sctp_default_send_param)
        except:
            pass  # SCTP options may not be available on all systems

    def process_ngap_setup_response(self, pdu_dict):
        """Process NG Setup Response from AMF."""
        protocolIEs_list = pdu_dict['value'][1]['protocolIEs']
        self.gnb_amf = GNBAMF(protocolIEs_list)

    def send_message(self, message):
        """Send NGAP message to AMF."""
        try:
            self.PDU.set_val(message)
            self.sctp_socket.sctp_send(self.PDU.to_aper(), ppid=socket.htonl(60))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def _start_threads(self):
        """Start message processing threads."""
        self.message_thread = threading.Thread(target=self._acceptor)
        self.message_thread.daemon = True
        self.message_thread.start()
        
        self.sender_thread = threading.Thread(target=self._sender)
        self.sender_thread.daemon = True
        self.sender_thread.start()

    def _acceptor(self):
        """Accept and process incoming messages from AMF."""
        while self.running:
            try:
                data = self.sctp_socket.recv(4096)
                if not data:
                    break
                
                # Properly decode NGAP PDU to extract RAN UE NGAP ID
                PDU = NGAP_PDU_Descriptions.NGAP_PDU
                PDU.from_aper(data)
                type_t, pdu_dict = PDU()
                
                procedure_code = pdu_dict['procedureCode']
                
                # Skip error indications and paging
                try:
                    proc = ProcedureCode(procedure_code)
                    if proc in (ProcedureCode.ID_ERROR_INDICATION, ProcedureCode.ID_PAGING):
                        continue
                except ValueError:
                    pass
                
                protocol_ies = pdu_dict['value'][1]['protocolIEs']
                ran_ue_ngap_id = self._extract_ran_ue_ngap_id_from_ies(protocol_ies)
                if ran_ue_ngap_id is None:
                    continue
                
                # Convert to 0-based UE index
                idx = ran_ue_ngap_id - 1
                
                # Handle message in separate thread
                handler_thread = threading.Thread(
                    target=self._ngap_message_handler, 
                    args=(data, idx)
                )
                handler_thread.daemon = True
                handler_thread.start()
                
            except Exception as e:
                if self.running:
                    logger.error(f"Error in acceptor: {e}")
                break

    def _sender(self):
        """Send queued messages to AMF."""
        while self.running:
            try:
                message = self.message_queue.get(timeout=1)
                self.send_message(message)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in sender: {e}")

    def _ngap_message_handler(self, data, idx):
        """Handle NGAP message for specific UE."""
        if idx < 0 or idx >= len(self.ues):
            logger.warning(f"Invalid UE index: {idx}")
            return
            
        try:
            PDU = NGAP_PDU_Descriptions.NGAP_PDU
            PDU.from_aper(data)
            type_t, pdu_dict = PDU()
            
            with self.socket_lock:
                ue, messages = self.ues[idx].handle_message(type_t, pdu_dict)
                self.ues[idx] = ue
                
                for message in messages:
                    self.message_queue.put(message)
                    
        except Exception as e:
            logger.error(f"Error handling message for UE {idx}: {e}")

    def _extract_ran_ue_ngap_id_from_ies(self, protocol_ies):
        """Extract RAN UE NGAP ID from decoded NGAP protocol IEs.
        
        Handles both direct RAN-UE-NGAP-ID (id=85) and nested
        UE-NGAP-IDs (id=114) used in UEContextReleaseCommand.
        """
        try:
            for ie in protocol_ies:
                # Direct RAN-UE-NGAP-ID
                if ie['id'] == 85:
                    return ie['value'][1]
                # UE-NGAP-IDs (contains AMF-UE-NGAP-ID and RAN-UE-NGAP-ID pair)
                if ie['id'] == 114:
                    ue_ngap_ids = ie['value']
                    if isinstance(ue_ngap_ids, tuple) and len(ue_ngap_ids) == 2:
                        if ue_ngap_ids[0] == 'uE-NGAP-ID-pair':
                            return ue_ngap_ids[1].get('rAN-UE-NGAP-ID')
            logger.warning(f"RAN-UE-NGAP-ID not found (IE IDs: {[ie['id'] for ie in protocol_ies]})")
            return None
        except (KeyError, IndexError, TypeError) as e:
            logger.warning(f"Failed to extract RAN UE NGAP ID: {e}")
            return None

    def close(self):
        """Close gNB connection."""
        self.running = False
        if self.sctp_socket:
            try:
                self.sctp_socket.shutdown(socket.SHUT_RDWR)
                self.sctp_socket.close()
            except:
                pass


class GNBAMF:
    """AMF information from NG Setup Response."""
    
    def __init__(self, protocolIEs_list):
        self.amf_name = None
        self.guami = None
        self.amf_region_id = None
        self.amf_region_id_len = None
        self.amf_set_id = None
        self.amf_set_id_len = None
        self.amf_pointer = None
        self.amf_pointer_len = None
        self.relative_amf_capacity = None
        self._parse_protocolIEs(protocolIEs_list)

    def _parse_protocolIEs(self, protocolIEs_list):
        for ie in protocolIEs_list:
            if ie['value'][0] == 'AMFName':
                self.amf_name = ie['value'][1]
            elif ie['value'][0] == 'ServedGUAMIList':
                guami = ie['value'][1][0]['gUAMI']
                from integrated_messages import plmn_bcd_decode
                self.guami = plmn_bcd_decode(guami['pLMNIdentity'])
                self.amf_region_id = guami['aMFRegionID'][0]
                self.amf_region_id_len = guami['aMFRegionID'][0]
                self.amf_set_id = guami['aMFSetID'][0]
                self.amf_set_id_len = guami['aMFSetID'][1]
                self.amf_pointer = guami['aMFPointer'][0]
                self.amf_pointer_len = guami['aMFPointer'][1]
            elif ie['value'][0] == 'RelativeAMFCapacity':
                self.relative_amf_capacity = ie['value'][1]

    def __str__(self):
        return f"AMF Name: {self.amf_name}, GUAMI: {self.guami}, AMF Region ID: {self.amf_region_id}, " \
               f"AMF Set ID: {self.amf_set_id}, AMF Pointer: {self.amf_pointer}, Relative Capacity: {self.relative_amf_capacity}"