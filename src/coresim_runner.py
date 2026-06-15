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
from loguru import logger

# Add the current directory to the path to import local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config_loader import ConfigLoader
from core_network.core_network_factory import create_core_network
from ue_test_runner import UETestRunner
from integration.integrated_4g_gnb import Integrated4GGNB
from integration.integrated_4g_ue import _format_sgw_addr, _format_teid


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
        print(f"{'='*60}\n")
        
        success = runner.run_test()
        return success
        
    except Exception as e:
        print(f"Error running 5G test: {e}")
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
        """
    )
    
    # Operation mode
    parser.add_argument(
        "--mode", 
        help="Operation mode: 'provision' for subscription management, 'ue-test' for 5G testing, '4g-test' for 4G testing",
        choices=['provision', 'ue-test', '4g-test'],
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

    args = parser.parse_args()
    
    try:
        # Load configuration
        config_loader = ConfigLoader()
        
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
                print("\n✓ Multi-UE 4G test completed successfully!")
            else:
                print("\n✗ Multi-UE 4G test failed or partially failed.")
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
