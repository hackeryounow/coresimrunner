# CoreSimRunner v1.0.0

**Multi-UE 5G/4G Core Network Testing Framework**

CoreSimRunner is a comprehensive testing framework that enables automated provisioning, registration, and session establishment testing for both 5G and 4G core networks. It supports Free5GC and Open5GS with multi-UE concurrent testing capabilities, hybrid CLI + `.env` configuration, and detailed session reporting.

## 📋 Table of Contents

- [Features](#-features)
- [Supported Core Networks](#-supported-core-networks)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Usage Modes](#-usage-modes)
- [Configuration](#-configuration)
- [Performance & Scaling](#-performance--scaling)
- [Troubleshooting](#-troubleshooting)
- [Architecture](#-architecture)
- [License](#-license)

## ✨ Features

### Core Functionality
- **Automated Subscription Management**: Create/delete subscriber profiles in Free5GC and Open5GS
- **Multi-UE Concurrent Testing**: Simultaneously register and establish sessions for multiple UEs (1–100+)
- **Real-time Monitoring**: Live progress tracking with configurable logging levels
- **Comprehensive Results Reporting**: Detailed success/failure metrics per test run
- **Hybrid Configuration**: All parameters loadable from `.env` file, overridable via CLI arguments

### 5G Capabilities
- **5G SA Registration**: Full 5G registration procedure (NAS + NGAP)
- **PDU Session Establishment**: DNN-based PDU session setup with QoS flow configuration
- **NGAP Protocol**: Standard NGAP message construction and handling
- **Slice Awareness**: S-NSSAI configuration support for network slicing

### 4G LTE Capabilities
- **4G Attach Procedure**: Full LTE attach with NAS security (EIA2/EIA0 + EEA0)
- **EPS Bearer Establishment**: Default bearer setup with SGW TEID/address extraction
- **S1AP Protocol**: S1 Setup, InitialUEMessage, InitialContextSetup, E-RAB Setup
- **Milenage Authentication**: AUTN/RES verification, KASME derivation, NAS key generation

### Operational Benefits
- **Cross-Platform**: Works with both Free5GC and Open5GS core networks
- **Production Ready**: Comprehensive error handling and graceful degradation
- **Extensible Architecture**: Modular design for easy integration of new core networks

## 🌐 Supported Core Networks

| Core Network | Version | Status |
|--------------|---------|--------|
| **Free5GC** | v3.2+ | ✅ Production Ready |
| **Open5GS** | v2.4+ | ✅ Production Ready |

Both core networks support the same feature set with identical command-line interface.

## 🛠 Prerequisites

### System Requirements
- **Operating System**: Linux (Ubuntu 20.04+ recommended)
- **Python**: Python 3.8+
- **Network**: Docker/Docker Compose for core network deployment
- **Ports**: AMF 38412/SCTP (5G) or MME 36412/SCTP (4G) must be accessible

### Dependencies
- **pycrate**: ASN.1 encoding/decoding library (included in workspace)
- **CryptoMobile**: 3GPP cryptographic algorithms (included in workspace)
- **loguru**: Advanced logging library
- **requests**: HTTP client for core network API calls

All dependencies are automatically managed by the setup script.

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
# Core network
CORE_NETWORK_IP=192.168.55.53
GNB_ADDRESS=192.168.55.9
AMF_ADDRESS=192.168.55.53

# Subscriber
MCC=460
MNC=99
PERMANENT_KEY=465B5CE8B199B49FAA5F0A2EE238A6BC
OPC_VALUE=E8ED289DEBA952E4283B54E88E6183CA
DNN=internet
SLICES={"SST": 1}
GNB_NR_CELL_ID=1
```

**4G Configuration (additional):**
```ini
ENB_ADDRESS=192.168.55.9
MME_ADDRESS=192.168.55.53
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
Manage subscriber profiles in the core network.

```bash
# Create subscribers
python3 coresim_runner.py --mode provision --count 10 --core-network open5gs

# Delete subscribers
python3 coresim_runner.py --mode provision --count 10 --delete --core-network open5gs
```

### 5G UE Test Mode
Multi-UE registration and PDU session testing.

```bash
# Minimal — all params from .env
python3 coresim_runner.py --mode ue-test --core-network open5gs

# Override specific params via CLI
python3 coresim_runner.py --mode ue-test --count 20 \
    --gnb-address 192.168.55.9 --amf-address 192.168.55.53 \
    --dnn internet --log-level WARNING
```

### 4G UE Test Mode
Multi-UE LTE attach and EPS bearer testing.

```bash
# Minimal — all params from .env
python3 coresim_runner.py --mode 4g-test --core-network open5gs

# Override specific params via CLI
python3 coresim_runner.py --mode 4g-test --count 10 \
    --enb-address 192.168.55.9 --mme-address 192.168.55.53 \
    --apn internet --tac 000001
```

### Configuration Precedence
CLI arguments > `.env` file > built-in defaults. Any parameter can be set in `.env` and overridden on the command line.

## ⚙️ Configuration

### Environment Variables (`src/.env`)

**Common Parameters:**

| Parameter | Description | Default |
|-----------|-------------|--------|
| `CORE_NETWORK_IP` | Core network host IP | *(required)* |
| `MCC` | Mobile Country Code | `460` |
| `MNC` | Mobile Network Code | `99` |
| `PERMANENT_KEY` | Subscriber authentication key (Ki) | `465B...6BC` |
| `OPC_VALUE` | Operator ciphered variant (OPc) | `E8ED...3CA` |
| `INITIAL_IMSI_INDEX` | Starting IMSI suffix | `1` |
| `DEFAULT_SUBSCRIPTION_COUNT` | Default `--count` value | `2` |

**5G Parameters:**

| Parameter | Description | Default |
|-----------|-------------|--------|
| `GNB_ADDRESS` | gNodeB IP address | `192.168.55.9` |
| `AMF_ADDRESS` | AMF IP address | `192.168.55.53` |
| `DNN` | Data Network Name | `internet` |
| `SLICES` | Slice configuration JSON | `{"SST": 1}` |
| `GNB_NR_CELL_ID` | NR Cell ID | `1` |

**4G Parameters:**

| Parameter | Description | Default |
|-----------|-------------|--------|
| `ENB_ADDRESS` | eNodeB IP address | `192.168.55.9` |
| `MME_ADDRESS` | MME IP address | `192.168.55.53` |
| `MME_PORT` | MME SCTP port | `36412` |
| `ENB_ID` | eNodeB ID | `1` |
| `ENB_CELL_ID` | eNodeB Cell ID | `1000000` |
| `TAC` | Tracking Area Code | `000001` |
| `APN` | Access Point Name | `internet` |
| `IMEISV` | IMEISV value | `4370816125816151` |

### Command Line Arguments
Override `.env` settings with command-line arguments:

| Argument | Description | Example |
|----------|-------------|--------|
| `--mode` | Operation mode | `provision`, `ue-test`, `4g-test` |
| `--count` | Number of UEs/subscribers | `1`, `10`, `100` |
| `--core-network` | Core network type | `free5gc`, `open5gs` |
| `--gnb-address` | gNodeB IP (5G) | `192.168.55.9` |
| `--amf-address` | AMF IP (5G) | `192.168.55.53` |
| `--enb-address` | eNodeB IP (4G) | `192.168.55.9` |
| `--mme-address` | MME IP (4G) | `192.168.55.53` |
| `--mme-port` | MME port (4G) | `36412` |
| `--dnn` | Data Network Name (5G) | `internet` |
| `--apn` | Access Point Name (4G) | `internet` |
| `--tac` | Tracking Area Code | `000001` |
| `--log-level` | Logging verbosity | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `--delete` | Delete mode (provision only) | *(flag)* |

## 📊 Performance & Scaling

### Recommended Configurations

| UE Count | Log Level | Estimated Time | System Requirements |
|----------|-----------|----------------|-------------------|
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
|---------|-----------|----------|
| **Import Errors** | Missing dependencies | Run `bash setup.sh` |
| **Connection Refused** | AMF not reachable | Check AMF status and port 38412 |
| **Authentication Failed** | Invalid subscriber data | Verify KI/OPC match subscription |
| **Timeout Errors** | Network congestion | Reduce UE count, increase timeout |
| **Duplicate Subscriptions** | IMSI already exists | Delete existing subscriptions first |
| **Too Many Files** | File descriptor limit | Run `ulimit -n 65536` |

### Diagnostic Commands
```bash
# Test imports
python3 test_imports.py

# Check AMF connectivity
telnet 192.168.55.53 38412

# View core network logs
docker logs free5gc_amf -f  # Free5GC
journalctl -u open5gs-amfd -f  # Open5GS

# Capture NGAP traffic
sudo tcpdump -i any port 38412 -w capture.pcap
```

### Debugging Steps
1. Enable debug logging: `--log-level DEBUG`
2. Verify subscription exists in core network
3. Check network connectivity between gNodeB and AMF
4. Review AMF logs for detailed error messages
5. Validate configuration parameters in `.env`

## 🏗 Architecture

### Module Structure
```
src/
├── core_network/               # Core network abstraction layer
│   ├── core_network.py         # Base interface
│   ├── core_network_factory.py # Factory pattern
│   ├── free5gc_impl.py         # Free5GC implementation
│   └── open5gs_impl.py         # Open5GS implementation
├── integration/                # Protocol integration
│   ├── integrated_gnb.py       # 5G gNodeB simulator
│   ├── integrated_ue.py        # 5G UE state machine
│   ├── integrated_messages.py  # 5G NGAP message handling
│   ├── integrated_4g_gnb.py    # 4G eNodeB simulator
│   ├── integrated_4g_ue.py     # 4G UE state machine
│   ├── integrated_4g_messages.py # 4G S1AP message handling
│   └── eNAS.py                 # 4G NAS codec (encode/decode)
├── config_loader.py            # Configuration management (.env + JSON)
├── coresim_runner.py           # Main entry point (CLI)
└── ue_test_runner.py           # 5G multi-UE test orchestration
```

### Design Principles
- **Separation of Concerns**: Core network logic separated from 5G protocol implementation
- **Factory Pattern**: Easy addition of new core network types
- **Automatic Path Resolution**: No manual dependency configuration required
- **Thread Safety**: Safe concurrent execution for multi-UE testing
- **Comprehensive Error Handling**: Graceful degradation and informative error messages

## 📄 Documentation

Detailed documentation is available in the [`docs/`](docs/) directory:

- **[QUICKSTART.md](docs/QUICKSTART.md)**: Step-by-step getting started guide
- **[TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**: Comprehensive problem-solving guide  
- **[INTEGRATION_SUMMARY.md](docs/INTEGRATION_SUMMARY.md)**: Technical integration details
- **[FIX_SUMMARY.md](docs/FIX_SUMMARY.md)**: Implementation and fix history

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**CoreSimRunner v1.0.0**  
*Production Ready • Multi-UE Testing • Cross-Platform Compatible*

For support and issues, please refer to the troubleshooting documentation or contact the development team.
# coresimrunner
