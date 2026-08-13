# CoreSimRunner v1.1.0

**Multi-UE 5G/4G Core Network Testing Framework**

CoreSimRunner is a production-ready testing framework for automated subscriber provisioning, multi-UE registration, and session establishment testing against both **5G** and **4G** core networks. It supports **Free5GC** and **Open5GS** with concurrent provisioning (ThreadPoolExecutor), phase-based latency tracking, hybrid CLI + `.env` configuration, and detailed per-UE reporting.

## 📋 Table of Contents

* [Features](#-features)
* [Supported Core Networks](#-supported-core-networks)
* [Prerequisites](#-prerequisites)
* [Quick Start](#-quick-start)
* [Usage Modes](#-usage-modes)
* [Configuration](#-configuration)
* [IMS Provisioning (pyHSS)](#-ims-provisioning-pyhss)
* [Output & Reporting](#-output--reporting)
* [Performance & Scaling](#-performance--scaling)
* [Troubleshooting](#-troubleshooting)
* [Architecture](#-architecture)
* [License](#-license)

## ✨ Features

### Core Functionality

* **Concurrent Subscription Management**: ThreadPoolExecutor-based provisioning with tqdm progress bar (up to 20 concurrent workers)
* **IMS Provisioning via pyHSS**: Automatic 4-step IMS subscriber provisioning (APN → AuC → Subscriber → IMS Subscriber) when `ENABLE_IMS=true` (Open5GS only)
* **Multi-UE Concurrent Testing**: Simultaneously register and establish sessions for multiple UEs (1–100+)
* **Real-time Monitoring**: Live progress tracking with configurable logging levels (`LOG_LEVEL` in `.env`)
* **Compact Failure Reporting**: Range-formatted failure output (e.g., `Failed: 3/100, indices: 1-3, 5, 7-9`)
* **Hybrid Configuration**: All parameters loadable from `.env` file, overridable via CLI arguments

### 5G Capabilities

* **5G SA Registration**: Full 5G registration procedure (NAS + NGAP)
* **Dual PDU Session**: Optional second DNN via `ENABLE_IMS=true` (internet + IMS)
* **PDU Session Establishment**: DNN-based PDU session setup with QoS flow and S-NSSAI
* **NGAP Protocol**: Standard NGAP message construction and handling
* **Slice Awareness**: S-NSSAI configuration support (SST + SD)

### 4G LTE Capabilities

* **4G Attach Procedure**: Full LTE attach with NAS security (EIA2/EIA0 + EEA0)
* **EPS Bearer Establishment**: Default bearer setup with SGW TEID/address extraction
* **S1AP Protocol**: S1 Setup, InitialUEMessage, InitialContextSetup, E-RAB Setup
* **Milenage Authentication**: AUTN/RES verification, KASME derivation (3GPP PLMN encoding), NAS key generation

### Phase-Based Latency Tracking

Per-UE latency is measured at protocol milestones and reported as averages across all UEs:

| Phase | Measurement |
|----|----|
| **RRC Connection** | Initial UE Message sent → First DL response from AMF |
| **Auth + Security** | First DL response → Security Mode Complete sent |
| **Registration** | Security Mode Complete → Registration Accept received |
| **PDU Session 1** | Registration Accept → DNN1 session established |
| **PDU Session 2** | DNN1 established → DNN2 (IMS) session established |
| **Total** | Start → Final DNN established |

## 🌐 Supported Core Networks

| Core Network | Version | Status |
|----|----|----|
| **Free5GC** | v3.2+ | ✅ Production Ready |
| **Open5GS** | v2.4+ | ✅ Production Ready |

Both core networks support the same feature set with identical command-line interface.

## 🛠 Prerequisites

### System Requirements

* **Operating System**: Linux (Ubuntu 20.04+ recommended)
* **Python**: Python 3.8+
* **Network**: Docker/Docker Compose for core network deployment
* **Ports**: AMF 38412/SCTP (5G) or MME 36412/SCTP (4G) must be accessible

### Dependencies

* **pycrate**: ASN.1 encoding/decoding library (included in workspace)
* **CryptoMobile**: 3GPP cryptographic algorithms (installed separately, see below)
* **loguru**: Advanced logging library
* **requests**: HTTP client for core network API calls

All dependencies are automatically managed by the setup script.

### CryptoMobile Installation

CryptoMobile is not on PyPI and must be installed from source.

> ⚠️ **Do NOT clone the repository into this project.** Install it from a
> temporary directory and remove the clone afterwards, so the project tree
> stays clean.

```bash
# Install from a temporary directory (e.g., /tmp)
cd /tmp
git clone https://github.com/mitshell/CryptoMobile.git
cd CryptoMobile
python3 -m pip install .

# Clean up the temporary clone
cd /tmp && rm -rf CryptoMobile
```

Verify the installation:

```bash
python3 -c "from CryptoMobile.Milenage import Milenage; print('CryptoMobile OK')"
```

## 🚀 Quick Start

### 1. Setup Dependencies

```bash
cd /root/5gc/CoreSimRunner
bash setup.sh
```

### 2. Verify Installation

```bash
python3 test_imports.py
# Should show all imports successful
```

### 3. Configure Environment

Edit `src/.env` to match your core network. All parameters can also be passed via CLI.

**5G Configuration:**

```ini
# Core network (single address for WebUI API + AMF/MME SCTP)
CORE_ADDRESS=192.168.55.53
GNB_ADDRESS=192.168.55.9

# PLMN (MCC + MNC combined; MCC=PLMN[:3], MNC=PLMN[3:])
PLMN=20893

# Subscriber
PERMANENT_KEY=8baf473f2f8fd09487cccbd7097c6862
OPC_VALUE=8e27b6af0e692e750f32667a3b14605d
DNN=internet
SLICES={"SST": 1, "SD": "010203"}
GNB_NR_CELL_ID=1
ENABLE_IMS=false
LOG_LEVEL=INFO
```

**4G Configuration (additional):**

```ini
ENB_ADDRESS=192.168.55.9
MME_PORT=36412
ENB_ID=1
ENB_CELL_ID=1000000
TAC=000001
IMEISV=4370816125816151
APN=internet
```

### 4. Run Basic Test

```bash
cd src

# Provision 5 subscribers
python3 coresim_runner.py --mode provision --count 5 --core-network open5gs

# Run 5G UE test (all params from .env)
python3 coresim_runner.py --mode ue-test --core-network open5gs

# Run 4G UE test (all params from .env)
python3 coresim_runner.py --mode 4g-test --core-network open5gs

# Cleanup (delete subscribers)
python3 coresim_runner.py --mode provision --count 5 --delete --core-network open5gs
```

## 🎯 Usage Modes

### Provision Mode

Manage subscriber profiles with concurrent execution and progress bar.

```bash
# Create subscribers (concurrent, up to 20 workers)
python3 coresim_runner.py --mode provision --count 100 --core-network free5gc
# Progress: 100%|████████████████| 100/100 [00:03<00:00, 28.5sub/s]
# Failed: 0/100

# Delete subscribers
python3 coresim_runner.py --mode provision --count 100 --delete --core-network free5gc
```

### 5G UE Test Mode

Multi-UE registration and PDU session testing.

```bash
# Minimal — all params from .env
python3 coresim_runner.py --mode ue-test --core-network open5gs

# Override specific params via CLI
python3 coresim_runner.py --mode ue-test --count 20 \
    --gnb-address 192.168.55.9 --core-address 192.168.55.53 \
    --dnn internet --log-level WARNING
```

### 4G UE Test Mode

Multi-UE LTE attach and EPS bearer testing.

```bash
# Minimal — all params from .env
python3 coresim_runner.py --mode 4g-test --core-network open5gs

# Override specific params via CLI
python3 coresim_runner.py --mode 4g-test --count 10 \
    --enb-address 192.168.55.9 --core-address 192.168.55.53 \
    --apn internet --tac 000001
```

### Configuration Precedence

CLI arguments > `.env` file > built-in defaults. Any parameter can be set in `.env` and overridden on the command line.

## ⚙️ Configuration

### Environment Variables (`src/.env`)

**Common Parameters:**

| Parameter | Description | Default |
|----|----|----|
| `CORE_ADDRESS` | Core network IP (WebUI + AMF/MME) | *(required)* |
| `WEBUI_PORT` | WebUI port for API access | `5000` |
| `PLMN` | PLMN ID (MCC+MNC combined, e.g. `20893`) | `20893` |
| `PERMANENT_KEY` | Subscriber authentication key (Ki) | *(see .env)* |
| `OPC_VALUE` | Operator ciphered variant (OPc) | *(see .env)* |
| `INITIAL_IMSI_INDEX` | Starting IMSI suffix | `1` |
| `DEFAULT_SUBSCRIPTION_COUNT` | Default `--count` value | `2` |
| `LOG_LEVEL` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

**5G Parameters:**

| Parameter | Description | Default |
|----|----|----|
| `GNB_ADDRESS` | gNodeB IP address | `192.168.55.9` |
| `DNN` | Data Network Name | `internet` |
| `SLICES` | Slice configuration JSON (SST + optional SD) | `{"SST": 1}` |
| `GNB_NR_CELL_ID` | NR Cell ID | `1` |
| `ENABLE_IMS` | Enable IMS: second PDU session + pyHSS provisioning | `false` |
| `PYHSS_PORT` | pyHSS REST API port (for IMS provisioning) | `8080` |

**4G Parameters:**

| Parameter | Description | Default |
|----|----|----|
| `ENB_ADDRESS` | eNodeB IP address | `192.168.55.9` |
| `MME_PORT` | MME SCTP port | `36412` |
| `ENB_ID` | eNodeB ID | `1` |
| `ENB_CELL_ID` | eNodeB Cell ID | `1000000` |
| `TAC` | Tracking Area Code (hex, 6 chars) | `000001` |
| `APN` | Access Point Name | `internet` |
| `IMEISV` | IMEISV value | `4370816125816151` |

### Command Line Arguments

Override `.env` settings with command-line arguments:

| Argument | Description | Example |
|----|----|----|
| `--mode` | Operation mode | `provision`, `ue-test`, `4g-test` |
| `--count` | Number of UEs/subscribers | `1`, `10`, `100` |
| `--core-network` | Core network type | `free5gc`, `open5gs` |
| `--gnb-address` | gNodeB IP (5G) | `192.168.55.9` |
| `--core-address` | Core network IP (AMF/MME/WebUI) | `192.168.55.53` |
| `--enb-address` | eNodeB IP (4G) | `192.168.55.9` |
| `--mme-port` | MME port (4G) | `36412` |
| `--plmn` | PLMN ID (MCC+MNC) | `20893` |
| `--dnn` | Data Network Name (5G) | `internet` |
| `--apn` | Access Point Name (4G) | `internet` |
| `--tac` | Tracking Area Code | `000001` |
| `--log-level` | Logging verbosity | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--delete` | Delete mode (provision only) | *(flag)* |
| `--delete-all` | Delete ALL: pyHSS data (ims_subscriber → subscriber → auc → apn) + WebUI subscribers (provision only) | *(flag)* |

## 📞 IMS Provisioning (pyHSS)

When `ENABLE_IMS=true` and using **Open5GS**, each subscriber is automatically provisioned to the **pyHSS** REST API in addition to the Open5GS WebUI. This enables full IMS registration (VoNR/VoLTE) end-to-end.

### How It Works

For each subscriber, the following 4-step sequence is executed against pyHSS:

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Ensure APNs exist (idempotent)                    │
│    GET  /apn/list?page=0&page_size=200                     │
│    PUT  /apn/  {"apn": "internet", ...}  (if missing)     │
│    PUT  /apn/  {"apn": "ims", ...}      (if missing)     │
│    → Returns (internet_apn_id, ims_apn_id)                  │
│                                                             │
│  Step 2: Create AuC entry                                   │
│    PUT  /auc/  {"ki": ..., "opc": ..., "amf": ...,      │
│                 "sqn": 0, "imsi": ...}                     │
│    → Returns auc_id                                         │
│                                                             │
│  Step 3: Create Subscriber                                  │
│    PUT  /subscriber/  {"imsi": ..., "auc_id": ...,        │
│          "default_apn": internet_id,                       │
│          "apn_list": "internet_id,ims_id",                │
│          "msisdn": ..., ...}                               │
│                                                             │
│  Step 4: Create IMS Subscriber                              │
│    PUT  /ims_subscriber/  {"imsi": ..., "msisdn": ...,   │
│          "scscf": "sip:scscf.ims.mnc{MNC}.mcc{MCC}...",   │
│          "scscf_realm": "ims.mnc{MNC}.mcc{MCC}..."}       │
└─────────────────────────────────────────────────────────────┘
```

### Key Behaviors

* **Idempotent APN creation**: Queries existing APNs first; only creates missing ones. Existing `apn_id`s are reused.
* **PLMN-derived S-CSCF**: The `scscf`, `scscf_peer`, and `scscf_realm` fields are automatically derived from the configured `PLMN` (MCC + MNC). A 2-digit MNC is zero-padded to 3 digits per 3GPP (e.g., `PLMN=46009` → `ims.mnc009.mcc460.3gppnetwork.org`).
* **MSISDN derivation**: Each subscriber gets a **unique** MSISDN derived from the IMSI index, both in the Open5GS WebUI and pyHSS. The fixed prefix comes from the subscription template; the trailing digits are replaced by the zero-padded index. E.g., template `"13300000001"` → index `42` → MSISDN `13300000042`.
* **Delete cleanup**: `--delete` removes the subscriber from pyHSS as well (ims_subscriber, subscriber, auc).
* **Delete all**: `--delete-all` wipes everything in a fixed order — first pyHSS `ims_subscriber` → `subscriber` → `auc` → `apn`, then every Open5GS WebUI subscriber. pyHSS list queries paginate automatically (`page_size=200`, no 200-entry limit).

### Configuration

```ini
# .env — required for IMS provisioning
ENABLE_IMS=true
PYHSS_PORT=8080
PERMANENT_KEY=12341234123412341234123412340000
OPC_VALUE=71a121bb69baf3c0cc53fb5038a0131f
AMF=8000
```

| Parameter | Source | pyHSS Field |
|-----------|--------|-------------|
| `PERMANENT_KEY` | `.env` | `ki` in AuC |
| `OPC_VALUE` | `.env` | `opc` in AuC |
| `AMF` | `.env` | `amf` in AuC (default `8000`) |
| `PLMN` | `.env` | MCC/MNC in S-CSCF URI |
| `CORE_ADDRESS` | `.env` | pyHSS API host |
| `PYHSS_PORT` | `.env` | pyHSS API port (default `8080`) |

### Usage Examples

```bash
# Provision 5 subscribers (Open5GS + pyHSS)
python3 coresim_runner.py --mode provision --count 5 --core-network open5gs

# Delete 5 subscribers (Open5GS + pyHSS cleanup)
python3 coresim_runner.py --mode provision --count 5 --delete --core-network open5gs

# Delete ALL subscriptions: pyHSS data first (ims_subscriber -> subscriber -> auc -> apn),
# then every Open5GS WebUI subscriber. Ignores --count.
python3 coresim_runner.py --mode provision --delete-all --core-network open5gs
```

### Unit Tests

69 unit tests with mocked HTTP (no live pyHSS/Open5GS needed):

```bash
python3 -m pytest tests/test_pyhss_client.py tests/test_open5gs_delete_all.py -v
```

## 📊 Output & Reporting

### Provision Mode Output

```
Provisioning: 100%|████████████████| 100/100 [00:03<00:00, 28.5sub/s]
INFO - Provisioned 100/100 successfully
```

On failure, compact range format is used:

```
WARNING - Failed: 5/100, indices: 3-5, 12, 45-46
```

### UE Test Mode Output

```
INFO | ============================================================
INFO | Test Results Summary:
INFO |   Total UEs: 10
INFO |   Registered: 10
INFO |   PDU Sessions Established: 10
INFO |   Failed: 0
INFO | ============================================================
INFO |  --- Phase Latency (avg) ---
INFO |   RRC Connection:  85.3ms
INFO |   Auth+Security:   120.9ms
INFO |   Registration:    84.2ms
INFO |   PDU Session 1:   185.8ms
INFO |   Total:           476.2ms
INFO | ============================================================
```

### 4G Test Mode Output

```
INFO | ✓ UE 208930000000001 registered, EPS session: IPv4=172.28.0.3, SGW=10.200.1.1:2152, TEID=0x00000001
INFO | ============================================================
INFO | Test Results Summary (4G):
INFO |   Total UEs: 10
INFO |   Registered: 10
INFO |   EPS Sessions Established: 10
INFO |   Failed: 0
INFO | ============================================================
```

## 🚀 Performance & Scaling

### Recommended Configurations

| UE Count | Log Level | Estimated Time | System Requirements |
|----|----|----|----|
| 1-10 | INFO | 5-15 seconds | 2 CPU, 4GB RAM |
| 10-50 | WARNING | 15-60 seconds | 4 CPU, 8GB RAM |
| 50-100 | ERROR | 1-3 minutes | 8 CPU, 16GB RAM |
| 100+ | ERROR | 3-10 minutes | 16+ CPU, 32GB+ RAM |

### Optimization Tips


1. **Start Small**: Begin with 1-5 UEs to verify connectivity
2. **Reduce Logging**: Use `WARNING` or `ERROR` log levels for large-scale tests
3. **Monitor Resources**: Watch CPU, memory, and network usage during execution
4. **Network Tuning**: Ensure sufficient SCTP buffer sizes for high concurrency
5. **Cleanup Regularly**: Delete old subscriptions to prevent duplicates

## 🐛 Troubleshooting

### Common Issues & Solutions

| Problem | Diagnosis | Solution |
|----|----|----|
| **Import Errors** | Missing dependencies | Run `bash setup.sh` |
| **Connection Refused** | AMF not reachable | Check AMF status and port 38412 |
| **Authentication Failed** | Invalid subscriber data | Verify KI/OPC match subscription |
| **Timeout Errors** | Network congestion | Reduce UE count, increase timeout |
| **Duplicate Subscriptions** | IMSI already exists | Delete existing subscriptions first |
| **Too Many Files** | File descriptor limit | Run `ulimit -n 65536` |
| **SCTP PPID Issues** | Wrong byte order | PPID must be set via `pysctp.sctp_send()` in network byte order |

### Diagnostic Commands

```bash
# Test imports
python3 -m tests.test_imports

# Check AMF connectivity
telnet 192.168.55.53 38412

# View core network logs
docker logs free5gc_amf -f  # Free5GC
journalctl -u open5gs-amfd -f  # Open5GS

# Capture NGAP traffic
sudo tcpdump -i any port 38412 -w capture.pcap
```

### Debugging Steps


1. Enable debug logging: `--log-level DEBUG` or set `LOG_LEVEL=DEBUG` in `.env`
2. Verify subscription exists in core network WebUI
3. Check network connectivity between gNodeB and AMF
4. Review AMF logs for detailed error messages
5. Validate configuration parameters in `.env`

## 🏗 Architecture

### Module Structure

```
CoreSimRunner/
├── src/
│   ├── core_network/                # Core network abstraction layer
│   │   ├── core_network.py          # Base interface + _format_failed_range()
│   │   ├── core_network_factory.py  # Factory pattern
│   │   ├── free5gc_impl.py          # Free5GC: concurrent provisioning, tqdm
│   │   ├── open5gs_impl.py          # Open5GS: concurrent provisioning + pyHSS IMS
│   │   └── pyhss_client.py          # PyHSS REST API client (APN/AuC/Subscriber/IMS)
│   ├── integration/                 # Protocol integration
│   │   ├── integrated_gnb.py        # 5G gNodeB simulator (SCTP, NGAP)
│   │   ├── integrated_ue.py         # 5G UE state machine + latency tracking
│   │   ├── integrated_messages.py   # 5G NGAP/NAS message handling
│   │   ├── integrated_4g_gnb.py     # 4G eNodeB simulator (S1AP)
│   │   ├── integrated_4g_ue.py      # 4G UE state machine
│   │   ├── integrated_4g_messages.py # 4G S1AP/NAS message handling
│   │   └── eNAS.py                  # 4G NAS codec (encode/decode)
│   ├── tests/                       # Unit tests (Milenage, NAS MAC, imports, pyHSS)
│   │   ├── test_pyhss_client.py     # PyHSS client: 39 tests, mocked HTTP
│   │   ├── test_milenage.py         # Milenage authentication
│   │   ├── test_compute_smc_mac.py  # NAS MAC computation
│   │   └── test_imports.py          # Import verification
│   ├── config_loader.py             # .env + JSON config management
│   ├── coresim_runner.py            # Main CLI entry point
│   └── ue_test_runner.py            # Multi-UE orchestrator + latency stats
├── config/                          # Subscription templates
│   ├── free5gc_subscription_template.json
│   └── open5gs_subscription_template.json
├── scripts/                         # Diagnostic scripts
│   └── diagnose_nas_mac.py
├── setup.sh                         # Dependency setup
└── requirements.txt                 # Python dependencies
```

### Design Principles

* **Separation of Concerns**: Core network logic separated from 5G/4G protocol implementation
* **Factory Pattern**: Easy addition of new core network types
* **Automatic Path Resolution**: No manual dependency configuration required
* **Thread Safety**: Safe concurrent execution for multi-UE testing and provisioning
* **Concurrent Provisioning**: `ThreadPoolExecutor` with up to 20 workers, `tqdm` progress bar
* **Comprehensive Error Handling**: Graceful degradation and compact failure reporting

## 📖 Wiki

Full documentation is available in the [GitHub Wiki](https://github.com/hackeryounow/coresimrunner/wiki).

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


---


**CoreSimRunner v1.1.0***Production Ready • Concurrent Provisioning • Phase Latency Tracking • Cross-Platform*

For support and issues, please visit the [GitHub Wiki](https://github.com/hackeryounow/coresimrunner/wiki) or open an issue.