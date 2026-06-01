#!/usr/bin/env python3
"""
Integrated 4G eNodeB for LTE network simulation.

This module simulates an LTE base station (eNodeB) using an acceptor/sender threading model
(mirroring IntegratedGNB from integrated_gnb.py). The acceptor receives S1AP messages from
the MME, routes them to the correct UE via handle_message(), and queues all responses for
the sender thread to transmit.
"""

import sys
import os
import socket
import struct
import threading
import time
import queue
from typing import List, Dict, Optional, Any
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
except ImportError as e:
    print(f"Error importing required packages: {e}")
    print("Please run: bash setup.sh")
    sys.exit(1)

from integrated_4g_ue import Integrated4GUE
from integrated_4g_messages import (
    return_plmn_s1ap, S1SetupRequest, S1SetupResponseProcessing,
)


class Integrated4GGNB:
    """
    Simulated eNodeB for 4G network testing.

    Architecture (mirrors IntegratedGNB):
        - _acceptor() receives SCTP data from MME, extracts ENB-UE-S1AP-ID, dispatches handler
        - _s1ap_message_handler(data, ue_idx) decodes PDU, calls ue.handle_message(), queues responses
        - _sender() reads from message_queue, encodes PDU, sends via SCTP
    """

    def __init__(self,
                 mcc: str = "460",
                 mnc: str = "99",
                 enb_name: str = "4G-Sim-eNB",
                 enb_ip: str = "192.168.55.9",
                 mme_ip: str = "192.168.55.53",
                 mme_port: int = 36412,
                 enb_id: int = 1,
                 enb_cell_id: int = 1000000,
                 tac: str = "0001",
                 plmn: str = "46099",
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 apn: str = "internet",
                 number_of_ues: int = 1,
                 start_imsi: str = "0000000001",
                 imeisv: str = "4370816125816151",
                 op: bool = False,
                 attach_type: int = 1,
                 pdp_type: int = 1,
                 log_level: str = "INFO",
                 config_loader: Optional[Any] = None):
        # Network configuration
        self.mcc = mcc
        self.mnc = mnc
        self.enb_name = enb_name
        self.enb_ip = enb_ip
        self.mme_ip = mme_ip
        self.mme_port = mme_port
        self.enb_id = enb_id
        self.enb_cell_id = enb_cell_id
        self.tac = tac
        self.plmn = plmn
        self.ki = ki
        self.opc = opc
        self.apn = apn
        self.number_of_ues = number_of_ues
        self.start_imsi = start_imsi
        self.imeisv = imeisv
        self.op = op
        self.attach_type = attach_type
        self.pdp_type = pdp_type
        self.log_level = log_level
        self.config_loader = config_loader

        # Internal state
        self.ues: List[Integrated4GUE] = []
        self.ue_lock = threading.Lock()
        self.socket_lock = threading.Lock()
        self.message_queue = queue.Queue()
        self.running = True

        # ENB-UE-S1AP-ID -> UE index mapping
        self.enb_ue_id_to_idx: Dict[int, int] = {}

        # S1AP PDU
        self.sctp_socket = None
        self.PDU = S1AP.S1AP_PDU_Descriptions.S1AP_PDU

        # MME info (from S1 Setup Response)
        self.mme_name = ""
        self.mme_plmn = b""
        self.mme_group_id = b""
        self.mme_code = b""
        self.mme_relative_capacity = 0

        # Threads
        self.acceptor_thread = None
        self.sender_thread = None

        # Configure logging
        self._setup_logging()

        # Setup eNB connection to MME
        self._setup_enb()

        # Start acceptor/sender threads
        self._start_threads()

    def _setup_logging(self):
        """Configure logging."""
        logger.remove()
        logger.add(
            sink=sys.stdout,
            level=self.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )

    # ------------------------------------------------------------------
    # S1 Setup
    # ------------------------------------------------------------------

    def _setup_enb(self):
        """Create SCTP socket, connect to MME, perform S1 Setup."""
        try:
            self.sctp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_SCTP)
            self.sctp_socket.bind((self.enb_ip, 0))

            # Set SCTP default send params
            try:
                sctp_default_send_param = bytearray(self.sctp_socket.getsockopt(132, 10, 32))
                sctp_default_send_param[11] = 18
                self.sctp_socket.setsockopt(132, 10, sctp_default_send_param)
            except Exception:
                pass

            self.sctp_socket.connect((self.mme_ip, self.mme_port))
            logger.info(f"eNB connected to MME at {self.mme_ip}:{self.mme_port}")

            self._send_s1_setup_request()

        except Exception as e:
            logger.error(f"Failed to setup eNodeB connection: {e}")
            raise

    def _send_s1_setup_request(self):
        """Send S1 Setup Request and process the response."""
        try:
            plmn_bcd = return_plmn_s1ap(self.plmn)
            # Convert TAC to 2-byte value (supports 2, 4, or 6 hex char strings)
            if isinstance(self.tac, str):
                tac_int = int(self.tac, 16)
            elif isinstance(self.tac, bytes):
                tac_int = int.from_bytes(self.tac, 'big')
            else:
                tac_int = int(self.tac)
            tac1_bytes = struct.pack('!H', tac_int & 0xFFFF)
            tac2_bytes = struct.pack('!H', (tac_int + 2) & 0xFFFF)

            dic = {
                'ENB-PLMN': plmn_bcd,
                'ENB-NAME': self.enb_name,
                'ENB-ID': self.enb_id,
                'ENB-TAC1': tac1_bytes,
                'ENB-TAC2': tac2_bytes,
                'ENB-TAC-NBIOT': tac1_bytes,
                'S1-TYPE': '4G',
            }
            pdu_value = S1SetupRequest(dic)

            self.PDU.set_val(pdu_value)
            msg = self.PDU.to_aper()
            self.sctp_socket.send(msg)
            logger.info(f"S1 Setup Request sent from {self.enb_name}")

            # Receive S1 Setup Response
            raw = self.sctp_socket.recv(4096)
            if not raw:
                raise Exception("No S1 Setup Response received")

            self.PDU.from_aper(raw)
            decoded = self.PDU.get_val()
            protocol_ies = decoded[1]['value'][1]['protocolIEs']

            result = S1SetupResponseProcessing(protocol_ies, {
                'MME-NAME': '', 'MME-PLMN': b'', 'MME-GROUP-ID': b'',
                'MME-CODE': b'', 'MME-RELATIVE-CAPACITY': 0, 'STATE': 0,
            })
            self.mme_name = result['MME-NAME']
            self.mme_plmn = result['MME-PLMN']
            self.mme_group_id = result['MME-GROUP-ID']
            self.mme_code = result['MME-CODE']
            self.mme_relative_capacity = result['MME-RELATIVE-CAPACITY']

            logger.info(f"S1 Setup successful - MME: {self.mme_name}, PLMN: {self.plmn}")

        except Exception as e:
            logger.error(f"S1 Setup failed: {e}")
            raise

    # ------------------------------------------------------------------
    # UE Lifecycle
    # ------------------------------------------------------------------

    def run(self):
        """Start the eNB: create UEs and send Initial UE Messages."""
        self._create_ues()

    def _create_ues(self):
        """Create UE instances and queue Initial UE Messages."""
        start_imsi_int = int(self.start_imsi)
        logger.info(f"Creating {self.number_of_ues} UEs starting from IMSI suffix {self.start_imsi}")

        for idx in range(self.number_of_ues):
            imsi = str(start_imsi_int + idx).zfill(10)
            enb_ue_s1ap_id = 1000 + idx

            # Generate IMEISV for this UE
            current_imeisv = '{:016d}'.format(start_imsi_int + idx)

            ue = Integrated4GUE(
                mcc=self.mcc,
                mnc=self.mnc,
                imsi_suffix10=imsi,
                enb_ue_s1ap_id=enb_ue_s1ap_id,
                enb_address=self.enb_ip,
                mme_address=self.mme_ip,
                ki=self.ki,
                opc=self.opc,
                apn=self.apn,
                tac=self.tac,
                plmn=self.plmn,
                imeisv=current_imeisv,
                op=self.op,
                attach_type=self.attach_type,
                pdp_type=self.pdp_type,
                enb_cell_id=self.enb_cell_id,
                logging_level=self.log_level,
            )

            with self.ue_lock:
                self.ues.append(ue)
                self.enb_ue_id_to_idx[enb_ue_s1ap_id] = idx

            logger.debug(f"Created UE: IMSI={ue.supi}, ENB-UE-S1AP-ID={enb_ue_s1ap_id}")
            time.sleep(0.002)

        logger.info(f"{len(self.ues)} UEs created")

        # Send Initial UE Messages
        self._send_initial_ue_messages()

    def _send_initial_ue_messages(self):
        """Queue Initial UE Messages for all UEs."""
        for ue in self.ues:
            try:
                pdu_value = ue.send_initial_ue_message()
                if pdu_value:
                    self.message_queue.put(pdu_value)
                    logger.info(f"Queued Initial UE Message for {ue.supi}")
                else:
                    logger.warning(f"Failed to create Initial UE Message for {ue.supi}")
            except Exception as e:
                logger.error(f"Error queuing Initial UE Message for {ue.supi}: {e}")

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------

    def _start_threads(self):
        """Start acceptor and sender threads."""
        self.acceptor_thread = threading.Thread(target=self._acceptor)
        self.acceptor_thread.daemon = True
        self.acceptor_thread.start()

        self.sender_thread = threading.Thread(target=self._sender)
        self.sender_thread.daemon = True
        self.sender_thread.start()

    def _acceptor(self):
        """
        Receive S1AP messages from MME, decode to find UE, dispatch to handler thread.
        Mirrors IntegratedGNB._acceptor().
        """
        while self.running:
            try:
                data = self.sctp_socket.recv(8192)
                if not data:
                    break

                logger.debug(f"Acceptor: received {len(data)} bytes from MME")

                # Decode to find ENB-UE-S1AP-ID for routing
                PDU = S1AP.S1AP_PDU_Descriptions.S1AP_PDU
                PDU.from_aper(data)
                type_t, pdu_dict = PDU()

                procedure = pdu_dict['value'][0]
                logger.debug(f"Acceptor: decoded {type_t}/{procedure}")

                ue_idx = self._find_ue_index(pdu_dict)
                if ue_idx is None:
                    logger.warning(f"Acceptor: could not route {procedure} to any UE")
                    continue

                # Handle in a separate thread
                handler = threading.Thread(
                    target=self._s1ap_message_handler,
                    args=(data, ue_idx),
                )
                handler.daemon = True
                handler.start()

            except Exception as e:
                if self.running:
                    logger.error(f"Error in acceptor: {e}")
                    import traceback; traceback.print_exc()
                break

    def _find_ue_index(self, pdu_dict):
        """
        Extract ENB-UE-S1AP-ID from a decoded S1AP PDU and map to UE index.

        Works for DownlinkNASTransport, InitialContextSetupRequest, E-RABSetupRequest,
        and UEContextReleaseCommand.
        """
        try:
            protocol_ies = pdu_dict['value'][1]['protocolIEs']
        except (KeyError, IndexError, TypeError):
            return None

        enb_ue_s1ap_id = None
        mme_ue_s1ap_id = None

        for ie in protocol_ies:
            if ie['id'] == 8:   # ENB-UE-S1AP-ID
                enb_ue_s1ap_id = ie['value'][1]
                break
            elif ie['id'] == 0:  # MME-UE-S1AP-ID (fallback)
                mme_ue_s1ap_id = ie['value'][1]

        if enb_ue_s1ap_id is not None:
            idx = self.enb_ue_id_to_idx.get(enb_ue_s1ap_id)
            if idx is not None:
                return idx

        # Fallback: try to find UE by MME-UE-S1AP-ID
        if mme_ue_s1ap_id is not None:
            with self.ue_lock:
                for i, ue in enumerate(self.ues):
                    if ue.mme_ue_s1ap_id == mme_ue_s1ap_id:
                        return i

        logger.warning(f"Could not route S1AP message to any UE "
                       f"(ENB-UE-S1AP-ID={enb_ue_s1ap_id}, MME-UE-S1AP-ID={mme_ue_s1ap_id})")
        return None

    def _s1ap_message_handler(self, data, ue_idx):
        """
        Decode S1AP PDU, call ue.handle_message(), queue all response PDUs.
        Mirrors IntegratedGNB._ngap_message_handler().
        """
        if ue_idx < 0 or ue_idx >= len(self.ues):
            logger.warning(f"Invalid UE index: {ue_idx}")
            return

        try:
            PDU = S1AP.S1AP_PDU_Descriptions.S1AP_PDU
            PDU.from_aper(data)
            type_t, pdu_dict = PDU()

            procedure = pdu_dict['value'][0]
            protocol_ies = pdu_dict['value'][1]['protocolIEs']

            with self.ue_lock:
                ue, messages = self.ues[ue_idx].handle_message(type_t, procedure, protocol_ies)
                self.ues[ue_idx] = ue

                logger.debug(f"UE {ue_idx} handler for {procedure} returned {len(messages)} response(s)")
                for message in messages:
                    self.message_queue.put(message)

        except Exception as e:
            logger.error(f"Error handling S1AP message for UE {ue_idx}: {e}")
            import traceback; traceback.print_exc()

    def _sender(self):
        """
        Send queued S1AP PDU value tuples via SCTP.
        Mirrors IntegratedGNB._sender().
        """
        while self.running:
            try:
                message = self.message_queue.get(timeout=1)
                PDU = S1AP.S1AP_PDU_Descriptions.S1AP_PDU
                PDU.set_val(message)
                encoded = PDU.to_aper()
                logger.debug(f"Sender: sending PDU procedure={message[1].get('value', ('?',))[0]}, {len(encoded)} bytes")
                with self.socket_lock:
                    self.sctp_socket.send(encoded)
            except queue.Empty:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Error in sender: {e}")
                    import traceback; traceback.print_exc()

    # ------------------------------------------------------------------
    # Stats and Cleanup
    # ------------------------------------------------------------------

    def get_registration_stats(self):
        """Get registration statistics for all UEs."""
        stats = {
            "total": len(self.ues),
            "registered": 0,
            "pdn_connected": 0,
        }
        with self.ue_lock:
            for ue in self.ues:
                if ue.registered:
                    stats["registered"] += 1
                if ue.pdn_connected:
                    stats["pdn_connected"] += 1
        return stats

    def close(self):
        """Close eNodeB connection and cleanup."""
        self.running = False
        if self.sctp_socket:
            try:
                self.sctp_socket.shutdown(socket.SHUT_RDWR)
                self.sctp_socket.close()
            except Exception:
                pass
        logger.info("eNodeB closed")

    def send_message(self, message):
        """Queue an S1AP PDU value tuple for sending."""
        self.message_queue.put(message)


class Integrated4GMME:
    """MME information from S1 Setup Response."""

    def __init__(self, protocol_ies_list):
        self.mme_name = None
        self.served_plmns = []
        self.mme_group_id = None
        self.mme_code = None
        self.relative_capacity = None
        self._parse_protocol_ies(protocol_ies_list)

    def _parse_protocol_ies(self, protocol_ies_list):
        for ie in protocol_ies_list:
            if ie['value'][0] == 'MMEname':
                self.mme_name = ie['value'][1].decode() if isinstance(ie['value'][1], bytes) else ie['value'][1]
            elif ie['value'][0] == 'ServedGUMMEIs':
                served_gummeis = ie['value'][1][0]
                if 'pLMNidentity' in served_gummeis:
                    self.served_plmns.append(served_gummeis['pLMNidentity'])
                if 'mME-Group-ID' in served_gummeis:
                    self.mme_group_id = served_gummeis['mME-Group-ID']
                if 'mME-Code' in served_gummeis:
                    self.mme_code = served_gummeis['mME-Code']
            elif ie['value'][0] == 'RelativeMMECapacity':
                self.relative_capacity = ie['value'][1]


if __name__ == "__main__":
    gnb = Integrated4GGNB(
        mcc="460",
        mnc="99",
        enb_ip="192.168.55.9",
        mme_ip="192.168.55.53",
        number_of_ues=2,
        start_imsi="1234567890",
    )
    gnb.run()

    try:
        for i in range(60):
            stats = gnb.get_registration_stats()
            logger.info(f"Registration stats: {stats}")
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        gnb.close()
