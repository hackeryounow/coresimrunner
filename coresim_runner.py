#!/usr/bin/env python3
"""
CoreSimRunner - 5G/4G Core Network Subscription Provisioning and Multi-UE Testing

This script provides functionality to:
1. Provision or delete subscriptions in different 5G core networks (Free5GC, Open5GS)
2. Perform multi-UE concurrent registration and PDU session establishment testing for 5G
3. Perform multi-UE concurrent registration and PDN session establishment testing for 4G
"""

import argparse
import sys
import os
import time

# Ensure the parent directory is on sys.path so that
# `from coresimrunner.xxx import ...` works when running
# this script directly from inside the package directory.
_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from loguru import logger

from coresimrunner.config_loader import ConfigLoader
from coresimrunner.core_network.core_network_factory import create_core_network
from coresimrunner.ue_test_runner import UETestRunner
from coresimrunner.integration.integrated_4g_gnb import Integrated4GGNB
from coresimrunner.integration.integrated_4g_ue import _format_sgw_addr, _format_teid
from coresimrunner.sequential_reg_runner import SequentialRegRunner
from coresimrunner.vonr_session import VoNRSessionRunner


def provision_subscriptions(count: int, core_network_type: str, delete: bool = False):
    """
    Provision or delete subscriptions in the specified core network.
    
    Args:
        count: Number of subscriptions to provision/delete
        core_network_type: Type of core network ('free5gc', 'open5gs', 'custom')
        delete: If True, delete subscriptions instead of provisioning
    """
    try:
        config_loader = ConfigLoader()
        core_network = create_core_network(core_network_type, config_loader)
        if core_network is None:
            logger.error(f"Unsupported core network type '{core_network_type}'")
            return False
        
        action = "Delete" if delete else "Provision"
        logger.info(f"{action}ing {count} subscriptions on {core_network_type}...")
        
        if delete:
            success = core_network.delete_subscriptions(count)
        else:
            success = core_network.provision_subscriptions(count)
        
        if success:
            logger.info(f"{action}ed {count}/{count} subscriptions successfully")
        return success
            
    except Exception as e:
        logger.error(f"Error during subscription {'deletion' if delete else 'provisioning'}: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_5g_test(args, config_loader):
    """
    Run 5G UE registration and PDU session establishment test.
    """
    try:
        # Get configuration values from .env or use provided arguments
        network_config = config_loader.get_network_config(args.core_network)
        
        plmn = args.plmn or config_loader.get_plmn()
        mcc = plmn[:3]
        mnc = plmn[3:]
        ki = args.ki or config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        opc = args.opc or config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        start_imsi = args.start_imsi or f"{network_config.get('initial_imsi_index', 1):010d}"
        gnb_address = args.gnb_address or config_loader.get("GNB_ADDRESS", "192.168.55.9")
        amf_address = args.core_address or config_loader.get_core_address()
        dnn = args.dnn or config_loader.get("DNN", "internet")
        tac = args.tac or config_loader.get("TAC", "000001")
        gnb_nr_cell_id = config_loader.get_int("GNB_NR_CELL_ID", 1)
        log_level = args.log_level or config_loader.get("LOG_LEVEL", "INFO")
        count = args.count if args.count is not None else config_loader.get_int("DEFAULT_SUBSCRIPTION_COUNT", 2)
        action = args.action if hasattr(args, 'action') and args.action != 'register' else None
        
        runner = UETestRunner(
            mcc=mcc,
            mnc=mnc,
            gnb_address=gnb_address,
            amf_address=amf_address,
            number_of_ues=count,
            start_imsi=start_imsi,
            ki=ki,
            opc=opc,
            dnn=dnn,
            tac=tac,
            gnb_nr_cell_id=gnb_nr_cell_id,
            log_level=log_level
        )
        
        print(f"\n{'='*60}")
        print(f"Starting Multi-UE Concurrent Registration Test (5G)")
        print(f"{'='*60}")
        print(f"Core Network: {args.core_network}")
        print(f"Number of UEs: {count}")
        print(f"gNodeB Address: {gnb_address}")
        print(f"AMF Address: {amf_address}")
        print(f"PLMN: {plmn}")
        print(f"Starting IMSI: {start_imsi}")
        print(f"DNN: {dnn}")
        print(f"TAC: {tac}")
        if action:
            print(f"Post-registration action: {action}")
        print(f"{'='*60}\n")
        
        success = runner.run_test(action=action)
        return success
        
    except Exception as e:
        print(f"Error running 5G test: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_seq_reg(args, config_loader):
    """
    Run sequential 2-round registration with GTP-U encapsulation.

    Round 1: Register each UE one-by-one, capture IP + TEID.
    Round 2: Deregister, send GTP-U encapsulated NAS, re-register.
    """
    try:
        network_config = config_loader.get_network_config(args.core_network)

        plmn = args.plmn or config_loader.get_plmn()
        mcc = plmn[:3]
        mnc = plmn[3:]
        ki = args.ki or config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        opc = args.opc or config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        gnb_address = args.gnb_address or config_loader.get("GNB_ADDRESS", "192.168.55.9")
        amf_address = args.core_address or config_loader.get_core_address()
        dnn = args.dnn or config_loader.get("DNN", "internet")
        tac = args.tac or config_loader.get("TAC", "000001")
        gnb_nr_cell_id = config_loader.get_int("GNB_NR_CELL_ID", 1)
        log_level = args.log_level or config_loader.get("LOG_LEVEL", "INFO")

        # Build IMSI list: from --imsi args or from start_imsi + count
        if hasattr(args, 'imsi') and args.imsi:
            imsi_list = args.imsi
        else:
            start_imsi = args.start_imsi or f"{network_config.get('initial_imsi_index', 1):010d}"
            count = args.count if args.count is not None else 2
            start_val = int(start_imsi)
            imsi_list = [f"{start_val + i:010d}" for i in range(count)]

        # Slice config
        slices_config = config_loader.get("SLICES", '{"SST": 1}')
        try:
            import json
            slices = json.loads(slices_config.replace("'", '"'))
        except Exception:
            slices = {"SST": 1}
        if "SD" in slices and isinstance(slices["SD"], str):
            slices["SD"] = int(slices["SD"], 16)

        gtpu_port = args.gtpu_port if hasattr(args, 'gtpu_port') and args.gtpu_port else 2152

        print(f"\n{'='*60}")
        print(f"Sequential Registration with GTP-U Encapsulation")
        print(f"{'='*60}")
        print(f"Core Network:  {args.core_network}")
        print(f"UE Count:      {len(imsi_list)}")
        print(f"IMSI List:     {imsi_list}")
        print(f"gNodeB Addr:   {gnb_address}")
        print(f"AMF Addr:      {amf_address}")
        print(f"GTP-U Port:   {gtpu_port}")
        print(f"PLMN:          {plmn}")
        print(f"DNN:           {dnn}")
        print(f"TAC:           {tac}")
        print(f"{'='*60}\n")

        runner = SequentialRegRunner(
            mcc=mcc,
            mnc=mnc,
            gnb_address=gnb_address,
            amf_address=amf_address,
            imsi_list=imsi_list,
            ki=ki,
            opc=opc,
            dnn=dnn,
            tac=tac,
            gnb_nr_cell_id=gnb_nr_cell_id,
            slices=slices,
            log_level=log_level,
            gtpu_target_port=gtpu_port,
        )

        success = runner.run()
        return success

    except Exception as e:
        print(f"Error running sequential registration: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_vonr(args, config_loader):
    """
    Run VoNR IMS session establishment: 5G registration + IMS PDU + SIP REGISTER + VoNR call.

    Sends SIP messages through the UPF GTP-U tunnel to the P-CSCF,
    performing IMS registration and optionally a VoNR INVITE call.
    """
    try:
        plmn = args.plmn or config_loader.get_plmn()
        mcc = plmn[:3]
        mnc = plmn[3:]
        ki = args.ki or config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        opc = args.opc or config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        gnb_address = args.gnb_address or config_loader.get("GNB_ADDRESS", "192.168.55.9")
        amf_address = args.core_address or config_loader.get_core_address()
        tac = args.tac or config_loader.get("TAC", "000001")
        log_level = args.log_level or config_loader.get("LOG_LEVEL", "INFO")

        # IMSI
        if hasattr(args, 'imsi') and args.imsi:
            imsi_suffix = args.imsi
        else:
            start_imsi = args.start_imsi or f"{config_loader.get_int('INITIAL_IMSI_INDEX', 1):010d}"
            imsi_suffix = start_imsi

        # Slice config
        slices_config = config_loader.get("SLICES", '{"SST": 1}')
        try:
            import json
            slices = json.loads(slices_config.replace("'", '"'))
        except Exception:
            slices = {"SST": 1}
        if "SD" in slices and isinstance(slices["SD"], str):
            slices["SD"] = int(slices["SD"], 16)

        # VoNR-specific parameters (from CLI or docker_open5gs .env defaults)
        upf_ip = args.upf_ip or config_loader.get("UPF_IP", "172.22.0.8")
        pcscf_ip = args.pcscf_ip or config_loader.get("PCSCF_IP", "172.22.0.21")
        pcscf_port = args.pcscf_port or config_loader.get_int("PCSCF_PORT", 5060)
        ims_domain = args.ims_domain or None  # auto-derive from PLMN
        caller_phone = args.caller_phone or "13012345679"
        callee_phone = args.callee_phone or "13012345678"
        skip_call = args.skip_call

        print(f"\n{'='*70}")
        print(f"  VoNR IMS Session Establishment")
        print(f"{'='*70}")
        print(f"  PLMN:       {plmn} (MCC={mcc}, MNC={mnc})")
        print(f"  IMSI:       {mcc}{mnc}{imsi_suffix.zfill(10)}")
        print(f"  gNB:        {gnb_address}")
        print(f"  AMF:        {amf_address}")
        print(f"  UPF:        {upf_ip}")
        print(f"  P-CSCF:     {pcscf_ip}:{pcscf_port}")
        print(f"  Caller:     {caller_phone}")
        print(f"  Callee:     {callee_phone}")
        print(f"  Skip Call:  {skip_call}")
        print(f"{'='*70}\n")

        runner = VoNRSessionRunner(
            mcc=mcc,
            mnc=mnc,
            imsi_suffix10=imsi_suffix,
            ki=ki,
            opc=opc,
            gnb_address=gnb_address,
            amf_address=amf_address,
            upf_ip=upf_ip,
            pcscf_ip=pcscf_ip,
            pcscf_port=pcscf_port,
            ims_domain=ims_domain,
            caller_phone=caller_phone,
            callee_phone=callee_phone,
            tac=tac,
            slices=slices,
            log_level=log_level,
        )

        return runner.run(skip_call=skip_call)

    except Exception as e:
        print(f"Error running VoNR session: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_4g_test(args, config_loader):
    """
    Run 4G UE registration and PDN session establishment test.
    """
    try:
        # Get configuration values from .env or use provided arguments
        network_config = config_loader.get_network_config(args.core_network)
        
        plmn = args.plmn or config_loader.get_plmn()
        mcc = plmn[:3]
        mnc = plmn[3:]
        ki = args.ki or config_loader.get("PERMANENT_KEY", "12341234123412341234123412340000")
        opc = args.opc or config_loader.get("OPC_VALUE", "71a121bb69baf3c0cc53fb5038a0131f")
        start_imsi = args.start_imsi or f"{network_config.get('initial_imsi_index', 1):010d}"
        
        # Read 4G-specific parameters from .env (fallback to sensible defaults)
        enb_address = args.enb_address or config_loader.get("ENB_ADDRESS", "192.168.55.9")
        mme_address = args.core_address or config_loader.get_core_address()
        mme_port = args.mme_port if args.mme_port is not None else config_loader.get_int("MME_PORT", 36412)
        enb_id = args.enb_id if args.enb_id is not None else config_loader.get_int("ENB_ID", 1)
        enb_cell_id = args.enb_cell_id if args.enb_cell_id is not None else config_loader.get_int("ENB_CELL_ID", 1000000)
        tac = args.tac or config_loader.get("TAC", "000001")
        apn = args.apn or config_loader.get("APN", "internet")
        imeisv = config_loader.get("IMEISV", "4370816125816151")
        log_level = args.log_level or config_loader.get("LOG_LEVEL", "INFO")
        count = args.count if args.count is not None else config_loader.get_int("DEFAULT_SUBSCRIPTION_COUNT", 2)
        
        runner = Integrated4GGNB(
            mcc=mcc,
            mnc=mnc,
            enb_name="CoreSim-4G-eNB",
            enb_ip=enb_address,
            mme_ip=mme_address,
            mme_port=mme_port,
            enb_id=enb_id,
            enb_cell_id=enb_cell_id,
            tac=tac,
            plmn=plmn,
            ki=ki,
            opc=opc,
            apn=apn,
            imeisv=imeisv,
            number_of_ues=count,
            start_imsi=start_imsi,
            log_level=log_level,
            config_loader=config_loader
        )
        
        print(f"\n{'='*60}")
        print(f"Starting Multi-UE Concurrent Registration Test (4G)")
        print(f"{'='*60}")
        print(f"Core Network: {args.core_network}")
        print(f"Number of UEs: {count}")
        print(f"eNodeB Address: {enb_address}")
        print(f"MME Address: {mme_address}:{mme_port}")
        print(f"PLMN: {plmn}")
        print(f"Starting IMSI: {start_imsi}")
        print(f"APN: {apn}")
        print(f"TAC: {tac}")
        print(f"{'='*60}\n")
        
        # Start UE creation and Initial UE Message sending
        runner.run()
        
        # Wait for registration to complete
        time.sleep(2)
        
        # Monitor registration progress
        for i in range(30):
            stats = runner.get_registration_stats()
            total = stats.get('total', 0)
            registered = stats.get('registered', 0)
            pdn_connected = stats.get('pdn_connected', 0)
            if registered == total > 0:
                logger.info(f"All UEs registered")
                break
            logger.info(f"Progress: {registered}/{total} registered, {pdn_connected}/{total} EPS sessions established")
            time.sleep(2)
        
        # Final stats
        stats = runner.get_registration_stats()
        total = stats.get('total', 0)
        registered = stats.get('registered', 0)
        eps_established = stats.get('pdn_connected', 0)
        failed = total - max(registered, eps_established)
        
        # Per-UE detail
        for ue in runner.ues:
            info = ue.get_session_info()
            ipv4 = info['ipv4'] or 'N/A'
            logger.info(
                f"\u2713 UE {info['imsi']} registered, EPS session established: "
                f"IPv4={ipv4}"
            )
            for b in info['bearers']:
                if b.get('sgw_teid') is not None:
                    logger.debug(
                        f"  Bearer {b['bearer_id']}: type={b['type']}, state={b['state']}, "
                        f"SGW-TEID={_format_teid(b['sgw_teid'])}, SGW-Addr={_format_sgw_addr(b['sgw_addr'])}"
                    )
        
        # Clean summary block (matches 5G format)
        logger.info("")
        logger.info("=" * 60)
        logger.info("Test Results Summary (4G):")
        logger.info(f"  Total UEs: {total}")
        logger.info(f"  Registered: {registered}")
        logger.info(f"  EPS Sessions Established: {eps_established}")
        logger.info(f"  Failed: {failed}")
        logger.info("=" * 60)
        
        success = (registered == total and eps_established == total)
        return success
        
    except Exception as e:
        print(f"Error running 4G test: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point for subscription provisioning/deletion and UE testing."""
    parser = argparse.ArgumentParser(
        description="5G/4G Core Network Subscription Management and Multi-UE Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Provision subscriptions
  %(prog)s --count 2 --core-network free5gc
  %(prog)s --count 5 --core-network open5gs
  
  # Delete subscriptions
  %(prog)s --count 2 --core-network free5gc --delete
  %(prog)s --count 5 --core-network open5gs --delete
  
  # Run 5G test (all params from .env)
  %(prog)s --mode ue-test --core-network open5gs
  
  # Run 5G test (override gnb/core address via CLI)
  %(prog)s --mode ue-test --count 10 --core-network free5gc --gnb-address 192.168.55.9 --core-address 192.168.55.211
  
  # Run 4G test (all params from .env)
  %(prog)s --mode 4g-test --core-network open5gs
  
  # Run 4G test (override address via CLI)
  %(prog)s --mode 4g-test --count 10 --core-network open5gs --enb-address 192.168.55.9 --core-address 192.168.55.53
  
  # Run sequential 2-round registration with GTP-U encapsulation
  %(prog)s --mode seq-reg --imsi 0000000001 0000000002 --core-network free5gc --gnb-address 192.168.55.9 --core-address 192.168.55.211

  # Run VoNR IMS session (REGISTER + INVITE via GTP-U to P-CSCF)
  %(prog)s --mode vonr --imsi 0000000001 --gnb-address 192.168.55.9 --core-address 192.168.55.53 --upf-ip 172.22.0.8 --pcscf-ip 172.22.0.21

  # VoNR REGISTER only (no call)
  %(prog)s --mode vonr --skip-call --imsi 0000000001
        """
    )
    
    # Operation mode
    parser.add_argument(
        "--mode", 
        help="Operation mode: 'provision' for subscription management, 'ue-test' for 5G testing, '4g-test' for 4G testing, 'seq-reg' for sequential 2-round registration with GTP-U, 'vonr' for VoNR IMS SIP session",
        choices=['provision', 'ue-test', '4g-test', 'seq-reg', 'vonr'],
        default="provision"
    )
    
    # Common arguments
    parser.add_argument(
        "--count", 
        help="Number of subscriptions or UEs (default: from .env DEFAULT_SUBSCRIPTION_COUNT or 2)", 
        type=int,
        default=None
    )
    parser.add_argument(
        "--core-network", 
        help="Type of core network ('free5gc', 'open5gs', or 'custom')", 
        choices=['free5gc', 'open5gs', 'custom'],
        default="free5gc"
    )
    parser.add_argument(
        "--delete",
        help="Delete subscriptions instead of provisioning them (only for provision mode)",
        action="store_true",
        default=False
    )
    
    # 5G test specific arguments
    parser.add_argument(
        "--gnb-address",
        help="gNodeB IP address (default: from .env GNB_ADDRESS)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--core-address",
        help="Core network IP address for AMF/MME/WebUI (default: from .env CORE_ADDRESS)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--dnn",
        help="Data Network Name (default: from .env DNN or 'internet')",
        type=str,
        default=None
    )
    parser.add_argument(
        "--action",
        help="Action to perform after registration+PDU establishment: register (default), deregister, release-pdu, service-request",
        choices=['register', 'deregister', 'release-pdu', 'service-request'],
        default='register'
    )
    
    # 4G test specific arguments
    parser.add_argument(
        "--enb-address",
        help="eNodeB IP address (default: from .env ENB_ADDRESS)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--apn",
        help="Access Point Name for 4G (default: from .env APN or 'internet')",
        type=str,
        default=None
    )
    parser.add_argument(
        "--mme-port",
        help="MME port for 4G (default: from .env MME_PORT or 36412)",
        type=int,
        default=None
    )
    parser.add_argument(
        "--attach-type",
        help="Attach type for 4G (default: 2)",
        type=int,
        default=2
    )
    parser.add_argument(
        "--pdp-type",
        help="PDP type for 4G (default: 1)",
        type=int,
        default=1
    )
    parser.add_argument(
        "--enb-id",
        help="eNodeB ID for 4G (default: from .env ENB_ID or 1)",
        type=int,
        default=None
    )
    parser.add_argument(
        "--enb-cell-id",
        help="eNodeB Cell ID for 4G (default: from .env ENB_CELL_ID or 1000000)",
        type=int,
        default=None
    )
    parser.add_argument(
        "--plmn",
        help="PLMN ID (MCC+MNC combined, e.g., 20893) (default: from .env PLMN)",
        type=str,
        default=None
    )

    # Common test arguments
    parser.add_argument(
        "--start-imsi",
        help="Starting IMSI suffix (10 digits, e.g., 0000000001)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--ki",
        help="Subscriber authentication key (hex string, 32 chars)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--opc",
        help="Operator ciphered variant (hex string, 32 chars)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--tac",
        help="Tracking Area Code (default: from .env TAC or '000001')",
        type=str,
        default=None
    )
    parser.add_argument(
        "--log-level",
        help="Logging level (DEBUG, INFO, WARNING, ERROR) (default: from .env LOG_LEVEL or INFO)",
        type=str,
        default=None,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR']
    )
    parser.add_argument(
        "--profile",
        help="Named config profile (e.g., 'default', 'prod') (default: active profile)",
        type=str,
        default=None
    )
    
    # Sequential registration arguments
    parser.add_argument(
        "--imsi",
        help="List of IMSI suffixes (10 digits each) for seq-reg mode, e.g. --imsi 0000000001 0000000002",
        nargs='+',
        type=str,
        default=None
    )
    parser.add_argument(
        "--gtpu-port",
        help="GTP-U target UDP port for encapsulated packets (default: 2152)",
        type=int,
        default=None
    )

    # VoNR-specific arguments
    parser.add_argument(
        "--upf-ip",
        help="UPF GTP-U tunnel endpoint IP for VoNR (default: 172.22.0.8)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--pcscf-ip",
        help="P-CSCF SIP address for VoNR (default: 172.22.0.21)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--pcscf-port",
        help="P-CSCF SIP port for VoNR (default: 5060)",
        type=int,
        default=None
    )
    parser.add_argument(
        "--ims-domain",
        help="IMS home domain (auto-derived from PLMN if omitted)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--caller-phone",
        help="Caller phone number for VoNR INVITE (default: 13012345679)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--callee-phone",
        help="Callee phone number for VoNR INVITE (default: 13012345678)",
        type=str,
        default=None
    )
    parser.add_argument(
        "--skip-call",
        help="Only perform SIP REGISTER, skip VoNR INVITE call setup",
        action="store_true",
        default=False
    )

    args = parser.parse_args()
    
    try:
        # Load configuration
        config_loader = ConfigLoader(profile_name=args.profile)
        
        if args.mode == "provision":
            count = args.count if args.count is not None else config_loader.get_int("DEFAULT_SUBSCRIPTION_COUNT", 2)
            success = provision_subscriptions(count, args.core_network, args.delete)
            if not success:
                sys.exit(1)
                    
        elif args.mode == "ue-test":
            gnb_addr = args.gnb_address or config_loader.get("GNB_ADDRESS")
            core_addr = args.core_address or config_loader.get_core_address()
            if not gnb_addr or not core_addr:
                print("Error: gNodeB and core network addresses required for ue-test mode")
                print("  Set via CLI: --gnb-address X.X.X.X --core-address Y.Y.Y.Y")
                print("  Or in .env:  GNB_ADDRESS=X.X.X.X  CORE_ADDRESS=Y.Y.Y.Y")
                sys.exit(1)
            
            success = run_5g_test(args, config_loader)
            
            if success:
                print("\n✓ Multi-UE 5G test completed successfully!")
            else:
                print("\n✗ Multi-UE 5G test failed or partially failed.")
                sys.exit(1)

        elif args.mode == "4g-test":
            success = run_4g_test(args, config_loader)
                    
            if success:
                print("\n\u2713 Multi-UE 4G test completed successfully!")
            else:
                print("\n\u2717 Multi-UE 4G test failed or partially failed.")
                sys.exit(1)
        
        elif args.mode == "seq-reg":
            success = run_seq_reg(args, config_loader)
                    
            if success:
                print("\n\u2713 Sequential registration with GTP-U encapsulation completed!")
            else:
                print("\n\u2717 Sequential registration failed or partially failed.")
                sys.exit(1)

        elif args.mode == "vonr":
            success = run_vonr(args, config_loader)

            if success:
                print("\n\u2713 VoNR IMS session establishment completed!")
            else:
                print("\n\u2717 VoNR IMS session failed or partially completed.")
                sys.exit(1)
            
    except FileNotFoundError as e:
        print(f"Configuration error: {e}")
        sys.exit(1)
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nPlease install required dependencies:")
        print("  cd /root/5gc/CoreSimRunner && bash setup.sh")
        print("\nOr manually install:")
        print("  pip3 install pycrate-asn1dir pycrate-mobile CryptoMobile pycryptodome loguru tqdm")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
