# Troubleshooting and Diagnostics

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [diagnose_nas_mac.py](file://scripts/diagnose_nas_mac.py)
- [test_imports.py](file://src/tests/test_imports.py)
- [coresim_runner.py](file://src/coresim_runner.py)
- [integrated_4g_messages.py](file://src/integration/integrated_4g_messages.py)
- [integrated_gnb.py](file://src/integration/integrated_gnb.py)
- [config_loader.py](file://src/config_loader.py)
- [setup.sh](file://setup.sh)
</cite>

## Update Summary
**Changes Made**
- Updated troubleshooting section to reflect the comprehensive troubleshooting documentation now included in README.md
- Enhanced diagnostic procedures with practical solutions and diagnostic commands
- Added systematic approach to problem identification and resolution strategies
- Improved coverage of common issues including import errors, connection problems, authentication failures, timeout errors, and duplicate subscription conflicts
- Expanded diagnostic commands for testing imports, checking AMF connectivity, viewing core network logs, capturing NGAP traffic, and NAS MAC diagnosis
- Added practical troubleshooting workflows, error message interpretation, and step-by-step resolution procedures

## Table of Contents
1. [Introduction](#introduction)
2. [Systematic Troubleshooting Approach](#systematic-troubleshooting-approach)
3. [Common Issues and Solutions](#common-issues-and-solutions)
4. [Diagnostic Commands and Tools](#diagnostic-commands-and-tools)
5. [NAS MAC Diagnosis Procedures](#nas-mac-diagnosis-procedures)
6. [Log Analysis Techniques](#log-analysis-techniques)
7. [Network Connectivity Verification](#network-connectivity-verification)
8. [Practical Troubleshooting Workflows](#practical-troubleshooting-workflows)
9. [Error Message Interpretation](#error-message-interpretation)
10. [Debugging Steps for Different Failure Scenarios](#debugging-steps-for-different-failure-scenarios)
11. [Performance Bottleneck Identification](#performance-bottleneck-identification)
12. [Resource Constraint Troubleshooting](#resource-constraint-troubleshooting)
13. [Escalation Procedures for Complex Issues](#escalation-procedures-for-complex-issues)

## Introduction
CoreSimRunner provides a comprehensive troubleshooting and diagnostics framework designed to systematically identify, diagnose, and resolve common issues in multi-UE 5G/4G core network testing environments. This guide focuses on practical problem identification, diagnosis procedures, and resolution strategies for import errors, connection problems, authentication failures, timeout errors, and duplicate subscription conflicts. It covers diagnostic commands for testing imports, checking AMF connectivity, viewing core network logs, capturing NGAP traffic, NAS MAC diagnosis, log analysis techniques, and network connectivity verification. The documentation includes practical troubleshooting workflows, error message interpretation, and step-by-step resolution procedures, along with debugging steps for different failure scenarios, performance bottleneck identification, resource constraint troubleshooting, and escalation procedures for complex issues.

## Systematic Troubleshooting Approach
The CoreSimRunner troubleshooting methodology follows a structured, step-by-step approach that ensures comprehensive problem identification and resolution:

### Phase 1: Initial Assessment
- Verify system prerequisites and dependencies
- Check environment configuration and network connectivity
- Validate core network status and accessibility

### Phase 2: Problem Classification
- Categorize issues into import errors, connection problems, authentication failures, timeout errors, or duplicate subscription conflicts
- Identify the specific component affected (imports, AMF connectivity, core network, NAS processing)

### Phase 3: Diagnostic Execution
- Run targeted diagnostic commands based on problem classification
- Analyze logs and error messages for detailed insights
- Compare expected vs. actual behavior

### Phase 4: Resolution Implementation
- Apply appropriate fixes based on diagnostic findings
- Verify resolution through follow-up tests
- Document lessons learned and preventive measures

### Phase 5: Prevention and Optimization
- Implement monitoring and alerting mechanisms
- Optimize system configuration for reliability
- Establish best practices for future deployments

## Common Issues and Solutions

### Import Errors
**Symptoms**: ImportError exceptions indicating missing modules or failed imports
**Root Causes**: Missing dependencies, incorrect Python path configuration, or workspace path issues
**Solutions**:
- Run `bash setup.sh` to install all required dependencies
- Execute `python3 test_imports.py` to verify all imports succeed
- Ensure workspace paths are correctly configured in Python path
- Verify `pycrate` and `CryptoMobile` libraries are accessible

### Connection Problems
**Symptoms**: Connection refused errors, timeout during AMF connection, or SCTP association failures
**Root Causes**: AMF service not running, firewall blocking ports, incorrect network configuration, or SCTP support issues
**Solutions**:
- Verify AMF container/service status and port accessibility
- Check firewall rules and network connectivity between gNodeB and AMF
- Ensure SCTP support is available and properly configured
- Validate AMF address and port configuration in `.env` file

### Authentication Failures
**Symptoms**: Authentication rejected by core network, MAC verification failures, or subscriber validation errors
**Root Causes**: Incorrect KI/OPC values, PLMN mismatch, expired AUTN values, or subscription data inconsistencies
**Solutions**:
- Verify subscription exists in core network database
- Confirm KI and OPC values match subscription profile
- Ensure PLMN configuration matches command parameters
- Check AUTN freshness and sequence number synchronization
- Review AMF authentication logs for detailed error messages

### Timeout Errors
**Symptoms**: Test execution exceeding configured timeout limits, registration failures, or session establishment timeouts
**Root Causes**: Network congestion, insufficient system resources, high UE concurrency, or AMF performance issues
**Solutions**:
- Increase timeout values in test configuration
- Reduce concurrent UE count for large-scale tests
- Monitor AMF performance and resource utilization
- Stagger UE initialization to avoid system overload
- Optimize network parameters and buffer sizes

### Duplicate Subscription Conflicts
**Symptoms**: "Subscription already exists" errors or IMSI conflicts during provisioning
**Root Causes**: Existing subscriber profiles, overlapping IMSI ranges, or configuration conflicts
**Solutions**:
- Delete existing subscriptions before provisioning new ones
- Change starting IMSI index in `.env` configuration
- Specify unique start-imsi parameter on command line
- Clean up core network database of stale entries

### Too Many Files Errors
**Symptoms**: "Too many open files" or file descriptor limit exceeded errors
**Root Causes**: Insufficient system file descriptor limits for high concurrency testing
**Solutions**:
- Increase file descriptor limits: `ulimit -n 65536`
- Optimize file handle management in test execution
- Reduce concurrent connections during peak loads
- Implement proper resource cleanup and disposal

**Section sources**
- [README.md:252-264](file://README.md#L252-L264)

## Diagnostic Commands and Tools

### Import Verification
**Command**: `python3 test_imports.py`
**Purpose**: Validates all required dependencies are available and paths are configured correctly
**Expected Output**: All import tests should pass successfully
**Troubleshooting**: If imports fail, run `bash setup.sh` and verify Python path configuration

### AMF Connectivity Testing
**Command**: `telnet 192.168.55.53 38412`
**Purpose**: Tests SCTP port accessibility between test runner and AMF
**Alternative**: `nc 192.168.55.53 38412`
**Expected Result**: Successful connection indicates network connectivity is established

### Core Network Log Monitoring
**Free5GC**: `docker logs free5gc_amf -f`
**Open5GS**: `journalctl -u open5gs-amfd -f`
**Purpose**: Real-time monitoring of core network operations and error detection
**Usage**: Tail logs during test execution to capture error messages and warnings

### NGAP Traffic Capture
**Command**: `sudo tcpdump -i any port 38412 -w ngap_capture.pcap`
**Purpose**: Captures NGAP protocol traffic for detailed analysis
**Analysis**: Use Wireshark or tshark to analyze captured packets and identify protocol-level issues

### Subscription Data Verification
**Command**: `curl` API endpoints or web UI/database queries
**Purpose**: Verifies subscription data consistency and configuration accuracy
**Scope**: Checks subscriber profiles, authentication parameters, and network slice configurations

### Debug Logging Enablement
**Command**: Add `--log-level DEBUG` to coresim_runner.py commands
**Purpose**: Increases logging verbosity for detailed troubleshooting information
**Usage**: Enable during problem reproduction to capture comprehensive diagnostic information

**Section sources**
- [README.md:265-279](file://README.md#L265-L279)

## NAS MAC Diagnosis Procedures

### NAS MAC Diagnostic Tool Usage
**Command**: `python3 scripts/diagnose_nas_mac.py --plmn 46099 --ki 1234...0000 --opc 71a1...131f --enc-alg 1 --int-alg 2`
**Purpose**: Identifies root causes of NAS MAC verification failures by comparing eNB reference implementation and CoreSimRunner integration code

### Diagnostic Process Flow
1. **Input Parameter Validation**: Verify PLMN encoding, KI/OPC values, and algorithm selections
2. **Milenage Computation**: Validate RES, CK, IK derivation using provided parameters
3. **PLMN Encoding Comparison**: Compare eNB reference vs. CoreSimRunner PLMN encoding for KASME derivation
4. **KASME Derivation Analysis**: Check KASME calculation consistency between implementations
5. **NAS Key Derivation**: Validate NAS encryption and integrity key derivation
6. **Security Mode Complete Construction**: Build and compare Security Mode Complete messages
7. **MAC Computation Verification**: Compare MAC calculations between implementations

### Key Diagnostic Areas
- **PLMN Encoding**: Critical difference between eNB reference (correct 3GPP 24.301) and CoreSimRunner (incorrect S1AP format)
- **Algorithm Selection**: Ensure correct EEA/EIA algorithm values and counter synchronization
- **Key Derivation**: Validate KASME and NAS key derivation processes
- **Message Construction**: Verify proper NAS message encoding and security header formatting

**Section sources**
- [diagnose_nas_mac.py:1-650](file://scripts/diagnose_nas_mac.py#L1-L650)

## Log Analysis Techniques

### Structured Log Filtering
- Filter logs by severity level (ERROR, WARNING, INFO, DEBUG)
- Filter by component (AMF, gNB, core network services)
- Correlate timestamps across multiple components for timeline analysis
- Search for specific error keywords and patterns

### Error Pattern Recognition
- Authentication failures: Look for "authentication rejected", "MAC verification failed", "invalid subscriber"
- Connection issues: Identify "connection refused", "timeout", "port unavailable"
- Protocol errors: Search for "ASN.1 decode failed", "message format error", "protocol violation"
- Resource constraints: Monitor "too many open files", "memory exhausted", "connection pool full"

### Timeline Analysis
- Correlate events across AMF, gNodeB, and UE components
- Identify causality chains in multi-component failures
- Track error propagation and recovery attempts
- Analyze performance degradation patterns over time

### Log Rotation and Retention
- Configure appropriate log rotation policies for long-running tests
- Ensure critical error logs are preserved for post-mortem analysis
- Balance log volume with storage capacity requirements
- Implement log aggregation for distributed testing environments

## Network Connectivity Verification

### Basic Connectivity Tests
- **Ping Test**: Verify basic IP connectivity between test runner and AMF
- **Port Testing**: Use telnet or netcat to test SCTP port 38412 accessibility
- **DNS Resolution**: Validate hostname-to-IP mapping for core network components
- **Firewall Rules**: Check inbound/outbound rules for required ports and protocols

### Protocol-Level Testing
- **SCTP Association**: Verify SCTP connection establishment between gNodeB and AMF
- **NGAP Message Exchange**: Test basic NGAP setup and teardown procedures
- **NAS Message Flow**: Validate initial NAS message exchange during registration
- **Session Establishment**: Test PDU session creation and tear-down procedures

### Network Performance Metrics
- **Latency Measurement**: Monitor round-trip times for critical network operations
- **Throughput Testing**: Verify adequate bandwidth for concurrent UE testing
- **Packet Loss Detection**: Identify network quality issues affecting test reliability
- **Jitter Analysis**: Monitor timing variations that could affect NAS message synchronization

### Troubleshooting Network Issues
- **Path Tracing**: Use traceroute to identify network bottlenecks and routing issues
- **Bandwidth Testing**: Verify network capacity meets test requirements
- **Quality of Service**: Check network QoS settings affecting real-time traffic
- **Security Policies**: Validate firewall and security policies allowing test traffic

## Practical Troubleshooting Workflows

### Workflow 1: Import Errors
**Problem**: ImportError indicating missing modules
**Step-by-Step Resolution**:
1. Run `python3 test_imports.py` to identify failing imports
2. Execute `bash setup.sh` to install missing dependencies
3. Manually add workspace paths if needed using `export PYTHONPATH`
4. Verify imports with `python3 test_imports.py` again
5. Check Python version compatibility (3.8+ required)

**Section sources**
- [test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)
- [setup.sh:11-27](file://setup.sh#L11-L27)

### Workflow 2: Connection Refused to AMF
**Problem**: Socket connection failure to AMF service
**Step-by-Step Resolution**:
1. Check AMF container/service status using `docker ps` or `systemctl status`
2. Verify AMF is listening on port 38412 using `netstat -tulpn | grep 38412`
3. Test port accessibility with `telnet 192.168.55.53 38412`
4. Inspect firewall rules for port 38412 blocking
5. Verify network connectivity between test runner and AMF
6. Check AMF logs for startup errors or configuration issues

**Section sources**
- [README.md:259](file://README.md#L259)

### Workflow 3: NGAP Setup Failed
**Problem**: AMF rejects NGAP setup requests
**Step-by-Step Resolution**:
1. Verify PLMN configuration matches between test runner and AMF
2. Check AMF logs for specific setup failure reasons
3. Validate gNodeB address is reachable from AMF network perspective
4. Confirm core network IP addresses are correctly configured
5. Review AMF configuration for supported PLMN and cell parameters
6. Test basic connectivity using simple telnet or netcat commands

**Section sources**
- [README.md:259](file://README.md#L259)

### Workflow 4: Authentication Failed
**Problem**: Core network rejects authentication parameters
**Step-by-Step Resolution**:
1. Verify subscription exists in core network database
2. Check KI and OPC values match subscription profile exactly
3. Confirm PLMN configuration matches authentication command parameters
4. Validate AUTN freshness and sequence number synchronization
5. Review AMF authentication logs for detailed error messages
6. Test with known-good credentials to isolate parameter issues

**Section sources**
- [README.md:260](file://README.md#L260)

### Workflow 5: PDU Session Establishment Failed
**Problem**: DNN configuration or UPF connectivity issues
**Step-by-Step Resolution**:
1. Verify DNN is configured in subscriber subscription profile
2. Check UPF status and reachability from AMF perspective
3. Validate slice configuration (SST/SD) matches test requirements
4. Review SMF logs for UPF communication errors
5. Test basic connectivity between AMF and UPF
6. Verify network slice configuration in core network

**Section sources**
- [README.md:260](file://README.md#L260)

### Workflow 6: Timeout During Registration
**Problem**: Exceeded configured timeout during UE registration
**Step-by-Step Resolution**:
1. Increase timeout values in test configuration or command line
2. Reduce concurrent UE count for large-scale tests
3. Monitor AMF performance and resource utilization during test
4. Stagger UE initialization to avoid system overload
5. Check network latency and optimize connection parameters
6. Review AMF logs for performance bottlenecks

**Section sources**
- [README.md:261](file://README.md#L261)

### Workflow 7: Duplicate IMSI Error
**Problem**: Duplicate IMSI detected during subscription provisioning
**Step-by-Step Resolution**:
1. Delete existing subscriptions using provision mode with `--delete` flag
2. Change starting IMSI index in `.env` configuration file
3. Specify unique start-imsi parameter on command line
4. Verify IMSI uniqueness in core network database
5. Test with reduced UE count to avoid conflicts
6. Clean up any remaining stale subscription entries

**Section sources**
- [README.md:262](file://README.md#L262)

### Workflow 8: SCTP Association Failed
**Problem**: SCTP support missing or AMF not configured for SCTP
**Step-by-Step Resolution**:
1. Check SCTP kernel module availability using `lsmod | grep sctp`
2. Install SCTP libraries if needed using package manager
3. Verify AMF configuration supports SCTP protocol
4. Test SCTP connectivity using specialized tools
5. Check firewall rules allow SCTP traffic
6. Validate network infrastructure supports SCTP protocol

**Section sources**
- [README.md:263](file://README.md#L263)

## Error Message Interpretation

### Import Error Messages
**Common Patterns**: "ImportError: No module named ..." or "ModuleNotFoundError"
**Interpretation**: Missing Python dependencies or incorrect import paths
**Resolution**: Run setup script, verify Python path configuration, check virtual environment activation

### Connection Error Messages
**Common Patterns**: "Connection refused", "Connection timed out", "No route to host"
**Interpretation**: Network connectivity or service availability issues
**Resolution**: Check service status, verify port accessibility, inspect firewall configuration

### Authentication Error Messages
**Common Patterns**: "Authentication rejected", "Invalid subscriber", "MAC verification failed"
**Interpretation**: Subscriber data mismatch or authentication parameter errors
**Resolution**: Verify KI/OPC values, check PLMN configuration, validate AUTN freshness

### PDU Session Error Messages
**Common Patterns**: "DNN not configured", "UPF unreachable", "Slice configuration error"
**Interpretation**: Network slice or DNN configuration issues
**Resolution**: Verify subscription DNN settings, check UPF connectivity, validate slice parameters

### Test Timeout Error Messages
**Common Patterns**: "Test timed out", "Exceeded timeout", "Registration failed"
**Interpretation**: Network performance or resource constraint issues
**Resolution**: Increase timeout values, reduce concurrency, optimize system resources

### Subscription Error Messages
**Common Patterns**: "Subscription already exists", "IMSI conflict", "Duplicate entry"
**Interpretation**: Existing subscriber profiles or configuration conflicts
**Resolution**: Delete existing subscriptions, change IMSI ranges, clean database entries

### SCTP Error Messages
**Common Patterns**: "SCTP association failed", "Protocol not available", "No such device"
**Interpretation**: SCTP support or configuration issues
**Resolution**: Install SCTP libraries, verify AMF configuration, check system support

## Debugging Steps for Different Failure Scenarios

### Import Error Debugging
1. **Run import verification**: Execute `python3 test_imports.py` to identify failing imports
2. **Execute setup process**: Run `bash setup.sh` to install dependencies and configure paths
3. **Manual path configuration**: Add workspace paths if automatic configuration fails
4. **Verify import success**: Re-run import test to confirm resolution
5. **Check Python compatibility**: Ensure Python 3.8+ is installed and active

### Connection Problem Debugging
1. **Service status verification**: Check AMF container/service status and health
2. **Port accessibility testing**: Use telnet or netcat to test port 38412 connectivity
3. **Firewall inspection**: Review firewall rules for port 38412 blocking
4. **Network connectivity validation**: Verify reachability between components
5. **AMF configuration review**: Check AMF logs for startup and configuration errors

### Authentication Failure Debugging
1. **Subscription verification**: Confirm subscriber exists in core network database
2. **Parameter validation**: Check KI and OPC values match subscription exactly
3. **PLMN consistency**: Ensure PLMN configuration matches authentication parameters
4. **AUTN freshness check**: Validate AUTN sequence number and freshness
5. **AMF log analysis**: Review detailed authentication error messages

### Timeout Error Debugging
1. **Timeout adjustment**: Increase timeout values in test configuration
2. **Concurrency reduction**: Lower concurrent UE count for large-scale tests
3. **Performance monitoring**: Monitor AMF resource utilization during execution
4. **Initialization staggering**: Implement staggered UE initialization
5. **Network optimization**: Check and optimize network parameters

### Duplicate Subscription Debugging
1. **Database cleanup**: Delete existing subscriptions using provision mode
2. **IMSI range modification**: Change starting IMSI index in configuration
3. **Parameter specification**: Use start-imsi command line parameter
4. **Uniqueness verification**: Check IMSI uniqueness in core network
5. **Conflict prevention**: Implement proper cleanup procedures

### SCTP Association Debugging
1. **Support verification**: Check SCTP kernel module availability
2. **Library installation**: Install required SCTP libraries if missing
3. **AMF configuration**: Verify AMF supports and is configured for SCTP
4. **Connectivity testing**: Test SCTP connectivity between components
5. **Infrastructure validation**: Ensure network infrastructure supports SCTP

## Performance Bottleneck Identification

### System Resource Monitoring
- **CPU Utilization**: Monitor CPU usage during multi-UE testing to identify processing bottlenecks
- **Memory Consumption**: Track memory usage patterns to detect leaks or excessive consumption
- **Network Throughput**: Measure network bandwidth utilization during concurrent connections
- **File Descriptor Limits**: Monitor file handle usage to prevent "too many open files" errors

### Concurrency and Scalability Analysis
- **Thread Pool Sizing**: Optimize thread pool configuration for balanced throughput and stability
- **Connection Pool Management**: Implement efficient connection pooling for high concurrency
- **Resource Allocation**: Balance CPU, memory, and network resources for optimal performance
- **Load Distribution**: Distribute workload evenly across available system resources

### Network Performance Optimization
- **Buffer Sizing**: Adjust SCTP and TCP buffer sizes for high-throughput scenarios
- **Connection Reuse**: Implement connection reuse strategies to reduce overhead
- **Protocol Optimization**: Optimize protocol parameters for test scenarios
- **Bandwidth Management**: Ensure adequate network bandwidth for concurrent testing

### Logging and Monitoring Impact
- **Logging Overhead**: Reduce logging verbosity for large-scale tests to minimize performance impact
- **Log Aggregation**: Implement efficient log aggregation for distributed testing environments
- **Performance Metrics**: Collect and analyze performance metrics during test execution
- **Resource Profiling**: Profile application resource usage to identify optimization opportunities

## Resource Constraint Troubleshooting

### File Descriptor Management
**Issue**: "Too many open files" or file descriptor limit exceeded errors
**Solution**: 
1. Increase system file descriptor limits: `ulimit -n 65536`
2. Implement proper resource cleanup and disposal
3. Optimize file handle management in test execution
4. Monitor file descriptor usage during long-running tests

### Memory Optimization
**Issue**: Memory exhaustion during large-scale testing
**Solution**:
1. Implement memory-efficient data structures and algorithms
2. Use streaming processing for large datasets
3. Implement proper garbage collection and resource cleanup
4. Monitor memory usage patterns and optimize allocation strategies

### CPU Resource Management
**Issue**: High CPU utilization causing test instability
**Solution**:
1. Optimize algorithm efficiency and reduce computational complexity
2. Implement parallel processing with appropriate thread pool sizing
3. Use asynchronous processing for I/O-bound operations
4. Monitor CPU usage and identify hotspots for optimization

### Network Resource Optimization
**Issue**: Network bandwidth limitations affecting test performance
**Solution**:
1. Optimize network packet sizes and transmission rates
2. Implement connection pooling and reuse strategies
3. Use efficient serialization formats for data exchange
4. Monitor network utilization and optimize transmission patterns

## Escalation Procedures for Complex Issues

### Comprehensive Issue Documentation
1. **Problem Description**: Clear and concise problem statement with impact assessment
2. **Reproduction Steps**: Detailed steps to reproduce the issue consistently
3. **Environment Details**: Complete system configuration and dependency versions
4. **Error Messages**: Complete error logs and stack traces
5. **Test Configuration**: All relevant configuration parameters and test settings

### Multi-Component Analysis
1. **Component Isolation**: Identify which system components are affected
2. **Dependency Mapping**: Document relationships between affected components
3. **Impact Assessment**: Evaluate business impact and critical path dependencies
4. **Workaround Documentation**: Document temporary solutions for continued operations

### Evidence Collection and Analysis
1. **Log Aggregation**: Collect logs from all affected components and systems
2. **Traffic Capture**: Capture network traffic for protocol-level analysis
3. **Performance Metrics**: Gather system performance and resource utilization data
4. **Configuration Comparison**: Compare current configuration with known working setups

### Expert Consultation and Support
1. **Internal Review**: Conduct internal technical review with subject matter experts
2. **External Support**: Engage vendor support channels when applicable
3. **Community Engagement**: Seek assistance from relevant community forums and support groups
4. **Documentation Enhancement**: Update troubleshooting guides and knowledge bases

### Resolution Validation and Follow-up
1. **Fix Verification**: Thoroughly test implemented solutions in controlled environment
2. **Regression Testing**: Ensure fixes don't introduce new issues
3. **Performance Validation**: Verify solution doesn't negatively impact system performance
4. **Knowledge Transfer**: Document lessons learned and update operational procedures

**Section sources**
- [README.md:281-287](file://README.md#L281-L287)