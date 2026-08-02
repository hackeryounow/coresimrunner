# CSCF Vulnerability Research & PoC Collection

**Target**: Kamailio 6.1.3 IMS (P-CSCF / I-CSCF / S-CSCF)  
**Environment**: Docker open5gs sa-vonr-deploy-2.8.1-beta  
**Date**: 2026-07-28  

---

## Confirmed Crashes

### diameter_crash_poc.py — CDP Diameter Heap Overflow

**CONFIRMED on I-CSCF (3869) and S-CSCF (3870), 100% reproducible.**

- **Root cause**: `receiver.c:621-627` — `shm_malloc(length)` then `memcpy(msg, buf, 20)` with no minimum length check
- **Attack**: Fresh TCP connection, send 20-byte Diameter header with Length=0
- **Impact**: Heap canary corruption → SIGABRT → container exit
- **RFC**: RFC 6733 §3 minimum message length violation
- **Usage**: `python3 diameter_crash_poc.py --target icscf`

### diameter_cer_attack.py — CER Handshake Comparison

Tests crash payload on both established (post-CER) and fresh connections.
Demonstrates that fresh connections crash but established ones don't.

---

## Attack Suites

### diameter_attack_poc.py — Comprehensive Diameter Suite

3 vulnerability classes tested against all CSCF Diameter ports:
- VULN-A: Short length heap overflow (receiver.c)
- VULN-B: AVP integer underflow (diameter_msg.c)
- VULN-C: Malformed CER variants

### advanced_poc.py — 7 Attack Vectors

Combined SIP + Diameter attack suite:
1. Alias port overflow (save.c:229)
2. Notify port overflow (notify.c:178)
3. Service routes overflow (service_routes.c:506)
4. TCP connection flood
5. SIP parser edge cases
6. Diameter short length
7. Combined multi-vector

### cve_poc_collection.py — Known CVE PoCs

Tests 4 known Kamailio CVEs (all patched in 6.1.3):
- CVE-2018-16657, CVE-2018-14767, CVE-2020-27507, CVE-2018-8828

### cscf_crash_suite.py — General Crash Suite

SIP-level crash triggers for all three CSCFs.

### cscf_crash_triggers.py — SIP Crash Triggers

Various SIP malformed message triggers.

---

## Exploits (Code-Confirmed, Not Triggered)

### exploit_alias_overflow.py — Alias Port Stack Overflow

Targets `save.c:229` — `portbuf[5]` overflow via Via `alias=HOST~PORT~PROTO`.
Registration succeeds but overflow is benign (corrupts locals only).

### poc_registration_race.py — Registration Race Condition

Targets Kamailio Issue #4670 — `ipsec_create/REGISTER_reply` SIGSEGV
via rapid overlapping REGISTER sequences. Not reproducible in 6.1.3.

### ipsec_crash_test.py — IPSec Module Crash Tests

Tests ims_ipsec_pcscf module crash scenarios.

---

## Fuzzing

### cscf_fuzzer.py — SIP Message Fuzzer

Sends malformed SIP messages to CSCF SIP ports (5060/4060/6060).

---

## Helper Scripts

### ims_register_full.py — Full IMS Registration Flow

Complete REGISTER→401→AKA→200OK→SUBSCRIBE→NOTIFY flow
using CryptoMobile Milenage. Used as base for exploit scripts.

### ims_register_full_vul.py — Vulnerable Registration Variant

Registration flow with deliberate vulnerabilities for testing.

---

## Documentation

### CSCF_CRASH_FINDINGS.md — Full Findings Report

Comprehensive report with root cause analysis, crash evidence,
reproducibility matrix, CVE references, and fix recommendations.

---

## Quick Start

```bash
# Crash I-CSCF (100% reliable)
python3 diameter_crash_poc.py --target icscf

# Crash S-CSCF (100% reliable)
python3 diameter_crash_poc.py --target scscf

# Crash both
python3 diameter_crash_poc.py --target all

# Run full Diameter attack suite
python3 diameter_attack_poc.py --target all

# Test race condition
python3 poc_registration_race.py
```

## Network Map

| Container | SIP Port | Diameter Port | Interface |
|-----------|----------|---------------|-----------|
| P-CSCF | 172.22.0.21:5060 | 3871 (not listening) | Rx |
| I-CSCF | 172.22.0.19:4060 | 3869 (listening) | Cx |
| S-CSCF | 172.22.0.20:6060 | 3870 (listening) | Cx |
| pyHSS | — | 3868 (listening) | Cx/Sh |
