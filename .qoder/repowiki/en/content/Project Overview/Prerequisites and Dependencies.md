# Prerequisites and Dependencies

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [setup.sh](file://setup.sh)
- [requirements.txt](file://requirements.txt)
- [test_imports.py](file://src/tests/test_imports.py)
- [TROUBLESHOOTING.md](file://docs/TROUBLESHOOTING.md)
- [coresim_runner.py](file://src/coresim_runner.py)
- [config_loader.py](file://src/config_loader.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [System Requirements](#system-requirements)
3. [Software Dependencies](#software-dependencies)
4. [Environment Setup](#environment-setup)
5. [Verification Procedures](#verification-procedures)
6. [Resource Recommendations](#resource-recommendations)
7. [Network Requirements](#network-requirements)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document provides comprehensive prerequisites and dependency management guidance for CoreSimRunner. It covers system requirements, software dependencies, environment setup, verification procedures, resource recommendations, network requirements, and troubleshooting steps for dependency-related issues.

## System Requirements
CoreSimRunner requires:
- Operating System: Linux (Ubuntu 20.04+ recommended)
- Python: Python 3.8+
- Docker and Docker Compose for core network deployment
- Accessible AMF port 38412/SCTP for NGAP communication

These requirements are documented in the project's README and are essential for running the framework successfully.

**Section sources**
- [README.md:52-56](file://README.md#L52-L56)

## Software Dependencies
CoreSimRunner depends on the following Python packages:
- pycrate: ASN.1 encoding/decoding library (included in workspace)
- CryptoMobile: 3GPP cryptographic algorithms (included in workspace)
- loguru: Advanced logging library
- requests: HTTP client for core network API calls
- pycryptodome: Cryptographic primitives
- tqdm: Progress bar for CLI operations
- pysocks: SOCKS proxy support

The primary dependencies are declared in the requirements file, while pycrate and CryptoMobile are included in the workspace and must be added to the Python path.

**Section sources**
- [README.md:58-64](file://README.md#L58-L64)
- [requirements.txt:1-7](file://requirements.txt#L1-L7)

## Environment Setup
CoreSimRunner provides an automated setup process through a dedicated script that:
- Creates necessary directories (logs, config, current)
- Installs Python dependencies from requirements.txt
- Installs additional core dependencies (loguru, pycryptodome, pysocks)
- Checks availability of pycrate and CryptoMobile
- Generates a default .env configuration file with essential parameters

Manual setup steps include:
1. Running the setup script to initialize the environment
2. Verifying dependency installation using the import test script
3. Configuring the .env file with core network settings

The setup script ensures all dependencies are properly installed and available for use.

**Section sources**
- [setup.sh:1-60](file://setup.sh#L1-L60)

## Verification Procedures
CoreSimRunner includes a comprehensive import verification script that:
- Adds workspace libraries (pycrate and CryptoMobile) to the Python path
- Tests imports for all required modules including pycrate_asn1dir, CryptoMobile, loguru, and internal modules
- Validates that all dependencies are correctly installed and accessible
- Provides clear pass/fail feedback for each import test

Verification steps:
1. Run the import test script after setup completion
2. Confirm all import tests pass successfully
3. Use the diagnostic commands from the troubleshooting guide for additional checks

**Section sources**
- [test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)

## Resource Recommendations
CoreSimRunner provides performance guidelines for different test scales:
- Small tests (1-10 UEs): 2 CPU cores, 4 GB RAM, INFO logging level
- Medium tests (10-50 UEs): 4 CPU cores, 8 GB RAM, WARNING logging level
- Large tests (50-100 UEs): 8 CPU cores, 16 GB RAM, ERROR logging level
- Very large tests (100+ UEs): 16+ CPU cores, 32+ GB RAM, ERROR logging level

These recommendations help ensure optimal performance during multi-UE testing scenarios.

**Section sources**
- [README.md:184-191](file://README.md#L184-L191)

## Network Requirements
CoreSimRunner requires specific network configurations:
- AMF port 38412/SCTP must be accessible for NGAP communication
- gNodeB (192.168.55.9) must be able to reach AMF (192.168.55.53) on port 38412
- Core network components (AMF, SMF, UPF) must be deployed and accessible
- Proper firewall configuration to allow SCTP traffic

Network connectivity verification includes:
- Ping tests between components
- Port accessibility checks using telnet or netcat
- AMF status verification through Docker or systemd

**Section sources**
- [README.md:56](file://README.md#L56)
- [TROUBLESHOOTING.md:32-63](file://docs/TROUBLESHOOTING.md#L32-L63)

## Troubleshooting Guide
Common dependency-related issues and solutions:
- Import errors for pycrate_asn1dir or CryptoMobile: Run setup script or manually add workspace paths to PYTHONPATH
- Missing Python dependencies: Execute setup script to install requirements
- Connection refused to AMF: Verify AMF service status, port accessibility, and firewall rules
- Authentication failures: Check KI/OPC values, subscription existence, and PLMN configuration
- Timeout errors: Reduce UE count, increase timeouts, or optimize system resources

Diagnostic procedures include:
- Using the import test script to verify all dependencies
- Checking AMF connectivity with telnet/netstat
- Capturing NGAP traffic with tcpdump for analysis
- Reviewing core network logs for detailed error messages

**Section sources**
- [TROUBLESHOOTING.md:5-28](file://docs/TROUBLESHOOTING.md#L5-L28)
- [TROUBLESHOOTING.md:280-297](file://docs/TROUBLESHOOTING.md#L280-L297)

## Conclusion
CoreSimRunner's prerequisites and dependencies are designed for straightforward setup and reliable operation. The automated setup script handles most dependency management tasks, while the verification procedures ensure proper configuration. Following the system requirements, installing the specified dependencies, and verifying connectivity will enable successful multi-UE testing of 5G core networks.