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

from coresimrunner.config_loader import ConfigLoader


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
                 log_level: str = "INFO",
                 ue_init_delay: float = 0.3):
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
        # Load configuration from active profile
        self.config_loader = ConfigLoader()
        
        # Use provided values or load from .env configuration
        plmn = self._get_config_value("PLMN") or self._get_config_value("PLMN_ID", "20893")
        self.mcc = mcc or plmn[:3]
        self.mnc = mnc or plmn[3:]
        self.gnb_address = gnb_address or self._get_config_value("GNB_ADDRESS", "172.28.0.6")
        self.amf_address = amf_address
        self.number_of_ues = number_of_ues
        self.start_imsi = start_imsi or f"{self.config_loader.get_int('INITIAL_IMSI_INDEX', 1):010d}"
        self.ki = ki or self.config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        self.opc = opc or self.config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        self.dnn = dnn or self._get_config_value("DNN") or self._get_config_value("DATA_NETWORK_NAME", "internet")
        self.amf_port = amf_port
        self.tac = tac
        self.gnb_id = gnb_id
        self.gnb_nr_cell_id = gnb_nr_cell_id or self.config_loader.get_int("GNB_NR_CELL_ID", 1)
        self.log_level = log_level
        self.ue_init_delay = ue_init_delay
        
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

    def close(self):
        """Explicitly close the gNB connection (called by API stop endpoint)."""
        if self.gnb:
            try:
                self.gnb.close()
            except Exception as e:
                logger.error(f"Error closing gNB: {e}")

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
    
    def run_test(self, cancel_event=None, action=None, keep_alive=False) -> bool:
        """
        Execute the multi-UE concurrent registration and PDU session test.
        
        Args:
            cancel_event: threading.Event — when set, aborts the test immediately.
            action: Optional action after registration+PDU: 'deregister', 'release-pdu', 'service-request'
            keep_alive: If True, do NOT close the gNB socket after test completes
                        (required when the API server needs to send further UE actions).
        
        Returns:
            bool: True if all UEs successfully registered and established PDU sessions
        """
        try:
            # Import and initialize gNB simulator
            from coresimrunner.integration.integrated_gnb import IntegratedGNB
            
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
                enable_ims=self.enable_ims,
                ue_init_delay=self.ue_init_delay
            )
            
            # Start the test
            logger.info(f"Starting test with {self.number_of_ues} UEs")
            self.gnb.run()
            
            # Monitor test progress
            self._monitor_test_progress(cancel_event)
            
            # Execute post-registration action if specified
            if action and self.gnb:
                action_success = self._execute_post_action(action, cancel_event)
                if not action_success:
                    logger.warning(f"Post-registration action '{action}' had issues")
            
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
            # Cleanup: only close the socket if NOT being kept alive for
            # subsequent UE actions (e.g. release-pdu, deregister, user-inactivity).
            if not keep_alive and self.gnb:
                try:
                    self.gnb.close()
                except:
                    pass

    def _monitor_test_progress(self, cancel_event=None):
        """Monitor test progress and update results."""
        timeout_seconds = 300  # 5 minutes timeout
        start_time = time.time()
        last_update_time = start_time
        
        while time.time() - start_time < timeout_seconds:
            # Check for cancellation
            if cancel_event and cancel_event.is_set():
                logger.warning("Test cancelled by user — stopping immediately")
                break

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

    def _execute_post_action(self, action, cancel_event=None):
        """
        Execute post-registration action: 'deregister', 'release-pdu', or 'service-request'.
        All actions require that registration + PDU session establishment are complete.
        """
        if not self.gnb or not self.gnb.ues:
            logger.error("No UEs available for post-registration action")
            return False

        logger.info(f"\n{'='*60}")
        logger.info(f"Executing post-registration action: {action}")
        logger.info(f"{'='*60}")

        if action == 'deregister':
            return self._action_deregister(cancel_event)
        elif action == 'release-pdu':
            return self._action_release_pdu(cancel_event)
        elif action == 'service-request':
            return self._action_service_request(cancel_event)
        else:
            logger.error(f"Unknown action: {action}")
            return False

    def _action_deregister(self, cancel_event=None):
        """
        Send Deregistration Request for each UE, wait for Dereg Accept + UE Context Release.
        """
        logger.info(f"Sending Deregistration Request for {len(self.gnb.ues)} UEs...")
        for ue in self.gnb.ues:
            if not ue.registered:
                logger.warning(f"UE {ue.supi} not registered, skipping deregistration")
                continue
            msg = ue.send_deregistration_request()
            self.gnb.message_queue.put(msg)
            logger.info(f"  Sent Deregistration Request for UE {ue.supi}")
            time.sleep(0.1)

        # Wait for deregistration to complete
        timeout = 30
        start = time.time()
        while time.time() - start < timeout:
            if cancel_event and cancel_event.is_set():
                break
            all_deregistered = all(not ue.registered for ue in self.gnb.ues)
            if all_deregistered:
                logger.info("All UEs successfully deregistered")
                return True
            time.sleep(0.5)

        # Final status
        dereg_count = sum(1 for ue in self.gnb.ues if not ue.registered)
        logger.info(f"Deregistration result: {dereg_count}/{len(self.gnb.ues)} UEs deregistered")
        return dereg_count == len(self.gnb.ues)

    def _action_release_pdu(self, cancel_event=None):
        """
        Send PDU Session Release Request for each UE, wait for Release Command + Complete.
        """
        logger.info(f"Sending PDU Session Release Request for {len(self.gnb.ues)} UEs...")
        for ue in self.gnb.ues:
            if not ue.dnn_internet_connected:
                logger.warning(f"UE {ue.supi} has no PDU session, skipping release")
                continue
            pdu_sess_id = ue.dnn_internet_pdu_sess_id or 1
            msg = ue.send_pdu_session_release_request(pdu_sess_id)
            self.gnb.message_queue.put(msg)
            logger.info(f"  Sent PDU Session Release Request for UE {ue.supi}, session {pdu_sess_id}")
            time.sleep(0.1)

        # Wait for release to complete
        timeout = 30
        start = time.time()
        while time.time() - start < timeout:
            if cancel_event and cancel_event.is_set():
                break
            all_released = all(not ue.dnn_internet_connected for ue in self.gnb.ues)
            if all_released:
                logger.info("All PDU sessions successfully released")
                return True
            time.sleep(0.5)

        # Final status
        released_count = sum(1 for ue in self.gnb.ues if not ue.dnn_internet_connected)
        logger.info(f"PDU release result: {released_count}/{len(self.gnb.ues)} sessions released")
        return released_count == len(self.gnb.ues)

    def _action_service_request(self, cancel_event=None):
        """
        Release UE context (gNB-initiated), then send Service Request to re-establish.
        Flow: UE Context Release Request → Command → Complete → (Paging) → Service Request.
        """
        # Step 1: Release UE context (gNB-initiated release)
        logger.info(f"Releasing UE context for {len(self.gnb.ues)} UEs...")
        for ue in self.gnb.ues:
            if ue.registered:
                msg = ue.release_ue_context()
                self.gnb.message_queue.put(msg)
                logger.info(f"  Sent UE Context Release Request for UE {ue.supi}")
                time.sleep(0.1)

        # Wait for context release to complete
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            if cancel_event and cancel_event.is_set():
                break
            all_released = all(ue.context_released for ue in self.gnb.ues)
            if all_released:
                logger.info("All UE contexts released")
                break
            time.sleep(0.2)

        # Step 2: Send Service Request via InitialUEMessage
        logger.info(f"Sending Service Request for {len(self.gnb.ues)} UEs...")
        for ue in self.gnb.ues:
            msg = ue.send_service_request()
            self.gnb.message_queue.put(msg)
            logger.info(f"  Sent Service Request for UE {ue.supi}")
            time.sleep(0.1)

        # Wait for service request response
        timeout = 30
        start = time.time()
        while time.time() - start < timeout:
            if cancel_event and cancel_event.is_set():
                break
            all_accepted = all(ue.service_accepted for ue in self.gnb.ues)
            if all_accepted:
                logger.info("All UEs received Service Accept")
                return True
            time.sleep(0.5)

        accepted_count = sum(1 for ue in self.gnb.ues if ue.service_accepted)
        logger.info(f"Service request result: {accepted_count}/{len(self.gnb.ues)} UEs accepted")
        return accepted_count == len(self.gnb.ues)