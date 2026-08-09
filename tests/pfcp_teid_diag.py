#!/usr/bin/env python3
"""
Diagnose GTP-U TEID issue by capturing PFCP Session Establishment Response
and extracting the actual TEIDs that the UPF registers.
"""
import subprocess
import struct
import socket
import time
import sys
import threading

# Start tshark capture on docker bridge for PFCP port 8805
def start_capture():
    """Start tshark to capture PFCP on docker bridge."""
    proc = subprocess.Popen(
        ['tshark', '-i', 'docker_open5gs_default', '-w', '/tmp/pfcp_diag.pcap',
         '-f', 'udp port 8805', '-a', 'duration:30'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(1)
    return proc

def run_vonr_test():
    """Run the VoNR test."""
    proc = subprocess.Popen(
        [sys.executable, 'vonr_session.py',
         '--gnb-address', '192.168.55.53',
         '--amf-address', '192.168.55.53',
         '--upf-ip', '172.22.0.8',
         '--skip-call',
         '--log-level', 'INFO'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd='/root/5gc/coresimrunner'
    )
    stdout, _ = proc.communicate(timeout=60)
    return stdout.decode('utf-8', errors='replace')

def parse_pfcp_responses():
    """Parse PFCP Session Establishment Response to extract Created PDR F-TEIDs."""
    try:
        result = subprocess.run(
            ['tshark', '-r', '/tmp/pfcp_diag.pcap', '-Y',
             'pfcp.session_establishment_response || pfcp.session_modification_response',
             '-T', 'fields',
             '-e', 'frame.number', '-e', 'pfcp.message_type',
             '-e', 'pfcp.seid', '-e', 'pfcp.created_pdr'],
            capture_output=True, text=True, timeout=10
        )
        print("=== PFCP Session Responses ===")
        print(result.stdout if result.stdout else "(no session responses found)")
    except Exception as e:
        print(f"Error parsing PFCP: {e}")

    # Also check all PFCP messages
    try:
        result = subprocess.run(
            ['tshark', '-r', '/tmp/pfcp_diag.pcap', '-Y', 'pfcp',
             '-T', 'fields', '-e', 'frame.number', '-e', 'ip.src', '-e', 'ip.dst',
             '-e', 'pfcp.message_type', '-e', 'pfcp.seid'],
            capture_output=True, text=True, timeout=10
        )
        print("\n=== All PFCP Messages ===")
        for line in result.stdout.strip().split('\n')[:30]:
            print(line)
    except Exception as e:
        print(f"Error listing PFCP: {e}")

def check_ngap_teids():
    """Extract TEIDs from NGAP PDU Session Resource Setup."""
    try:
        result = subprocess.run(
            ['tshark', '-r', '/tmp/pfcp_diag.pcap', '-Y', 'ngap',
             '-T', 'fields', '-e', 'frame.number', '-e', 'ngap.procedureCode',
             '-e', 'ngap.ProtocolIE_ID'],
            capture_output=True, text=True, timeout=10
        )
        print("\n=== NGAP Messages ===")
        print(result.stdout if result.stdout else "(no NGAP messages)")
    except Exception as e:
        print(f"Error: {e}")

def check_gtpu():
    """Check GTP-U traffic."""
    try:
        result = subprocess.run(
            ['tshark', '-r', '/tmp/pfcp_diag.pcap', '-Y', 'gtp',
             '-T', 'fields', '-e', 'frame.number', '-e', 'ip.src', '-e', 'ip.dst',
             '-e', 'gtp.message_type'],
            capture_output=True, text=True, timeout=10
        )
        print("\n=== GTP-U Traffic ===")
        print(result.stdout if result.stdout else "(no GTP-U traffic)")
    except Exception as e:
        print(f"Error: {e}")

def main():
    print("=" * 60)
    print("PFCP TEID Diagnostic")
    print("=" * 60)

    # Step 1: Start capture
    print("\n[1] Starting PFCP capture on docker_open5gs_default...")
    cap = start_capture()

    # Step 2: Run VoNR test
    print("[2] Running VoNR test...")
    output = run_vonr_test()

    # Extract key info from test output
    for line in output.split('\n'):
        if 'TEID' in line or 'IMS' in line or 'IPv4' in line or 'Error' in line:
            print(f"  >> {line.strip()}")

    # Step 3: Wait for capture to finish
    print("\n[3] Waiting for capture to complete...")
    cap.wait(timeout=35)

    # Step 4: Parse PFCP responses
    print("\n[4] Analyzing captured traffic...")
    parse_pfcp_responses()
    check_ngap_teids()
    check_gtpu()

    # Step 5: Check UPF logs
    print("\n[5] UPF Error Indication logs:")
    try:
        result = subprocess.run(
            ['docker', 'exec', 'upf', 'grep', 'Error Indication',
             '/open5gs/install/var/log/open5gs/upf.log'],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split('\n')
        for line in lines[-10:]:
            print(f"  {line}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == '__main__':
    main()
