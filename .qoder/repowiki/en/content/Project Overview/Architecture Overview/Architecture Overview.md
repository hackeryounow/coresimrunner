# Architecture Overview

<cite>
**Referenced Files in This Document**
- [README.md](file://README.md)
- [coresim_runner.py](file://src/coresim_runner.py)
- [config_loader.py](file://src/config_loader.py)
- [core_network/core_network.py](file://src/core_network/core_network.py)
- [core_network/core_network_factory.py](file://src/core_network/core_network_factory.py)
- [core_network/free5gc_impl.py](file://src/core_network/free5gc_impl.py)
- [core_network/open5gs_impl.py](file://src/core_network/open5gs_impl.py)
- [integration/integrated_gnb.py](file://src/integration/integrated_gnb.py)
- [integration/integrated_messages.py](file://src/integration/integrated_messages.py)
- [integration/integrated_ue.py](file://src/integration/integrated_ue.py)
- [ue_test_runner.py](file://src/ue_test_runner.py)
- [tests/test_imports.py](file://src/tests/test_imports.py)
- [tests/test_ue_functionality.py](file://src/tests/test_ue_functionality.py)
- [config/free5gc_subscription_template.json](file://config/free5gc_subscription_template.json)
- [config/open5gs_subscription_template.json](file://config/open5gs_subscription_template.json)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)

## Introduction
This document presents the architecture of CoreSimRunner, a multi-UE 5G/4G core network testing framework. The system is designed around a clear separation between:
- Core network abstraction layer: responsible for provisioning/deleting subscriptions in different core networks (Free5GC/Open5GS).
- 5G protocol integration layer: responsible for simulating gNodeB and UE behavior, performing registration, authentication, security mode command, and PDU session establishment procedures.

It also documents the factory pattern for dynamic core network instantiation, the strategy-like pluggable backend design, and the observer-style progress monitoring used in multi-UE testing. The module structure, design principles (separation of concerns, thread safety, automatic path resolution, comprehensive error handling), and integration patterns with external dependencies are explained with diagrams and references to the source code.

## Project Structure
CoreSimRunner is organized into three primary modules plus configuration and tests:
- core_network/: Abstraction and implementations for Free5GC and Open5GS subscription provisioning.
- integration/: 5G protocol integration including gNodeB simulator, UE state machine, and NGAP/NAS message handling.
- tests/: Unit and integration tests validating imports and basic functionality.
- Root-level entry points and configuration loader.

```mermaid
graph TB
subgraph "CoreSimRunner"
A["src/coresim_runner.py"]
B["src/config_loader.py"]
subgraph "core_network/"
C["core_network.py"]
D["core_network_factory.py"]
E["free5gc_impl.py"]
F["open5gs_impl.py"]
end
subgraph "integration/"
G["integrated_gnb.py"]
H["integrated_messages.py"]
I["integrated_ue.py"]
end
J["src/ue_test_runner.py"]
K["src/tests/*"]
L["config/*.json"]
end
A --> B
A --> D
D --> C
D --> E
D --> F
A --> J
J --> G
G --> H
G --> I
B --> L
```

**Diagram sources**
- [coresim_runner.py:1-485](file://src/coresim_runner.py#L1-L485)
- [config_loader.py:1-150](file://src/config_loader.py#L1-L150)
- [core_network/core_network.py:1-56](file://src/core_network/core_network.py#L1-L56)
- [core_network/core_network_factory.py:1-34](file://src/core_network/core_network_factory.py#L1-L34)
- [core_network/free5gc_impl.py:1-203](file://src/core_network/free5gc_impl.py#L1-L203)
- [core_network/open5gs_impl.py:1-197](file://src/core_network/open5gs_impl.py#L1-L197)
- [integration/integrated_gnb.py:1-416](file://src/integration/integrated_gnb.py#L1-L416)
- [integration/integrated_messages.py:1-559](file://src/integration/integrated_messages.py#L1-L559)
- [integration/integrated_ue.py:1-454](file://src/integration/integrated_ue.py#L1-L454)
- [ue_test_runner.py:1-260](file://src/ue_test_runner.py#L1-L260)
- [tests/test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)
- [tests/test_ue_functionality.py:1-109](file://src/tests/test_ue_functionality.py#L1-L109)
- [config/free5gc_subscription_template.json:1-222](file://config/free5gc_subscription_template.json#L1-L222)
- [config/open5gs_subscription_template.json:1-109](file://config/open5gs_subscription_template.json#L1-L109)

**Section sources**
- [README.md:236-281](file://README.md#L236-L281)
- [coresim_runner.py:1-485](file://src/coresim_runner.py#L1-L485)

## Core Components
- CoresimRunner entry point: orchestrates modes (provision, 5G UE test, 4G test), loads configuration, and delegates to core network and integration layers.
- Core network abstraction: unified interface for subscription provisioning/deletion; factory resolves the concrete implementation.
- Integration layer: gNodeB simulator, UE state machine, and NGAP/NAS message builders/parsers.
- Test runner: multi-UE orchestration with progress monitoring and thread-safe counters.

Key responsibilities:
- CoresimRunner: argument parsing, configuration loading, mode dispatch, and high-level orchestration.
- CoreNetwork: define contract for subscription lifecycle; implementations encapsulate API specifics.
- IntegratedGNB: SCTP connection to AMF, message queues, worker threads, and per-UE message handling.
- IntegratedUE: state machine for registration and PDU session establishment; constructs NAS/NGAP messages.
- UETestRunner: instantiates gNodeB, monitors progress, aggregates results.

**Section sources**
- [coresim_runner.py:27-485](file://src/coresim_runner.py#L27-L485)
- [core_network/core_network.py:12-56](file://src/core_network/core_network.py#L12-L56)
- [core_network/core_network_factory.py:15-34](file://src/core_network/core_network_factory.py#L15-L34)
- [integration/integrated_gnb.py:47-416](file://src/integration/integrated_gnb.py#L47-L416)
- [integration/integrated_ue.py:40-454](file://src/integration/integrated_ue.py#L40-L454)
- [ue_test_runner.py:35-260](file://src/ue_test_runner.py#L35-L260)

## Architecture Overview
The system follows a layered architecture:
- Presentation/Orchestration Layer: CoresimRunner parses CLI and coordinates flows.
- Configuration Layer: ConfigLoader centralizes environment and JSON templates.
- Core Network Abstraction Layer: CoreNetwork interface with Free5GC/Open5GS implementations.
- Integration Layer: gNodeB simulator, UE state machine, and protocol message handling.
- External Dependencies: HTTP APIs for core networks, pycrate/CryptoMobile for ASN.1 and cryptography, loguru for logging, requests for HTTP.

```mermaid
graph TB
subgraph "Presentation/Orchestration"
CR["coresim_runner.py"]
UTR["ue_test_runner.py"]
end
subgraph "Configuration"
CL["config_loader.py"]
F5GC_T["free5gc_subscription_template.json"]
O5GS_T["open5gs_subscription_template.json"]
end
subgraph "Core Network Abstraction"
CN_IF["core_network/core_network.py"]
CNF["core_network/core_network_factory.py"]
F5GC["core_network/free5gc_impl.py"]
O5GS["core_network/open5gs_impl.py"]
end
subgraph "Integration Layer"
GNB["integration/integrated_gnb.py"]
UE["integration/integrated_ue.py"]
MSG["integration/integrated_messages.py"]
end
CR --> CL
CR --> CNF
CNF --> CN_IF
CNF --> F5GC
CNF --> O5GS
CR --> UTR
UTR --> GNB
GNB --> MSG
GNB --> UE
CL --> F5GC_T
CL --> O5GS_T
```

**Diagram sources**
- [coresim_runner.py:1-485](file://src/coresim_runner.py#L1-L485)
- [config_loader.py:1-150](file://src/config_loader.py#L1-L150)
- [core_network/core_network.py:1-56](file://src/core_network/core_network.py#L1-L56)
- [core_network/core_network_factory.py:1-34](file://src/core_network/core_network_factory.py#L1-L34)
- [core_network/free5gc_impl.py:1-203](file://src/core_network/free5gc_impl.py#L1-L203)
- [core_network/open5gs_impl.py:1-197](file://src/core_network/open5gs_impl.py#L1-L197)
- [integration/integrated_gnb.py:1-416](file://src/integration/integrated_gnb.py#L1-L416)
- [integration/integrated_messages.py:1-559](file://src/integration/integrated_messages.py#L1-L559)
- [integration/integrated_ue.py:1-454](file://src/integration/integrated_ue.py#L1-L454)
- [config/free5gc_subscription_template.json:1-222](file://config/free5gc_subscription_template.json#L1-L222)
- [config/open5gs_subscription_template.json:1-109](file://config/open5gs_subscription_template.json#L1-L109)

## Detailed Component Analysis

### Core Network Abstraction and Factory Pattern
- CoreNetwork defines the abstract interface for subscription provisioning and deletion.
- CoreNetworkFactory resolves the concrete implementation based on configuration, enabling pluggable backends.
- Free5GC and Open5GS implementations encapsulate HTTP API specifics and authentication flows.

```mermaid
classDiagram
class CoreNetwork {
+string name
+provision_subscriptions(count) bool
+delete_subscriptions(count) bool
-_get_initial_imsi_index() int
}
class Free5GC {
+provision_subscriptions(count) bool
+delete_subscriptions(count) bool
-_login() bool
-_delete_subscription(imsi) bool
}
class Open5GS {
+provision_subscriptions(count) bool
+delete_subscriptions(count) bool
-_authenticate() Session
}
class CoreNetworkFactory {
+create_core_network(type, config) CoreNetwork
}
CoreNetwork <|-- Free5GC
CoreNetwork <|-- Open5GS
CoreNetworkFactory --> CoreNetwork : "creates"
```

**Diagram sources**
- [core_network/core_network.py:12-56](file://src/core_network/core_network.py#L12-L56)
- [core_network/free5gc_impl.py:15-203](file://src/core_network/free5gc_impl.py#L15-L203)
- [core_network/open5gs_impl.py:15-197](file://src/core_network/open5gs_impl.py#L15-L197)
- [core_network/core_network_factory.py:15-34](file://src/core_network/core_network_factory.py#L15-L34)

**Section sources**
- [core_network/core_network.py:12-56](file://src/core_network/core_network.py#L12-L56)
- [core_network/core_network_factory.py:15-34](file://src/core_network/core_network_factory.py#L15-L34)
- [core_network/free5gc_impl.py:15-203](file://src/core_network/free5gc_impl.py#L15-L203)
- [core_network/open5gs_impl.py:15-197](file://src/core_network/open5gs_impl.py#L15-L197)

### 5G Protocol Integration Layer
- IntegratedGNB: manages SCTP connection to AMF, message queues, worker threads, and per-UE handlers.
- IntegratedUE: maintains UE state, processes NGAP/NAS messages, and generates responses.
- integrated_messages: enums, helpers, and constructors for NGAP and NAS messages.

```mermaid
classDiagram
class IntegratedGNB {
+run()
+send_message(msg)
-_setup_gnb()
-_acceptor()
-_sender()
-_ngap_message_handler(data, idx)
-_extract_ran_ue_ngap_id(hex)
+close()
}
class IntegratedUE {
+handle_message(type_t, pdu_dict) (UE, msgs)
+send_initial_ue_message()
+send_service_request()
+release_ue_context()
+send_pdusession_establishment_request(dnn)
+get_session_info()
}
class IntegratedMessages {
<<enumerations>>
+ProcedureCode
+MessageType
+plmn_bcd_encode()
+plmn_bcd_decode()
+calculateRes()
+NGAPSetupReqeust(...)
+InitialUEMessage(...)
+AuthRequestMessage(...)
+SecurityModeCommandMessage(...)
+SecurityModeCompleteMessage(...)
+InitialContextSetupRequestMessage(...)
+InitialContextSetupResponseMessage(...)
+RegistrationCompleteMessage(...)
+PDUSessionEstablishmentRequestMessage(...)
+PDUSessionResourceSetupRequestMessage(...)
+PDUSessResourceSetupResponseMessage(...)
+UEContextReleaseRequestMessage(...)
+UEContextReleaseCommandMessage(...)
+UEContextReleaseCompleteMessage(...)
}
IntegratedGNB --> IntegratedUE : "manages"
IntegratedGNB --> IntegratedMessages : "uses"
IntegratedUE --> IntegratedMessages : "uses"
```

**Diagram sources**
- [integration/integrated_gnb.py:47-416](file://src/integration/integrated_gnb.py#L47-L416)
- [integration/integrated_ue.py:40-454](file://src/integration/integrated_ue.py#L40-L454)
- [integration/integrated_messages.py:33-559](file://src/integration/integrated_messages.py#L33-L559)

**Section sources**
- [integration/integrated_gnb.py:47-416](file://src/integration/integrated_gnb.py#L47-L416)
- [integration/integrated_ue.py:40-454](file://src/integration/integrated_ue.py#L40-L454)
- [integration/integrated_messages.py:33-559](file://src/integration/integrated_messages.py#L33-L559)

### Multi-UE Test Orchestration and Progress Monitoring
- UETestRunner initializes IntegratedGNB with configured parameters, runs tests, and monitors progress using thread-safe counters.
- CoresimRunner provides a CLI-driven flow for 5G/4G tests and subscription provisioning, delegating to UETestRunner or core network factory.

```mermaid
sequenceDiagram
participant CLI as "CoresimRunner"
participant CFG as "ConfigLoader"
participant FACT as "CoreNetworkFactory"
participant CN as "CoreNetwork Impl"
participant UER as "UETestRunner"
participant GNB as "IntegratedGNB"
participant UE as "IntegratedUE"
CLI->>CFG : load configuration
alt Provision Mode
CLI->>FACT : create_core_network(type, CFG)
FACT-->>CLI : CoreNetwork instance
CLI->>CN : provision_subscriptions(count)
CN-->>CLI : success/failure
else 5G UE Test Mode
CLI->>UER : initialize with params
UER->>GNB : instantiate IntegratedGNB
GNB->>UE : create UEs and send Initial UE Msg
loop Monitor
UER->>GNB : query UE states
GNB-->>UER : per-UE status
UER->>UER : update counters (thread-safe)
end
UER-->>CLI : final results
end
```

**Diagram sources**
- [coresim_runner.py:27-485](file://src/coresim_runner.py#L27-L485)
- [config_loader.py:14-150](file://src/config_loader.py#L14-L150)
- [core_network/core_network_factory.py:15-34](file://src/core_network/core_network_factory.py#L15-L34)
- [core_network/core_network.py:26-48](file://src/core_network/core_network.py#L26-L48)
- [ue_test_runner.py:151-260](file://src/ue_test_runner.py#L151-L260)
- [integration/integrated_gnb.py:169-213](file://src/integration/integrated_gnb.py#L169-L213)

**Section sources**
- [coresim_runner.py:27-485](file://src/coresim_runner.py#L27-L485)
- [ue_test_runner.py:151-260](file://src/ue_test_runner.py#L151-L260)
- [integration/integrated_gnb.py:169-213](file://src/integration/integrated_gnb.py#L169-L213)

### Configuration and Template Resolution
- ConfigLoader reads .env, substitutes placeholders, and loads JSON templates for core network subscription provisioning.
- Templates are parameterized and injected with runtime values from .env.

```mermaid
flowchart TD
Start(["Load .env"]) --> Parse[".env parsed<br/>key=value pairs"]
Parse --> Placeholders["Replace ${VAR} placeholders"]
Placeholders --> SelectCN{"Core Network Type?"}
SelectCN --> |Free5GC| LoadF5GC["Load FREE5GC_SUBSCRIPTION_TEMPLATE"]
SelectCN --> |Open5GS| LoadO5GS["Load OPEN5GS_SUBSCRIPTION_TEMPLATE"]
LoadF5GC --> Merge["Merge with runtime values"]
LoadO5GS --> Merge
Merge --> ReturnCfg["Return network config"]
```

**Diagram sources**
- [config_loader.py:27-150](file://src/config_loader.py#L27-L150)
- [config/free5gc_subscription_template.json:1-222](file://config/free5gc_subscription_template.json#L1-L222)
- [config/open5gs_subscription_template.json:1-109](file://config/open5gs_subscription_template.json#L1-L109)

**Section sources**
- [config_loader.py:27-150](file://src/config_loader.py#L27-L150)
- [config/free5gc_subscription_template.json:1-222](file://config/free5gc_subscription_template.json#L1-L222)
- [config/open5gs_subscription_template.json:1-109](file://config/open5gs_subscription_template.json#L1-L109)

## Dependency Analysis
- CoresimRunner depends on ConfigLoader, CoreNetworkFactory, and UETestRunner.
- CoreNetworkFactory depends on CoreNetwork and concrete implementations.
- Integration components depend on pycrate (ASN.1), CryptoMobile (Milenage), and loguru/tqdm for logging and progress bars.
- Tests validate imports and basic functionality.

```mermaid
graph LR
CR["coresim_runner.py"] --> CL["config_loader.py"]
CR --> CNF["core_network_factory.py"]
CR --> UTR["ue_test_runner.py"]
CNF --> CN["core_network.py"]
CNF --> F5GC["free5gc_impl.py"]
CNF --> O5GS["open5gs_impl.py"]
UTR --> GNB["integrated_gnb.py"]
GNB --> UE["integrated_ue.py"]
GNB --> MSG["integrated_messages.py"]
TESTS["tests/*"] --> MSG
TESTS --> UE
TESTS --> GNB
TESTS --> UTR
```

**Diagram sources**
- [coresim_runner.py:1-485](file://src/coresim_runner.py#L1-L485)
- [config_loader.py:1-150](file://src/config_loader.py#L1-L150)
- [core_network/core_network_factory.py:1-34](file://src/core_network/core_network_factory.py#L1-L34)
- [core_network/core_network.py:1-56](file://src/core_network/core_network.py#L1-L56)
- [core_network/free5gc_impl.py:1-203](file://src/core_network/free5gc_impl.py#L1-L203)
- [core_network/open5gs_impl.py:1-197](file://src/core_network/open5gs_impl.py#L1-L197)
- [ue_test_runner.py:1-260](file://src/ue_test_runner.py#L1-L260)
- [integration/integrated_gnb.py:1-416](file://src/integration/integrated_gnb.py#L1-L416)
- [integration/integrated_messages.py:1-559](file://src/integration/integrated_messages.py#L1-L559)
- [integration/integrated_ue.py:1-454](file://src/integration/integrated_ue.py#L1-L454)
- [tests/test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)
- [tests/test_ue_functionality.py:1-109](file://src/tests/test_ue_functionality.py#L1-L109)

**Section sources**
- [tests/test_imports.py:1-115](file://src/tests/test_imports.py#L1-L115)
- [tests/test_ue_functionality.py:1-109](file://src/tests/test_ue_functionality.py#L1-L109)

## Performance Considerations
- Concurrency: IntegratedGNB uses threading and queues to handle multiple UEs and messages concurrently; thread locks protect shared state.
- Backpressure: Queues and delays between API requests reduce overload on core networks and AMF.
- Logging: Lower log levels improve throughput for large-scale tests.
- SCTP tuning: Ensure adequate buffer sizes for high concurrency.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and diagnostics:
- Import failures: verify setup script installation and PYTHONPATH additions for pycrate and CryptoMobile.
- AMF connectivity: confirm AMF IP/port accessibility and SCTP availability.
- Authentication failures: validate KI/OPC alignment with core network subscription data.
- Duplicate subscriptions: clean up existing entries before provisioning.
- Resource limits: increase file descriptors if encountering “too many open files.”

Operational checks:
- Run import verification script to validate dependencies.
- Use telnet or network tools to probe AMF connectivity.
- Inspect core network logs for detailed error messages.
- Capture NGAP traffic for protocol-level debugging.

**Section sources**
- [README.md:200-235](file://README.md#L200-L235)
- [tests/test_imports.py:23-115](file://src/tests/test_imports.py#L23-L115)

## Conclusion
CoreSimRunner’s architecture cleanly separates core network provisioning from 5G protocol integration, enabling extensibility and maintainability. The factory pattern facilitates pluggable core network backends, while the integration layer provides robust, thread-safe multi-UE testing. Automatic configuration resolution and comprehensive error handling contribute to operational reliability. The documented patterns and diagrams serve as a blueprint for extending support to additional core networks or integrating further protocol features.