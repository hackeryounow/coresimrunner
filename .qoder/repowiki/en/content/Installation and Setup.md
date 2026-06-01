# Installation and Setup

<cite>
**Referenced Files in This Document**
- [setup.sh](file://setup.sh)
- [requirements.txt](file://requirements.txt)
- [test_imports.py](file://src/tests/test_imports.py)
- [README.md](file://README.md)
- [TROUBLESHOOTING.md](file://docs/TROUBLESHOOTING.md)
- [coresim_runner.py](file://src/coresim_runner.py)
- [config_loader.py](file://src/config_loader.py)
- [free5gc_subscription_template.json](file://config/free5gc_subscription_template.json)
- [open5gs_subscription_template.json](file://config/open5gs_subscription_template.json)
- [ue_test_runner.py](file://src/ue_test_runner.py)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [System Requirements](#system-requirements)
3. [Step-by-Step Installation](#step-by-step-installation)
4. [Dependency Management](#dependency-management)
5. [Environment Configuration](#environment-configuration)
6. [Verification Procedures](#verification-procedures)
7. [Troubleshooting Common Issues](#troubleshooting-common-issues)
8. [Cross-Platform Compatibility](#cross-platform-compatibility)
9. [Production Deployment Recommendations](#production-deployment-recommendations)
10. [Appendices](#appendices)

## Introduction
This document provides comprehensive guidance for preparing the CoreSimRunner environment, managing dependencies, and verifying the installation. CoreSimRunner is a multi-UE 5G core network testing framework that supports both Free5GC and Open5GS core networks. The installation process focuses on automatic dependency resolution, environment setup, and validation procedures to ensure a smooth deployment.

## System Requirements
CoreSimRunner requires a Linux-based environment with specific software and network prerequisites:

- Operating System: Linux (Ubuntu 20.04+ recommended)
- Python: Python 3.8+ (the project demonstrates compatibility with Python 3.9 in related components)
- Network: Docker/Docker Compose for core network deployment
- Ports: AMF port 38412/SCTP must be accessible
- Additional: File descriptor limits may need adjustment for high-concurrency testing

These requirements are essential for reliable operation of the testing framework and core network integration.

**Section sources**
- [README.md:50-57](file://README.md#L50-L57)

## Step-by-Step Installation
The installation process is streamlined through an automated setup script that handles dependency installation, environment preparation, and initial configuration:

1. Navigate to the project directory and execute the setup script:
   - Change to the project root directory
   - Run the setup script to initialize the environment

2. The setup script performs the following actions:
   - Creates necessary directories (logs, config, current)
   - Installs Python dependencies from requirements.txt
   - Installs additional core dependencies (loguru, pycryptodome, pysocks)
   - Checks for external libraries (pycrate, CryptoMobile) and provides guidance if missing
   - Generates a default .env configuration file with essential parameters

3. After setup completion, the script provides usage instructions for different operational modes:
   - 5G/4G provisioning with configurable subscriber counts
   - UE testing with multi-UE concurrent registration
   - 4G testing scenarios

The setup process ensures that all core dependencies are installed and the environment is ready for immediate testing.

**Section sources**
- [setup.sh:1-60](file://setup.sh#L1-L60)
- [README.md:66-78](file://README.md#L66-L78)

## Dependency Management
CoreSimRunner employs a dual approach to dependency management:

### Automatic Dependency Resolution
The setup script automatically installs core Python dependencies using pip:
- Primary dependencies are defined in requirements.txt
- Additional core dependencies are installed directly by the setup script
- External libraries (pycrate, CryptoMobile) are checked and flagged if not found

### Core Dependencies
The project relies on several key libraries:

- **pycrate**: ASN.1 encoding/decoding library for protocol handling
- **CryptoMobile**: 3GPP cryptographic algorithms for authentication
- **loguru**: Advanced logging framework
- **requests**: HTTP client for core network API interactions
- **pycryptodome**: Cryptographic primitives
- **tqdm**: Progress bar for long-running operations

### External Library Integration
The system includes special handling for external libraries located in the workspace:
- pycrate and CryptoMobile are added to the Python path
- Workspace libraries are automatically detected and included
- Manual path configuration is supported for environments where libraries are installed separately

### Dependency Verification
The test_imports.py script provides comprehensive validation of all dependencies:
- Verifies import functionality for all core modules
- Tests protocol handling libraries (pycrate ASN.1, pycrate mobile)
- Confirms cryptographic libraries (CryptoMobile, pycryptodome)
- Validates logging and HTTP client functionality
- Ensures internal module imports work correctly

**Section sources**
- [requirements.txt:1-8](file://requirements.txt#L1-L8)
- [setup.sh:11-27](file://setup.sh#L11-L27)
- [test_imports.py:23-115](file://src/tests/test_imports.py#L23-L115)
- [ue_test_runner.py:18-29](file://src/ue_test_runner.py#L18-L29)

## Environment Configuration
CoreSimRunner uses a centralized configuration system managed through .env files and JSON templates:

### .env Configuration File
The setup script generates a comprehensive .env file with essential parameters:
- Core network selection (Free5GC or Open5GS)
- Network addresses (gNodeB, AMF, MME)
- Subscriber parameters (MCC, MNC, IMSI indexing)
- Authentication keys (KI, OPC)
- DNN configuration and slice settings
- Logging levels and performance parameters

### Configuration Loading Mechanism
The ConfigLoader class provides robust configuration management:
- Reads and parses .env files with support for comments and quotes
- Handles variable substitution using ${VAR_NAME} syntax
- Loads JSON configuration templates with placeholder replacement
- Provides type-safe access to configuration values
- Supports network-specific configurations for different core networks

### Template-Based Configuration
CoreSimRunner uses JSON templates for core network subscriptions:
- Free5GC subscription template with comprehensive 5G configuration
- Open5GS subscription template with 4G/5G hybrid support
- Templates include authentication parameters, QoS settings, and slice configurations
- Placeholders in templates are automatically replaced with runtime configuration values

### Runtime Configuration Override
Command-line arguments can override .env settings:
- Core network type selection
- Network addresses and ports
- Subscriber parameters and authentication keys
- Logging levels and test parameters
- Slice configurations and DNN settings

**Section sources**
- [setup.sh:29-53](file://setup.sh#L29-L53)
- [config_loader.py:14-150](file://src/config_loader.py#L14-L150)
- [free5gc_subscription_template.json:1-222](file://config/free5gc_subscription_template.json#L1-L222)
- [open5gs_subscription_template.json:1-109](file://config/open5gs_subscription_template.json#L1-L109)
- [coresim_runner.py:70-90](file://src/coresim_runner.py#L70-L90)

## Verification Procedures
CoreSimRunner provides multiple verification mechanisms to ensure proper installation and configuration:

### Import Validation
The test_imports.py script performs comprehensive import testing:
- Validates all core dependencies can be imported successfully
- Tests protocol handling libraries (pycrate ASN.1, pycrate mobile)
- Confirms cryptographic library functionality (CryptoMobile, pycryptodome)
- Verifies internal module imports work correctly
- Provides detailed error reporting for failed imports

### Environment Setup Verification
The diagnostic approach includes:
- Python version compatibility checks
- Dependency availability verification
- Network connectivity testing (AMF accessibility)
- Port availability validation (SCTP 38412)
- System resource assessment (file descriptor limits)

### Configuration Validation
Configuration verification includes:
- .env file existence and parsing
- JSON template loading and validation
- Placeholder substitution correctness
- Network parameter reachability
- Authentication parameter validity

### Practical Verification Commands
Recommended verification procedures:
- Run the import test script to validate all dependencies
- Execute basic provisioning operations to test core network integration
- Perform small-scale UE registration tests
- Verify subscription creation and deletion functionality
- Check logging output and configuration parameter application

**Section sources**
- [test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)
- [README.md:74-78](file://README.md#L74-L78)
- [TROUBLESHOOTING.md:415-449](file://docs/TROUBLESHOOTING.md#L415-L449)

## Troubleshooting Common Issues
CoreSimRunner includes comprehensive troubleshooting guidance for common installation and runtime problems:

### Import Errors
Common symptoms: ImportError for pycrate or CryptoMobile modules
- Verify the setup script executed successfully
- Check Python path configuration for workspace libraries
- Ensure external libraries are properly installed
- Use the diagnostic script to identify missing dependencies

### Connection Issues
Symptoms: Connection refused to AMF or network timeouts
- Verify core network containers are running
- Check SCTP port accessibility (38412)
- Validate firewall rules and network connectivity
- Confirm AMF service availability and configuration

### Authentication Problems
Issues with subscriber authentication or registration failures
- Verify subscription data matches configuration parameters
- Check KI/OPC values alignment with core network settings
- Validate PLMN configuration consistency
- Review AMF authentication logs for detailed error information

### Performance and Resource Issues
Slow performance or system resource exhaustion with high UE counts
- Adjust logging levels to reduce overhead
- Increase system resource limits (file descriptors)
- Optimize network buffer settings
- Consider reducing concurrent UE count for large-scale tests

### Configuration Problems
Errors related to .env file parsing or template loading
- Validate .env file syntax and parameter formatting
- Check JSON template file paths and accessibility
- Verify placeholder substitution correctness
- Ensure network addresses are reachable from the test environment

**Section sources**
- [TROUBLESHOOTING.md:1-449](file://docs/TROUBLESHOOTING.md#L1-L449)
- [README.md:200-235](file://README.md#L200-L235)

## Cross-Platform Compatibility
CoreSimRunner is designed primarily for Linux environments with specific platform considerations:

### Primary Platform
- Linux (Ubuntu 20.04+) is the recommended and tested platform
- Native support for Linux networking stack and system resources
- Full compatibility with Docker and Docker Compose deployments

### Network Stack Dependencies
- SCTP protocol support is essential for AMF communication
- System-level networking configuration affects performance
- File descriptor limits impact concurrent UE testing capacity

### Alternative Environments
While the project is optimized for Linux, potential approaches for other platforms include:
- Using Docker containers to isolate Linux dependencies
- Virtual machines with Linux distributions
- WSL2 for Windows environments (with networking limitations)
- Cloud-based Linux instances for scalable testing

### Platform-Specific Considerations
- Network interface naming and configuration
- File system permissions and path resolution
- System resource limits and tuning
- Package manager differences for dependency installation

## Production Deployment Recommendations
For production-ready deployments, CoreSimRunner recommends the following best practices:

### Infrastructure Requirements
- Dedicated hardware or cloud instances with adequate CPU and memory resources
- Stable network connectivity between test environment and core networks
- Proper storage allocation for logs and test artifacts
- Backup and recovery procedures for test data

### Security Considerations
- Secure handling of authentication parameters (KI, OPC, API keys)
- Network segmentation between test and production environments
- Regular security updates for all dependencies
- Access control for administrative interfaces

### Monitoring and Logging
- Implement comprehensive logging for all test operations
- Monitor system resources during large-scale tests
- Set up alerting for critical failures or performance degradation
- Archive test results and performance metrics for analysis

### Scalability Planning
- Start with small UE counts and gradually scale up
- Monitor resource utilization and adjust system configuration
- Consider distributed testing architectures for very large scales
- Plan for concurrent test execution across multiple test instances

### Maintenance and Updates
- Regular updates to core network software and dependencies
- Automated testing of upgrade procedures
- Documentation maintenance for configuration changes
- Performance benchmarking and optimization cycles

## Appendices

### Quick Reference Commands
- Setup: `bash setup.sh`
- Import verification: `python3 test_imports.py`
- Basic provisioning: `python3 coresim_runner.py --mode provision --count 1`
- UE testing: `python3 coresim_runner.py --mode ue-test --count 1`
- 4G testing: `python3 coresim_runner.py --mode 4g-test --count 1`

### Configuration Parameters
- CORE_NETWORK: free5gc or open5gs
- GNB_ADDRESS: gNodeB IP address
- AMF_ADDRESS: AMF IP address
- MCC/MNC: Mobile country and network codes
- PERMANENT_KEY: Authentication key
- OPC_VALUE: Operator ciphered variant
- DNN: Data network name
- SLICES: Slice configuration JSON

### Dependency Versions
- Python: 3.8+
- pycrate: 0.7.9
- CryptoMobile: >=0.3.0
- loguru: >=0.5.0
- requests: >=2.25.0
- pycryptodome: >=3.10.0
- tqdm: >=4.60.0