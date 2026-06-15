#!/usr/bin/env python3
"""
UE Test Runner - Multi-UE Concurrent Registration and PDU Session Testing

This module integrates the 5G registration and PDU session establishment logic from 5gregpdu
into CoreSimRunner, enabling multi-UE concurrent testing capabilities.
"""

import sys
import os
import time
import threading
import queue
import json
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

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import config loader
from config_loader import ConfigLoader


class UETestRunner:
    """
    Multi-UE concurrent registration and PDU session test runner.
    
    This class orchestrates the creation of multiple simulated UEs,
    manages their registration with the 5G core network, and establishes
    PDU sessions concurrently.
    """
    
    def __init__(self, 
                 mcc: str = None,
                 mnc: str = None,
                 gnb_address: str = None,
                 amf_address: str = None,
                 number_of_ues: int = 1,
                 start_imsi: str = None,
                 ki: str = None,
                 opc: str = None,
                 dnn: str = None,
                 amf_port: int = 38412,
                 sst: int = None,
                 sd: Optional[int] = None,
                 tac: str = "000001",
                 gnb_id: int = 513,
                 gnb_nr_cell_id: int = None,
                 log_level: str = "INFO"):
        """
        Initialize the UE test runner.
        
        Args:
            mcc: Mobile Country Code (e.g., "460")
            mnc: Mobile Network Code (e.g., "99")
            gnb_address: gNodeB IP address
            amf_address: AMF IP address
            number_of_ues: Number of UEs to simulate
            start_imsi: Starting IMSI suffix (10 digits)
            ki: Subscriber authentication key (hex string)
            opc: Operator ciphered variant (hex string)
            dnn: Data Network Name
            amf_port: AMF SCTP port (default: 38412)
            sst: Slice/Service Type
            sd: Slice Differentiator (optional)
            tac: Tracking Area Code
            gnb_id: gNodeB ID
            gnb_nr_cell_id: NR Cell ID
            log_level: Logging level
        """
        # Load configuration from .env file
        self.config_loader = ConfigLoader(".env")
        
        # Use provided values or load from .env configuration
        self.mcc = mcc or self._get_config_value("MCC", "460")
        self.mnc = mnc or self._get_config_value("MNC", "99")
        self.gnb_address = gnb_address or self._get_config_value("GNB_ADDRESS", "172.28.0.6")
        self.amf_address = amf_address
        self.number_of_ues = number_of_ues
        self.start_imsi = start_imsi or f"{self.config_loader.get_int('INITIAL_IMSI_INDEX', 1):010d}"
        self.ki = ki or self.config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        self.opc = opc or self.config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        self.dnn = dnn or self._get_config_value("DNN", "internet")
        self.amf_port = amf_port
        self.tac = tac
        self.gnb_id = gnb_id
        self.gnb_nr_cell_id = gnb_nr_cell_id or self.config_loader.get_int("GNB_NR_CELL_ID", 1)
        self.log_level = log_level
        
        # IMS (DNN2) configuration
        ims_val = self._get_config_value("ENABLE_IMS", "false")
        self.enable_ims = ims_val.lower() in ('true', '1', 'yes')
        
        # Handle SLICES configuration from .env
        slices_config = self._get_config_value("SLICES", '{"SST": 1}')
        try:
            self.slices = json.loads(slices_config.replace("'", '"'))
        except (json.JSONDecodeError, ValueError):
            # Fallback to default if parsing fails
            self.slices = {"SST": 1}
        
        # Normalize SD: convert hex string (e.g. "010203") to integer
        if "SD" in self.slices and isinstance(self.slices["SD"], str):
            self.slices["SD"] = int(self.slices["SD"], 16)
        
        # Override SST/SD if explicitly provided
        if sst is not None:
            self.slices["SST"] = sst
        if sd is not None:
            self.slices["SD"] = sd
        
        # Internal state
        self.gnb = None
        self.test_results = {
            "total": number_of_ues,
            "registered": 0,
            "pdu_established": 0,
            "failed": 0
        }
        self.results_lock = threading.Lock()
        
        # Configure logger
        self._setup_logger()

    def _get_config_value(self, key: str, default: str = None) -> str:
        """Get configuration value from .env file with proper handling of quoted strings."""
        value = self.config_loader.get(key, default)
        if value is None:
            return default
            
        # Remove surrounding quotes if present (for string values in .env)
        if isinstance(value, str):
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
        return value

    def _setup_logger(self):
        """Configure logging for the test runner."""
        logger.remove()
        logger.add(
            sink=sys.stdout,
            level=self.log_level,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
    
    def run_test(self) -> bool:
        """
        Execute the multi-UE concurrent registration and PDU session test.
        
        Returns:
            bool: True if all UEs successfully registered and established PDU sessions
        """
        try:
            # Import and initialize gNB simulator
            from integration.integrated_gnb import IntegratedGNB
            
            logger.info(f"Initializing gNB simulator at {self.gnb_address}")
            logger.info(f"Connecting to AMF at {self.amf_address}:{self.amf_port}")
            
            # Create gNB instance with integrated UE management
            self.gnb = IntegratedGNB(
                mcc=self.mcc,
                mnc=self.mnc,
                slices=self.slices,
                gnb_address=self.gnb_address,
                amf_address=self.amf_address,
                amf_port=self.amf_port,
                tac=self.tac,
                gnb_id=self.gnb_id,
                gnb_nr_cell_id=self.gnb_nr_cell_id,
                start_suffix10=self.start_imsi,
                number_of_ues=self.number_of_ues,
                ki=self.ki,
                opc=self.opc,
                dnn=self.dnn,
                logging_level=self.log_level,
                enable_ims=self.enable_ims
            )
            
            # Start the test
            logger.info(f"Starting test with {self.number_of_ues} UEs")
            self.gnb.run()
            
            # Monitor test progress
            self._monitor_test_progress()
            
            # Get final results
            with self.results_lock:
                success = (self.test_results["registered"] == self.number_of_ues and 
                          self.test_results["pdu_established"] == self.number_of_ues)
                
                logger.info("="*60)
                logger.info("Test Results Summary:")
                logger.info(f"  Total UEs: {self.test_results['total']}")
                logger.info(f"  Registered: {self.test_results['registered']}")
                logger.info(f"  PDU Sessions (DNN1): {self.test_results['pdu_established']}")
                if self.enable_ims:
                    logger.info(f"  PDU Sessions (DNN2/IMS): {self.test_results.get('ims_established', 0)}")
                logger.info(f"  Failed: {self.test_results['failed']}")
                
                # Latency summary
                if self.test_results.get('latencies'):
                    lats = self.test_results['latencies']
                    logger.info("  --- Phase Latency (avg) ---")
                    if 'avg_rrc' in lats:
                        logger.info(f"  RRC Connection:  {lats['avg_rrc']:.1f}ms")
                    if 'avg_auth_sec' in lats:
                        logger.info(f"  Auth+Security:   {lats['avg_auth_sec']:.1f}ms")
                    if 'avg_reg' in lats:
                        logger.info(f"  Registration:    {lats['avg_reg']:.1f}ms")
                    if 'avg_pdu1' in lats:
                        logger.info(f"  PDU Session 1:   {lats['avg_pdu1']:.1f}ms")
                    if self.enable_ims and 'avg_pdu2' in lats:
                        logger.info(f"  PDU Session 2:   {lats['avg_pdu2']:.1f}ms")
                    if 'avg_total' in lats:
                        logger.info(f"  Total:           {lats['avg_total']:.1f}ms")
                logger.info("="*60)
                
            return success
            
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            # Cleanup
            if self.gnb:
                try:
                    self.gnb.close()
                except:
                    pass

    def _monitor_test_progress(self):
        """Monitor test progress and update results."""
        timeout_seconds = 300  # 5 minutes timeout
        start_time = time.time()
        last_update_time = start_time
        
        while time.time() - start_time < timeout_seconds:
            with self.results_lock:
                # Check current status
                registered_count = 0
                pdu_established_count = 0
                ims_established_count = 0
                
                if self.gnb and self.gnb.ues:
                    for ue in self.gnb.ues:
                        if ue.registered:
                            registered_count += 1
                        if ue.dnn_internet_connected:
                            pdu_established_count += 1
                        if ue.dnn2_ims_connected:
                            ims_established_count += 1
                    
                    self.test_results["registered"] = registered_count
                    self.test_results["pdu_established"] = pdu_established_count
                    self.test_results["ims_established"] = ims_established_count
                    self.test_results["failed"] = self.number_of_ues - max(registered_count, pdu_established_count)
                
                # Check if all UEs are done
                target_dnn = self.number_of_ues
                target_ims = self.number_of_ues if self.enable_ims else 0
                if (registered_count == self.number_of_ues and 
                    pdu_established_count == target_dnn and
                    ims_established_count >= target_ims):
                    break
            
            # Print progress every 2 seconds
            current_time = time.time()
            if current_time - last_update_time >= 2:
                with self.results_lock:
                    prog = f"Progress: {self.test_results['registered']}/{self.test_results['total']} registered, "
                    prog += f"{self.test_results['pdu_established']}/{self.test_results['total']} DNN1"
                    if self.enable_ims:
                        prog += f", {self.test_results['ims_established']}/{self.test_results['total']} DNN2(IMS)"
                    logger.info(prog)
                last_update_time = current_time
            
            time.sleep(0.5)
        
        # Final update with latency statistics
        with self.results_lock:
            self._compute_latency_stats()
            logger.info(f"Final status: {self.test_results['registered']}/{self.test_results['total']} registered, "
                      f"{self.test_results['pdu_established']}/{self.test_results['total']} DNN1 established")
    
    def _compute_latency_stats(self):
        """Compute average latency statistics from all UEs by protocol phase."""
        rrc_lats, auth_sec_lats, reg_lats, pdu1_lats, pdu2_lats, total_lats = [], [], [], [], [], []
        
        if self.gnb and self.gnb.ues:
            for ue in self.gnb.ues:
                # Phase 1: RRC (Initial UE Message → First DL response)
                if ue.t_start and ue.t_rrc:
                    rrc_lats.append((ue.t_rrc - ue.t_start) * 1000)
                # Phase 2: Auth+Sec (First DL → Security Mode Complete)
                if ue.t_rrc and ue.t_auth_sec:
                    auth_sec_lats.append((ue.t_auth_sec - ue.t_rrc) * 1000)
                # Phase 3: Registration (SMC sent → Registration Accept)
                if ue.t_auth_sec and ue.t_registered:
                    reg_lats.append((ue.t_registered - ue.t_auth_sec) * 1000)
                # Phase 4: PDU Session 1 (Registration Accept → DNN1 established)
                if ue.t_registered and ue.t_dnn1_done:
                    pdu1_lats.append((ue.t_dnn1_done - ue.t_registered) * 1000)
                # Phase 5: PDU Session 2 (DNN1 → DNN2)
                if ue.t_dnn1_done and ue.t_dnn2_done:
                    pdu2_lats.append((ue.t_dnn2_done - ue.t_dnn1_done) * 1000)
                # Total time
                if ue.t_start and ue.t_dnn2_done:
                    total_lats.append((ue.t_dnn2_done - ue.t_start) * 1000)
                elif ue.t_start and ue.t_dnn1_done:
                    total_lats.append((ue.t_dnn1_done - ue.t_start) * 1000)
        
        lats = {}
        if rrc_lats:
            lats['avg_rrc'] = sum(rrc_lats) / len(rrc_lats)
        if auth_sec_lats:
            lats['avg_auth_sec'] = sum(auth_sec_lats) / len(auth_sec_lats)
        if reg_lats:
            lats['avg_reg'] = sum(reg_lats) / len(reg_lats)
        if pdu1_lats:
            lats['avg_pdu1'] = sum(pdu1_lats) / len(pdu1_lats)
        if pdu2_lats:
            lats['avg_pdu2'] = sum(pdu2_lats) / len(pdu2_lats)
        if total_lats:
            lats['avg_total'] = sum(total_lats) / len(total_lats)
        
        self.test_results['latencies'] = lats