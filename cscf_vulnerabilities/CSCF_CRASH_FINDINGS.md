# CSCF Crash Trigger Findings
## Kamailio 6.1.3 IMS (P-CSCF / I-CSCF / S-CSCF)

**Date**: 2026-07-28  
**Target**: Kamailio 6.1.3 (x86_64/linux) dc4570  
**Environment**: Docker open5gs sa-vonr-deploy-2.8.1-beta  

---

## Executive Summary

| # | Vulnerability | Target | Status | Method |
|---|---------------|--------|--------|--------|
| 1 | CDP Diameter Heap Overflow | I-CSCF (3869) | **CONFIRMED CRASH** | Fresh TCP, length<20 |
| 2 | CDP Diameter Heap Overflow | S-CSCF (3870) | **CONFIRMED CRASH** | Fresh TCP, length<20 |
| 3 | CDP Diameter Heap Overflow | P-CSCF (3871) | Not reachable | CDP not listening |
| 4 | Registration Race Condition | P-CSCF (5060) | Not reproducible | May be fixed in 6.1.3 |
| 5 | Alias portbuf[5] Stack Overflow | P-CSCF (5060) | Code-confirmed, benign | Overflow corrupts locals only |
| 6 | Service routes[10][255] Overflow | P-CSCF (5060) | Not reachable | Function not called in config |

---

## Vulnerability 1: CDP Diameter Heap Overflow (CONFIRMED)

### Root Cause

**File**: `src/modules/cdp/receiver.c` lines 611-627

```c
// Line 611: Extract attacker-controlled 3-byte length from Diameter header
sp->length = get_3bytes(sp->buf + 1);

// Line 612: Only checks maximum (65536), NO minimum check
if(sp->length > DP_MAX_MSG_LENGTH) { ... goto error_and_reset; }

// Line 621: Allocates sp->length bytes (can be 0)
sp->msg = shm_malloc(sp->length);

// Line 627: ALWAYS copies 20 bytes (DIAMETER_HEADER_LEN)
memcpy(sp->msg, sp->buf, sp->buf_len);  // sp->buf_len == 20
```

**When `sp->length < 20`**: `shm_malloc(length)` allocates a tiny buffer, then `memcpy` writes 20 bytes, overflowing the heap allocation by `(20 - length)` bytes. This corrupts the adjacent heap fragment's end marker (canary `0xabcdefed`), which is detected by Kamailio's `qm_debug_check_frag()` on the next allocation, triggering `abort()` (SIGABRT).

### RFC Reference

RFC 6733 (Diameter Base Protocol) §3 — Message Format:
> The Message Length field is three octets and indicates the length of the Diameter message **including the header fields**. The minimum Diameter message is 20 bytes (header only, no AVPs).

The implementation fails to enforce this minimum, violating the protocol specification.

### Attack Vector

1. Open a **fresh TCP connection** to the target's Diameter port
2. Send a 20-byte Diameter header with the 3-byte Length field set to any value **< 20** (e.g., 0)
3. The CDP receiver process reads the header, allocates `length` bytes, copies 20 bytes → heap overflow
4. Next `shm_malloc`/`shm_free` detects corrupted canary → `abort()` → SIGABRT
5. Kamailio main process detects child death via SIGCHLD → **terminates entire process**

**Important**: Must be a **fresh connection** with no prior Diameter handshake. After a successful CER/CEA exchange, the heap state changes and the overflow may not corrupt critical metadata.

### Crash Evidence

**I-CSCF crash log** (4 separate crash events confirmed):
```
25(57) CRITICAL: <core> [core/mem/q_malloc.c:136]: qm_debug_check_frag():
  BUG: qm: fragm. 0x7fb58d6df570 (address 0x7fb58d6df5b0)
  end overwritten (bbbb0000, abcdefed)!
  Memory allocator was called from cdp: receiver.c:672.
  Fragment marked by cdp: receiver.c:621.
  Exec from core/mem/q_malloc.c:546.
 0(7) ALERT: <core> [main.c:824]: handle_sigs(): child process 57 exited by a signal 6
 0(7) ALERT: <core> [main.c:828]: handle_sigs(): core was generated
 0(7) INFO: <core> [main.c:851]: handle_sigs(): terminating due to SIGCHLD
```

**S-CSCF crash log** (2 separate crash events confirmed):
```
25(60) CRITICAL: <core> [core/mem/q_malloc.c:136]: qm_debug_check_frag():
  BUG: qm: fragm. 0x7f24347e8220 (address 0x7f24347e8260)
  end overwritten (efbe0000, abcdefed)!
  Memory allocator was called from cdp: receiver.c:672.
  Fragment marked by cdp: receiver.c:621.
  Exec from core/mem/q_malloc.c:546.
 0(7) ALERT: <core> [main.c:824]: handle_sigs(): child process 60 exited by a signal 6
 0(7) ALERT: <core> [main.c:828]: handle_sigs(): core was generated
```

Note: `(bbbb0000, abcdefed)` and `(efbe0000, abcdefed)` — the `0xbbbb` and `0xbeef`
(LE: `efbe`) are from the attacker's Hop-by-Hop ID and End-to-End ID fields,
proving attacker-controlled data corrupts heap metadata canaries.

### Reproducibility

| Target | Port | Fresh Connection | After CER Handshake |
|--------|------|-----------------|---------------------|
| I-CSCF | 3869 | **CRASH (100%)** | No crash |
| S-CSCF | 3870 | **CRASH (100%)** | No crash |
| P-CSCF | 3871 | N/A (not listening) | N/A |

### PoC Script

`diameter_crash_poc.py` — sends Diameter header with length=0 to trigger crash.

---

## Vulnerability 2: Registration Race Condition (Issue #4670)

### Reference

https://github.com/kamailio/kamailio/issues/4670 (reported against 6.1.1, March 2026)

### Description

P-CSCF crashes with SIGSEGV when processing rapid overlapping REGISTER/re-REGISTER/de-REGISTER sequences for the same UE. The crash occurs in `ipsec_create/REGISTER_reply` path when a pcontact is found with `reg_state[unknown]`.

### Status

**Not reproducible in 6.1.3** — may have been fixed. The PoC sent 200 rounds of rapid registration sequences without triggering a crash.

### PoC Script

`poc_registration_race.py` — sends rapid REGISTER sequences to P-CSCF.

---

## Vulnerability 3: Alias Port Buffer Overflow (Code-Confirmed, Benign)

### Root Cause

**File**: `src/modules/ims_registrar_pcscf/save.c` line 229

```c
char portbuf[5];  // line 136 — only 5 bytes!
...
memcpy(portbuf, port_s, (p - port_s));  // line 229 — NO bounds check
```

The `portbuf` is a 5-byte stack buffer. The `alias=HOST~PORT~PROTO` parameter in the Via header's `received` field can specify a port string longer than 5 characters, causing a stack buffer overflow.

### Same Pattern in notify.c

**File**: `src/modules/ims_registrar_pcscf/notify.c` line 178

```c
char bufport[5];  // line 91
...
memcpy(bufport, port, received_port_len);  // line 178 — NO bounds check
```

### Status

**Code-confirmed but benign in practice** — the overflow corrupts adjacent stack variables (alias_s, srcip) but does not reach the return address due to stack layout. No crash observed during testing.

---

## Vulnerability 4: Service Routes Buffer Overflow (Not Reachable)

### Root Cause

**File**: `src/modules/ims_registrar_pcscf/service_routes.c` lines 503-515

```c
char routes[MAXROUTES][MAXROUTESIZE];  // = char routes[10][255]
...
while(r) {
    memcpy(routes[i], r->nameaddr.uri.s, r->nameaddr.uri.len);  // NO bounds check
    i++;
}
```

Two overflow conditions:
1. **More than 10 Route headers** → `routes[10+]` writes beyond array bounds
2. **Route URI > 255 bytes** → memcpy overflows the 255-byte sub-array (SIP URIs can be up to 1024 bytes)

### Status

**Not reachable** — `check_service_routes()` is not called in the current P-CSCF Kamailio configuration.

---

## Attack Surface Summary

### Diameter (CDP) Interface

| Port | Service | Status | Notes |
|------|---------|--------|-------|
| 3868 | pyHSS | Listening | HSS Diameter (not Kamailio) |
| 3869 | I-CSCF | **Listening** | Cx interface, AcceptUnknownPeers=1 |
| 3870 | S-CSCF | **Listening** | Cx interface, AcceptUnknownPeers=1 |
| 3871 | P-CSCF | **NOT listening** | CDP module failed to start |

### SIP Interface

| Port | Service | Status | Notes |
|------|---------|--------|-------|
| 5060 | P-CSCF | Listening | UDP+TCP, IPSec ports 5100-6109 |
| 4060 | I-CSCF | Listening | UDP+TCP |
| 6060 | S-CSCF | Listening | UDP+TCP |

### CVE Database Search Results

- **15 Kamailio CVEs** found (2007-2026), all patched in 6.1.3
- **172 Open5GS CVEs** found (PFCP, SBI, AMF buffer overflows)
- **CVE-2020-6098**: freeDiameter integer underflow in AVP parsing (same pattern as our finding)

---

## Recommendations

1. **Immediate**: Apply minimum length check in CDP receiver.c:
   ```c
   if(sp->length < DIAMETER_HEADER_LEN || sp->length > DP_MAX_MSG_LENGTH) {
       goto error_and_reset;
   }
   ```

2. **Short-term**: Add bounds checking to `portbuf[5]` and `bufport[5]` memcpy calls in save.c and notify.c

3. **Medium-term**: Add bounds checking to service_routes.c routes array copy

4. **Long-term**: Investigate P-CSCF CDP module startup failure (port 3871)

---

## PoC Files

| File | Description |
|------|-------------|
| `diameter_crash_poc.py` | Confirmed crash: Diameter length=0 heap overflow |
| `diameter_attack_poc.py` | Comprehensive Diameter attack suite (3 vuln classes) |
| `diameter_cer_attack.py` | CER handshake + crash payload attack |
| `poc_registration_race.py` | Registration race condition (Issue #4670) |
| `exploit_alias_overflow.py` | Alias port overflow via registration flow |
| `advanced_poc.py` | 7 attack vectors combined |
