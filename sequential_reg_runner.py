#!/usr/bin/env python3
"""
Sequential Registration Runner - Chained 2-UE registration with GTP-U tunnel.

Flow:
  Round 1: UE1 registers through the original gNB, establishes PDU session,
           captures assigned IP (IP_A), TEID, and UPF IP.
  Round 2: Use IP_A as a NEW base station.  ALL NGAP messages (including
           NGSetupRequest) are sent ONLY via GTP-U tunnel using UE1's TEID.
           GTP-U packet structure:
             Outer UDP/IP (→UPF:2152)
             GTP-U Header (Flags=0x30, MsgType=0xFF, TEID)
             Inner IP (src=IP_A, dst=AMF, proto=132 SCTP)
             SCTP (src_port→dst_port=38412, DATA chunk PPID=60)
             NGAP APER-encoded message
"""

import sys
import os
import time
import json
import threading
import queue
import socket
import struct
import select
import ipaddress
import sctp
from typing import List, Dict, Optional
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
    from pycrate_asn1dir.NGAP import NGAP_PDU_Descriptions
except ImportError as e:
    print(f"Error importing required packages: {e}")
    sys.exit(1)

from coresimrunner.config_loader import ConfigLoader
from coresimrunner.integration.integrated_messages import (
    NGAPSetupReqeust, ProcedureCode, plmn_bcd_encode, plmn_bcd_decode
)
from coresimrunner.integration.integrated_ue import IntegratedUE

# NGAP SCTP PPID per 3GPP TS 38.412
NGAP_PPID = 60


class GNBAMF:
    """AMF information from NG Setup Response."""

    def __init__(self, protocolIEs_list):
        self.amf_name = None
        self.guami = None
        self.amf_region_id = None
        self.amf_set_id = None
        self.amf_pointer = None
        self._parse(protocolIEs_list)

    def _parse(self, ies):
        for ie in ies:
            if ie['value'][0] == 'AMFName':
                self.amf_name = ie['value'][1]
            elif ie['value'][0] == 'ServedGUAMIList':
                guami = ie['value'][1][0]['gUAMI']
                self.guami = plmn_bcd_decode(guami['pLMNIdentity'])
                self.amf_region_id = guami['aMFRegionID'][0]
                self.amf_set_id = guami['aMFSetID'][0]
                self.amf_pointer = guami['aMFPointer'][0]

    def __str__(self):
        return f"AMF={self.amf_name}, GUAMI={self.guami}"


class SequentialRegRunner:
    """
    Sequential 2-round registration runner.

    Round 1: Register UEs one-by-one, wait for full completion (registration + PDU),
             capture IP, TEID, and UPF IP.
    Round 2: Use UE1's IP_A as new gNB source IP.  All NGAP messages (including
             NGSetupRequest) are sent via GTP-U tunnel with structure:
             Outer UDP/IP → GTP-U → Inner IP(IP_A→AMF) → SCTP → NGAP.
    """

    def __init__(self,
                 mcc: str,
                 mnc: str,
                 gnb_address: str,
                 amf_address: str,
                 amf_port: int = 38412,
                 imsi_list: List[str] = None,
                 ki: str = "12341234123412341234123412340000",
                 opc: str = "71a121bb69baf3c0cc53fb5038a0131f",
                 dnn: str = "internet",
                 tac: str = "000001",
                 gnb_nr_cell_id: int = 1,
                 slices: dict = None,
                 log_level: str = "INFO",
                 gtpu_target_port: int = 2152,
                 round2_gnb_id: int = 514):
        self.mcc = mcc
        self.mnc = mnc
        self.gnb_address = gnb_address
        self.amf_address = amf_address
        self.amf_port = amf_port
        self.imsi_list = imsi_list or ["0000000001", "0000000002"]
        self.ki = ki
        self.opc = opc
        self.dnn = dnn
        self.tac = tac
        self.gnb_nr_cell_id = gnb_nr_cell_id
        self.slices = slices or {"SST": 1}
        self.log_level = log_level
        self.gtpu_target_port = gtpu_target_port
        self.round2_gnb_id = round2_gnb_id  # Different gNB ID for Round 2

        # SCTP / NGAP state
        self.sctp_socket = None
        self.PDU = NGAP_PDU_Descriptions.NGAP_PDU
        self.gnb_amf = None
        self.socket_lock = threading.Lock()
        self.message_queue = queue.Queue()
        self.running = True

        # UE list
        self.ues: List[IntegratedUE] = []

        # Results
        self.results = {
            'round1': [],
            'round2': [],
        }

        # Setup logging
        logger.remove()
        logger.add(
            sink=sys.stdout,
            level=log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )

    # ------------------------------------------------------------------
    # SCTP / NGAP connection
    # ------------------------------------------------------------------
    def _connect(self):
        """Establish SCTP connection and perform NG Setup using default gNB address."""
        logger.info(f"Connecting to AMF at {self.amf_address}:{self.amf_port} (source: {self.gnb_address})")
        self.sctp_socket = sctp.sctpsocket_tcp(socket.AF_INET)
        self.sctp_socket.bind((self.gnb_address, 0))
        self.sctp_socket.connect((self.amf_address, self.amf_port))
        self._do_ng_setup()

    def _connect_with_source_ip(self, source_ip: str):
        """Establish a NEW SCTP connection bound to the given source IP (UE's assigned IP).

        This simulates setting up a base station connection using the UE's previously
        assigned IP address from Round 1.  The old SCTP socket is closed first.
        NG Setup is performed on the new connection.
        """
        # Close old connection
        self._close_sctp()

        logger.info(f"Connecting to AMF at {self.amf_address}:{self.amf_port} "
                    f"(source IP = UE assigned: {source_ip})")
        self.sctp_socket = sctp.sctpsocket_tcp(socket.AF_INET)
        self.sctp_socket.bind((source_ip, 0))
        self.sctp_socket.connect((self.amf_address, self.amf_port))
        self._do_ng_setup()
        return self.sctp_socket

    def _connect_sctp_only(self, source_ip: str):
        """Establish SCTP connection WITHOUT NG Setup (for Round 2 GTP-U mode).

        In Round 2, ALL NGAP messages (including NGSetupRequest) are sent ONLY
        via GTP-U tunnel.  This method just establishes the raw SCTP connection
        for potential downlink reception — no NG Setup is performed here.
        """
        self._close_sctp()

        logger.info(f"SCTP connect (no NGSetup) to AMF at {self.amf_address}:{self.amf_port} "
                    f"(source: {source_ip})")
        self.sctp_socket = sctp.sctpsocket_tcp(socket.AF_INET)
        self.sctp_socket.bind((source_ip, 0))
        self.sctp_socket.connect((self.amf_address, self.amf_port))
        # NO _do_ng_setup() — NGSetup will be sent via GTP-U tunnel only
        logger.info(f"SCTP connection established (NGSetup deferred to GTP-U tunnel)")
        return self.sctp_socket

    def _do_ng_setup(self):
        """Perform NG Setup Request/Response on the current SCTP socket."""
        self.PDU.set_val(NGAPSetupReqeust(
            self.mcc + self.mnc,
            "CoreSim-SeqGNB",
            513, 32,
            tac=self.tac,
            sst=self.slices["SST"],
            sd=self.slices.get("SD", None)
        ))
        self.sctp_socket.sctp_send(self.PDU.to_aper(), ppid=socket.htonl(NGAP_PPID))

        data = self.sctp_socket.recv(4096)
        if not data:
            raise Exception("No NG Setup Response from AMF")
        self.PDU.from_aper(data)
        _, pdu_dict = self.PDU()

        # Validate response type
        pdu_type = pdu_dict.get('value', (None,))[0]
        if pdu_type == 'unsuccessfulOutcome':
            cause_ie = None
            for ie in pdu_dict['value'][1].get('protocolIEs', []):
                if ie['value'][0] == 'Cause':
                    cause_ie = ie['value'][1]
            raise Exception(f"NG Setup FAILED: AMF returned NGSetupFailure, Cause={cause_ie}")

        ies = pdu_dict['value'][1]['protocolIEs']
        self.gnb_amf = GNBAMF(ies)
        logger.info(f"NG Setup OK: {self.gnb_amf}")

    def _send_ngap(self, message):
        """Send an NGAP message to AMF via SCTP."""
        with self.socket_lock:
            self.PDU.set_val(message)
            data = self.PDU.to_aper()
        self.sctp_socket.sctp_send(data, ppid=socket.htonl(NGAP_PPID))

    @staticmethod
    def _crc32c(data: bytes) -> int:
        """Compute CRC32C (Castagnoli) checksum for SCTP.

        Uses the CRC32C polynomial 0x82F63B78 (bit-reversed 0x1EDC6F41).
        """
        crc = 0xFFFFFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0x82F63B78
                else:
                    crc >>= 1
        return crc ^ 0xFFFFFFFF

    def _build_inner_sctp_packet(self, ngap_data, src_ip, dst_ip,
                                  src_port=12345, dst_port=38412,
                                  tsn=1, stream_id=0):
        """Build an inner IP + SCTP DATA chunk packet containing NGAP payload.

        Structure:
          IPv4 Header (20 bytes): src=IP_A, dst=AMF, protocol=132 (SCTP)
          SCTP Common Header (12 bytes): src_port, dst_port, VTag, Checksum
          SCTP DATA Chunk (16+N bytes): Type=0, Flags=0x03, Length, TSN, SID, SSN, PPID, NGAP
        """
        # --- SCTP DATA chunk ---
        chunk_type = 0      # DATA
        chunk_flags = 0x03  # Begin + End (single-segment)
        ppid = NGAP_PPID    # 60 = NGAP
        # Data chunk header: 16 bytes (type+flags+length+tsn+sid+ssn+ppid)
        chunk_header_len = 16
        chunk_length = chunk_header_len + len(ngap_data)
        data_chunk = struct.pack('!BBHIHHI',
            chunk_type, chunk_flags, chunk_length,
            tsn, stream_id, 0,  # TSN, Stream ID, Stream Seq
            ppid
        ) + ngap_data
        # Pad to 4-byte boundary
        pad_len = (4 - len(data_chunk) % 4) % 4
        data_chunk += b'\x00' * pad_len

        # --- SCTP Common Header ---
        # src_port(2) + dst_port(2) + verification_tag(4) + checksum(4) = 12 bytes
        vtag = 0x00000001  # simplified verification tag
        sctp_header = struct.pack('!HHI', src_port, dst_port, vtag)
        sctp_packet = sctp_header + b'\x00\x00\x00\x00' + data_chunk

        # Compute CRC32c checksum over the SCTP packet (with checksum field zeroed)
        crc = self._crc32c(sctp_packet)
        # Replace checksum field (bytes 8-11)
        sctp_packet = sctp_packet[:8] + struct.pack('<I', crc) + sctp_packet[12:]

        # --- IPv4 Header ---
        src_bytes = ipaddress.IPv4Address(src_ip).packed
        dst_bytes = ipaddress.IPv4Address(dst_ip).packed
        total_length = 20 + len(sctp_packet)
        ip_header = struct.pack('!BBHHHBBH4s4s',
            0x45,           # Version=4, IHL=5 (20 bytes)
            0x00,           # DSCP/ECN
            total_length,   # Total length
            0x0001,         # Identification
            0x4000,         # Flags=DF, Fragment offset=0
            64,             # TTL
            132,            # Protocol = SCTP
            0,              # Checksum (0 initially, computed below)
            src_bytes,      # Source IP = IP_A
            dst_bytes       # Destination IP = AMF
        )
        # Compute IP header checksum
        checksum = 0
        for i in range(0, len(ip_header), 2):
            word = (ip_header[i] << 8) + ip_header[i + 1]
            checksum += word
        while checksum >> 16:
            checksum = (checksum & 0xFFFF) + (checksum >> 16)
        ip_header = ip_header[:10] + struct.pack('!H', ~checksum & 0xFFFF) + ip_header[12:]

        return ip_header + sctp_packet

    def _build_gtpu_packet(self, inner_ip_packet, teid, msg_type=0xFF):
        """Build a GTP-U packet wrapping an inner IP packet.

        Structure:
          GTP-U Header (8 bytes): Flags, MsgType, Length, TEID
          Payload: Inner IP packet (IP_A → AMF, SCTP → NGAP)

        GTP-U header per 3GPP TS 29.281:
          Flags(1B): Version=1, PT=1, E=0, S=0, PN=0  => 0x30
          MsgType(1B): 0xFF = G-PDU
          Length(2B): length of payload after this field (i.e., after 8-byte header)
          TEID(4B): Tunnel Endpoint Identifier
        """
        if isinstance(teid, str):
            teid_int = int(teid, 16)
        else:
            teid_int = int(teid)
        flags = 0x30
        # Length = payload length (everything after the 8-byte mandatory header)
        length = len(inner_ip_packet)
        header = struct.pack('!BBHI', flags, msg_type, length, teid_int)
        return header + inner_ip_packet

    def _send_gtpu(self, ngap_message, gtpu_udp_sock, gtpu_target,
                    gtpu_teid, src_ip, tsn_counter):
        """Send an NGAP message ONLY via GTP-U tunnel (no SCTP path).

        Builds: GTP-U → Inner IP(IP_A → AMF) → SCTP → NGAP
        Sends via UDP to the UPF target on port 2152.

        Args:
            ngap_message: NGAP message tuple/list for pycrate encoding
            gtpu_udp_sock: UDP socket for GTP-U transmission
            gtpu_target: UPF IP address (GTP-U endpoint)
            gtpu_teid: TEID from UE1's PDU session
            src_ip: IP_A (UE1's assigned IP, used as inner packet source)
            tsn_counter: mutable list [n] used as SCTP TSN counter
        """
        with self.socket_lock:
            self.PDU.set_val(ngap_message)
            ngap_data = self.PDU.to_aper()

        # Build inner IP + SCTP + NGAP
        inner_packet = self._build_inner_sctp_packet(
            ngap_data, src_ip, self.amf_address, tsn=tsn_counter[0]
        )
        tsn_counter[0] += 1

        # Build GTP-U encapsulation
        gtpu_packet = self._build_gtpu_packet(inner_packet, gtpu_teid)
        # Log the actual TEID bytes in the GTP-U header for verification
        _teid_bytes = gtpu_packet[4:8]
        logger.info(f"GTP-U packet built: teid_input={repr(gtpu_teid)}, "
                    f"teid_in_header=0x{_teid_bytes.hex()}, "
                    f"total_len={len(gtpu_packet)}")

        try:
            gtpu_udp_sock.sendto(gtpu_packet, (gtpu_target, self.gtpu_target_port))
            logger.debug(
                f"GTP-U tunnel: {len(gtpu_packet)}B → {gtpu_target}:{self.gtpu_target_port} "
                f"(TEID=0x{gtpu_teid}, inner IP={src_ip}→{self.amf_address}, "
                f"NGAP={len(ngap_data)}B)"
            )
        except Exception as e:
            logger.error(f"GTP-U send failed: {e}")

    def _recv_ngap(self, timeout=10):
        """Receive and decode one NGAP message from AMF via SCTP."""
        self.sctp_socket.settimeout(timeout)
        data = self.sctp_socket.recv(4096)
        if not data:
            return None, None
        with self.socket_lock:
            PDU = NGAP_PDU_Descriptions.NGAP_PDU
            PDU.from_aper(data)
            type_t, pdu_dict = PDU()
        return type_t, pdu_dict

    def _recv_gtpu_ngap(self, gtpu_udp_sock, timeout=2):
        """Receive a GTP-U packet, strip headers, and decode the inner NGAP message.

        GTP-U packet structure:
          Outer: UDP payload
          GTP-U Header (8 bytes): Flags, MsgType, Length, TEID
          Inner IP (20 bytes): src, dst, proto
          Inner SCTP (12+ bytes): Common Header + DATA Chunk header
          NGAP payload

        Returns: (type_t, pdu_dict) or (None, None) on timeout/error.
        """
        gtpu_udp_sock.settimeout(timeout)
        try:
            data, addr = gtpu_udp_sock.recvfrom(65535)
        except socket.timeout:
            return None, None
        except Exception as e:
            logger.debug(f"GTP-U recv error: {e}")
            return None, None

        if len(data) < 8:
            logger.debug(f"GTP-U packet too short: {len(data)}B from {addr}")
            return None, None

        # Parse GTP-U header
        flags, msg_type = data[0], data[1]
        gtpu_length = struct.unpack('!H', data[2:4])[0]
        gtpu_teid = struct.unpack('!I', data[4:8])[0]

        # Skip non-G-PDU messages (e.g., Error Indication 0x1A, Echo 0x01)
        if msg_type != 0xFF:
            logger.info(f"GTP-U non-G-PDU received: msg_type=0x{msg_type:02x}, "
                        f"TEID=0x{gtpu_teid:08x}, len={gtpu_length} from {addr}")
            return None, None

        # Inner IP packet starts at offset 8
        inner_ip_start = 8
        if len(data) < inner_ip_start + 20:
            logger.debug(f"GTP-U inner IP too short: {len(data)}B")
            return None, None

        # Parse inner IP header to get protocol and payload offset
        ip_proto = data[inner_ip_start + 9]
        ip_ihl = (data[inner_ip_start] & 0x0F) * 4
        inner_payload_start = inner_ip_start + ip_ihl

        if ip_proto == 132:  # SCTP
            # Skip SCTP Common Header (12 bytes)
            sctp_start = inner_payload_start
            if len(data) < sctp_start + 12:
                logger.debug(f"GTP-U inner SCTP too short")
                return None, None

            # Find DATA chunk (type=0)
            chunk_offset = sctp_start + 12
            while chunk_offset + 4 <= len(data):
                chunk_type = data[chunk_offset]
                chunk_flags = data[chunk_offset + 1]
                chunk_length = struct.unpack('!H', data[chunk_offset + 2:chunk_offset + 4])[0]

                if chunk_type == 0:  # DATA chunk
                    # DATA chunk header: 16 bytes (type+flags+len+tsn+sid+ssn+ppid)
                    ngap_start = chunk_offset + 16
                    ngap_data = data[ngap_start:chunk_offset + chunk_length]
                    # Strip any padding
                    if len(ngap_data) > 0:
                        logger.debug(f"GTP-U NGAP extracted: {len(ngap_data)}B from TEID=0x{gtpu_teid:08x}")
                        with self.socket_lock:
                            PDU = NGAP_PDU_Descriptions.NGAP_PDU
                            PDU.from_aper(ngap_data)
                            type_t, pdu_dict = PDU()
                        return type_t, pdu_dict
                    break
                else:
                    # Skip this chunk (padded to 4-byte boundary)
                    padded_len = (chunk_length + 3) & ~3
                    chunk_offset += padded_len

        return None, None

    def _recv_and_dispatch(self, ue: IntegratedUE, timeout=30, max_messages=50,
                           gtpu_udp_sock=None, gtpu_target=None, gtpu_teid=None,
                           gtpu_src_ip=None, tsn_counter=None):
        """Receive messages from AMF and dispatch to the given UE until it completes or times out.

        In GTP-U mode (gtpu_udp_sock provided), listens on BOTH the SCTP socket and
        the GTP-U UDP socket using select().  Incoming GTP-U packets are decapsulated
        (GTP-U → IP → SCTP → NGAP) before NGAP decoding.

        If gtpu_udp_sock/gtpu_target/gtpu_teid/gtpu_src_ip are provided, every outgoing
        NGAP response is sent ONLY via GTP-U tunnel (Inner IP + SCTP + NGAP).
        Otherwise, messages are sent via SCTP directly.
        """
        start = time.time()
        msg_count = 0
        use_gtpu = (gtpu_udp_sock is not None and gtpu_target is not None
                    and gtpu_teid is not None and gtpu_src_ip is not None
                    and tsn_counter is not None)

        while time.time() - start < timeout and msg_count < max_messages:
            try:
                type_t, pdu_dict = None, None

                if use_gtpu:
                    # Use select to listen on both SCTP and GTP-U sockets
                    remaining = max(0.5, timeout - (time.time() - start))
                    readable, _, _ = select.select(
                        [self.sctp_socket, gtpu_udp_sock], [], [], min(remaining, 2.0)
                    )
                    if self.sctp_socket in readable:
                        type_t, pdu_dict = self._recv_ngap(timeout=0.1)
                    elif gtpu_udp_sock in readable:
                        type_t, pdu_dict = self._recv_gtpu_ngap(gtpu_udp_sock, timeout=0.1)
                    else:
                        # Timeout on both sockets, loop back
                        continue
                else:
                    type_t, pdu_dict = self._recv_ngap(
                        timeout=max(1, timeout - (time.time() - start))
                    )

                if type_t is None:
                    continue

                procedure_code = pdu_dict['procedureCode']

                # Log every received NGAP message for debugging
                try:
                    proc = ProcedureCode(procedure_code)
                    proc_name = proc.name
                except ValueError:
                    proc_name = f"Unknown({procedure_code})"

                msg_type = ue._extract_message_type(pdu_dict)
                logger.info(f"Received NGAP: proc={proc_name} ({procedure_code}), "
                           f"msg_type={msg_type}")

                # Log but don't skip error indications and paging
                try:
                    proc = ProcedureCode(procedure_code)
                    if proc == ProcedureCode.ID_ERROR_INDICATION:
                        logger.warning(f"Received Error Indication from AMF!")
                        for ie in pdu_dict['value'][1].get('protocolIEs', []):
                            if ie['value'][0] == 'Cause':
                                logger.warning(f"  Cause: {ie['value'][1]}")
                        continue
                    if proc == ProcedureCode.ID_PAGING:
                        continue
                except ValueError:
                    pass

                ue, messages = ue.handle_message(type_t, pdu_dict)

                # Send response messages (GTP-U tunnel only, or SCTP)
                for msg in messages:
                    if use_gtpu:
                        self._send_gtpu(msg, gtpu_udp_sock, gtpu_target,
                                        gtpu_teid, gtpu_src_ip, tsn_counter)
                    else:
                        self._send_ngap(msg)
                    msg_count += 1

                # Check if UE is fully done (registered + PDU established)
                if ue.dnn_internet_connected:
                    return ue

                # Check if registration was rejected
                if ue.registration_rejected:
                    logger.error(f"UE {ue.supi} registration rejected (cause={ue.registration_reject_cause}). Stopping.")
                    return ue

            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error in recv/dispatch: {e}")
                continue

        return ue

    def _recv_until_registered(self, ue: IntegratedUE, timeout=30):
        """Receive messages until UE is registered (but PDU not yet established)."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                type_t, pdu_dict = self._recv_ngap(timeout=max(1, timeout - (time.time() - start)))
                if type_t is None:
                    continue
                try:
                    proc = ProcedureCode(pdu_dict['procedureCode'])
                    if proc in (ProcedureCode.ID_ERROR_INDICATION, ProcedureCode.ID_PAGING):
                        continue
                except ValueError:
                    pass

                ue, messages = ue.handle_message(type_t, pdu_dict)
                for msg in messages:
                    self._send_ngap(msg)

                if ue.registered:
                    return ue
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"Error waiting for registration: {e}")
                continue
        return ue

    # ------------------------------------------------------------------
    # Round 1: Register UE1 only, capture IP_A + TEID
    # ------------------------------------------------------------------
    def run_round1(self):
        """Round 1: Register UE1 through the original gNB, capture IP_A + TEID.

        Only the FIRST IMSI in the list is registered here.
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("ROUND 1: Register UE1 via original gNB")
        logger.info("=" * 60)

        imsi_suffix = self.imsi_list[0]
        logger.info(f"\nUE1: IMSI suffix={imsi_suffix}")

        # Create UE1
        current_imeisv = '{:016d}'.format(int(imsi_suffix))
        ue1 = IntegratedUE(
            mcc=self.mcc,
            mnc=self.mnc,
            imsi_suffix10=imsi_suffix,
            ran_ue_ngap_id=1,
            gnb_nr_cell_id=self.gnb_nr_cell_id,
            gnb_address=self.gnb_address,
            slices=self.slices,
            ki=self.ki,
            opc=self.opc,
            tac=self.tac,
            dnn=self.dnn,
            imeisv=current_imeisv,
            logging_level=self.log_level
        )
        self.ues.append(ue1)

        # Send Initial UE Message
        initial_msg = ue1.send_initial_ue_message()

        # Log the NGAP message details for debugging
        with self.socket_lock:
            self.PDU.set_val(initial_msg)
            ngap_bytes = self.PDU.to_aper()
        logger.info(f"Initial UE Message NGAP: {len(ngap_bytes)} bytes")
        logger.debug(f"NGAP hex: {ngap_bytes.hex()}")

        # Extract and log NAS-PDU
        for ie in initial_msg[1]['value'][1]['protocolIEs']:
            if ie['value'][0] == 'NAS-PDU':
                nas_bytes = ie['value'][1]
                logger.info(f"NAS-PDU ({len(nas_bytes)}B): {nas_bytes.hex()}")
                logger.info(f"  EPD=0x{nas_bytes[0]:02x} SecHdr=0x{nas_bytes[1]:02x} Type=0x{nas_bytes[2]:02x}")
                break

        self.sctp_socket.sctp_send(ngap_bytes, ppid=socket.htonl(NGAP_PPID))
        logger.info(f"Sent Initial UE Message for {ue1.supi}")

        # Wait for full registration + PDU session
        ue1 = self._recv_and_dispatch(ue1, timeout=60)

        if ue1.dnn_internet_connected:
            ue1.save_round1_session()
            result = {
                'imsi': ue1.supi,
                'ipv4': ue1.round1_ipv4,
                'teid': ue1.round1_teid,
                'upf_ip': ue1.round1_upf_ip,
                'status': 'success'
            }
            logger.info(f"\u2713 UE1 {ue1.supi} Round 1 COMPLETE:")
            logger.info(f"  Assigned IP_A = {ue1.round1_ipv4}")
            logger.info(f"  TEID          = 0x{ue1.round1_teid}")
            logger.info(f"  UPF IP        = {ue1.round1_upf_ip}")
        else:
            result = {
                'imsi': ue1.supi,
                'ipv4': None,
                'teid': None,
                'upf_ip': None,
                'status': 'failed'
            }
            logger.warning(f"\u2717 UE1 {ue1.supi} Round 1 FAILED "
                           f"(registered={ue1.registered}, pdu={ue1.dnn_internet_connected})")

        self.results['round1'].append(result)
        return ue1

    # ------------------------------------------------------------------
    # Round 2: Register UE2 through new base station using UE1's IP_A
    # ------------------------------------------------------------------
    def run_round2(self, ue1: IntegratedUE):
        """Round 2: Use UE1's assigned IP (IP_A) as a NEW base station,
        then register UE2 through it with GTP-U encapsulation using UE1's TEID.

        All NGAP messages are sent ONLY via GTP-U tunnel (no SCTP path):
          Outer: UDP(→UPF:2152)
          GTP-U: Flags=0x30, MsgType=0xFF, TEID=UE1's TEID
          Inner: IP(IP_A → AMF, proto=132 SCTP)
          SCTP:  src_port → dst_port=38412, DATA chunk (PPID=60 NGAP)
          NGAP:  APER-encoded message

        Flow:
        1. Create SCTP socket bound to IP_A (for NG Setup fallback / receiving)
        2. Create GTP-U UDP socket (bound to IP_A, targeting UPF with UE1's TEID)
        3. Send NGSetupRequest via GTP-U tunnel
        4. Create UE2 (brand new, never registered)
        5. Register UE2 — all NGAP messages sent via GTP-U tunnel only
        """
        logger.info("")
        logger.info("=" * 60)
        logger.info("ROUND 2: Register UE2 via new gNB (IP_A = UE1 assigned IP)")
        logger.info("=" * 60)

        if ue1 is None or ue1.round1_ipv4 is None or ue1.round1_teid is None:
            logger.error("UE1 has no valid round1 session info, cannot proceed with round 2")
            self.results['round2'].append({
                'imsi': 'N/A',
                'status': 'failed',
                'reason': 'UE1 round1 session unavailable'
            })
            return

        ip_a = ue1.round1_ipv4
        teid = ue1.round1_teid
        gtpu_target = ue1.round1_upf_ip or self.amf_address

        logger.info(f"New gNB source IP (IP_A): {ip_a}")
        logger.info(f"GTP-U TEID from UE1:      {repr(teid)} (type={type(teid).__name__})")
        if isinstance(teid, str):
            logger.info(f"GTP-U TEID as int:        0x{int(teid, 16):08x}")
        logger.info(f"GTP-U target (UPF):       {gtpu_target}:{self.gtpu_target_port}")

        # ----------------------------------------------------------
        # Step 1: Establish SCTP connection (NO NG Setup)
        #   In Round 2, ALL NGAP messages go through GTP-U tunnel.
        #   SCTP is only for potential downlink reception.
        # ----------------------------------------------------------
        logger.info(f"\nStep 1: Establishing SCTP connection (no NGSetup, source={ip_a})...")
        try:
            self._connect_sctp_only(ip_a)
        except Exception as e:
            logger.error(f"Failed to establish SCTP with IP_A={ip_a}: {e}")
            logger.warning("Falling back to original gNB address...")
            try:
                self._connect_sctp_only(self.gnb_address)
            except Exception as e2:
                logger.error(f"Fallback connection also failed: {e2}")
                self.results['round2'].append({
                    'imsi': 'N/A',
                    'status': 'failed',
                    'reason': f'connection failed: {e2}'
                })
                return

        # ----------------------------------------------------------
        # Step 2: Create GTP-U UDP socket for encapsulated messages
        # ----------------------------------------------------------
        gtpu_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            gtpu_udp_sock.bind((ip_a, 0))
        except Exception:
            logger.warning(f"Could not bind UDP socket to {ip_a}, using default")
        logger.info(f"\nStep 2: GTP-U UDP socket ready (bound to {ip_a})")

        # TSN counter for inner SCTP packets (mutable list so it can be passed by reference)
        tsn_counter = [1]

        # ----------------------------------------------------------
        # Step 3: Send NGSetupRequest via GTP-U tunnel
        #   NGSetup is also encapsulated in GTP-U to establish the
        #   gNB context through the tunnel.
        # ----------------------------------------------------------
        logger.info(f"\nStep 3: Sending NGSetupRequest via GTP-U tunnel "
                    f"(gNB ID={self.round2_gnb_id}, different from Round 1's 513)...")
        ng_setup_msg = NGAPSetupReqeust(
            self.mcc + self.mnc,
            "CoreSim-SeqGNB2",
            self.round2_gnb_id, 32,
            tac=self.tac,
            sst=self.slices["SST"],
            sd=self.slices.get("SD", None)
        )
        self._send_gtpu(ng_setup_msg, gtpu_udp_sock, gtpu_target,
                        teid, ip_a, tsn_counter)
        logger.info(f"NGSetupRequest sent via GTP-U tunnel (IP_A={ip_a})")

        # ----------------------------------------------------------
        # Step 4: Create UE2 (brand new, never registered)
        # ----------------------------------------------------------
        if len(self.imsi_list) < 2:
            logger.error("Need at least 2 IMSIs for round 2 (UE1 + UE2)")
            gtpu_udp_sock.close()
            return

        imsi_suffix_ue2 = self.imsi_list[1]
        logger.info(f"\nStep 4: Creating UE2 with IMSI suffix={imsi_suffix_ue2}...")

        current_imeisv = '{:016d}'.format(int(imsi_suffix_ue2))
        ue2 = IntegratedUE(
            mcc=self.mcc,
            mnc=self.mnc,
            imsi_suffix10=imsi_suffix_ue2,
            ran_ue_ngap_id=2,
            gnb_nr_cell_id=self.gnb_nr_cell_id,
            gnb_address=ip_a,  # Use IP_A as gNB address for UE2
            slices=self.slices,
            ki=self.ki,
            opc=self.opc,
            tac=self.tac,
            dnn=self.dnn,
            imeisv=current_imeisv,
            logging_level=self.log_level
        )
        self.ues.append(ue2)

        # ----------------------------------------------------------
        # Step 5: Register UE2 via GTP-U tunnel only
        #   - Initial UE Message sent via GTP-U (Inner IP + SCTP + NGAP)
        #   - All subsequent NGAP responses also sent via GTP-U tunnel
        # ----------------------------------------------------------
        logger.info(f"\nStep 5: Registering UE2 {ue2.supi} via GTP-U tunnel only...")
        initial_msg = ue2.send_initial_ue_message()

        # Send Initial UE Message via GTP-U tunnel (Inner IP_A → AMF)
        self._send_gtpu(initial_msg, gtpu_udp_sock, gtpu_target,
                        teid, ip_a, tsn_counter)
        logger.info(f"Sent Initial UE Message for UE2 via GTP-U tunnel")

        # Wait for registration + PDU (all responses sent via GTP-U tunnel)
        ue2 = self._recv_and_dispatch(
            ue2, timeout=60,
            gtpu_udp_sock=gtpu_udp_sock,
            gtpu_target=gtpu_target,
            gtpu_teid=teid,
            gtpu_src_ip=ip_a,
            tsn_counter=tsn_counter
        )

        # Close GTP-U UDP socket
        gtpu_udp_sock.close()

        if ue2.dnn_internet_connected:
            result = {
                'imsi': ue2.supi,
                'gnb_source_ip': ip_a,
                'gnb_teid_used': teid,
                'gtpu_target': gtpu_target,
                'ue2_ipv4': ue2.dnn_ipv4,
                'ue2_teid': ue2.dnn_gtp_teid,
                'ue2_upf_ip': ue2.upf_ip,
                'status': 'success'
            }
            logger.info(f"\n\u2713 UE2 {ue2.supi} Round 2 COMPLETE:")
            logger.info(f"  New gNB IP (IP_A):     {ip_a}")
            logger.info(f"  GTP-U TEID used:       0x{teid}")
            logger.info(f"  UE2 assigned IPv4:     {ue2.dnn_ipv4}")
            logger.info(f"  UE2 TEID:              {ue2.dnn_gtp_teid}")
        else:
            result = {
                'imsi': ue2.supi,
                'gnb_source_ip': ip_a,
                'gnb_teid_used': teid,
                'gtpu_target': gtpu_target,
                'ue2_ipv4': None,
                'ue2_teid': None,
                'ue2_upf_ip': None,
                'status': 'failed'
            }
            logger.warning(f"\u2717 UE2 {ue2.supi} Round 2 FAILED")

        self.results['round2'].append(result)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    def run(self):
        """Execute the full 2-round sequential registration flow.

        Round 1: UE1 registers through original gNB -> gets IP_A + TEID
        Round 2: Use IP_A as new gNB -> register UE2 through it with GTP-U encapsulation
        """
        try:
            if len(self.imsi_list) < 2:
                logger.error("Need at least 2 IMSIs: first for UE1 (round 1), second for UE2 (round 2)")
                return False

            self._connect()

            # Round 1: Register UE1, get IP_A + TEID
            ue1 = self.run_round1()

            if ue1 is None or not ue1.dnn_internet_connected:
                logger.error("Round 1 failed, cannot proceed to Round 2")
                self._print_summary()
                return False

            # Round 2: Register UE2 via new gNB using UE1's IP_A + TEID
            self.run_round2(ue1)

            # Summary
            self._print_summary()

            return True

        except Exception as e:
            logger.error(f"Sequential registration failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self._close()

    def _print_summary(self):
        """Print a summary of both rounds."""
        logger.info("")
        logger.info("=" * 60)
        logger.info("Sequential Registration Summary")
        logger.info("=" * 60)
    
        # Round 1 summary (UE1)
        logger.info("\nRound 1 (UE1 via original gNB):")
        r1_success = 0
        for r in self.results['round1']:
            status_icon = "\u2713" if r['status'] == 'success' else "\u2717"
            logger.info(f"  {status_icon} {r['imsi']}: IPv4={r['ipv4']}, "
                        f"TEID=0x{r['teid']}, UPF={r['upf_ip']}")
            if r['status'] == 'success':
                r1_success += 1
    
        # Round 2 summary (UE2 via new gNB using UE1's IP_A)
        logger.info("\nRound 2 (UE2 via new gNB using UE1's IP_A):")
        r2_success = 0
        for r in self.results['round2']:
            if r['status'] == 'skipped':
                logger.info(f"  - {r['imsi']}: SKIPPED ({r.get('reason', '')})")
                continue
            status_icon = "\u2713" if r['status'] == 'success' else "\u2717"
            logger.info(f"  {status_icon} {r['imsi']}: new gNB IP={r.get('gnb_source_ip', 'N/A')}, "
                        f"GTP-U TEID=0x{r.get('gnb_teid_used', 'N/A')} -> {r.get('gtpu_target', 'N/A')}")
            if r['status'] == 'success':
                logger.info(f"      UE2 IPv4={r['ue2_ipv4']}, UE2 TEID={r['ue2_teid']}")
                r2_success += 1
    
        logger.info("")
        logger.info(f"Round 1 (UE1): {r1_success}/{len(self.results['round1'])} success")
        logger.info(f"Round 2 (UE2): {r2_success}/{len(self.results['round2'])} success")
        logger.info("=" * 60)

    def _close(self):
        """Close SCTP connection and clean up."""
        self._close_sctp()
        logger.info("Connection closed")

    def _close_sctp(self):
        """Close the current SCTP socket if open."""
        self.running = False
        if self.sctp_socket:
            try:
                self.sctp_socket.shutdown(socket.SHUT_RDWR)
                self.sctp_socket.close()
            except:
                pass
            self.sctp_socket = None
