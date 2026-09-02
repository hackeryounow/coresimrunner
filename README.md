# CoreSimRunner

Automated 5G/4G core network testing tool: subscription provisioning,
multi-UE registration, session establishment and VoNR IMS calls —
against **Open5GS** and **Free5GC**.

## Features

- **Subscription management**: concurrent provision / delete / delete-all
  (Open5GS WebUI + pyHSS, strict order: ims_subscriber → subscriber → auc → apn)
- **5G**: multi-UE registration + PDU session establishment (NGAP/NAS over SCTP)
- **4G**: multi-UE attach + EPS bearer establishment (S1AP/NAS over SCTP)
- **Sequential registration** with GTP-U encapsulated NAS
- **VoNR**: IMS SIP REGISTER and INVITE call through the UPF GTP-U tunnel
- **Simple configuration**: one `.env` file, every key overridable via CLI

## Installation

Requires **Python 3.8+** and `git`.

One prerequisite system library (needed to build `pysctp` when no
matching wheel exists):

```bash
sudo apt-get install libsctp-dev
```

### From GitHub (recommended)

```bash
pip3 install git+https://github.com/hackeryounow/coresimrunner.git@v1.4.0
```

> Use `@<branch>` to pick any branch; the default branch works without it.

### From source

```bash
git clone git@github.com:hackeryounow/coresimrunner.git
cd coresimrunner
pip3 install .
```

> If your `pip` points to Python 3 (`pip --version` shows python 3.x),
> plain `pip install` works just as well — `pip3` / `python3 -m pip`
> only guarantees the right interpreter on multi-Python systems.

A plain install pulls in **all** runtime dependencies (including
`pycrate`, `pysctp` and `CryptoMobile`, the latter fetched straight
from GitHub since it is not on PyPI) — the CLI is fully usable right
after installation, no extras needed.

> `pip install -e .` (editable) is **not** supported — the repo root is
> the package itself. Run `python3 coresim_runner.py ...` from the source
> tree for development instead.
>
> If pip cannot reach GitHub for CryptoMobile, install it manually in a
> temporary directory first (do NOT clone it into this project):
> `cd /tmp && git clone https://github.com/mitshell/CryptoMobile.git && cd CryptoMobile && pip3 install .`

## Configuration

All settings live in one `.env` file. After installing from GitHub create
one from the bundled template:

```bash
cp $(python3 -c "import coresimrunner, os; print(os.path.dirname(coresimrunner.__file__))")/.env.example .env
```

Edit the keys for your environment:

| Key | Description |
|----|----|
| `CORE_ADDRESS` | Core network IP (WebUI API + AMF/MME SCTP) |
| `WEBUI_PORT` | WebUI API port (Open5GS default 9999) |
| `PLMN` | MCC+MNC combined, e.g. `46009` |
| `PERMANENT_KEY` / `OPC_VALUE` | Subscriber authentication keys |
| `USERNAME` / `PASSWORD` | WebUI login credentials |
| `GNB_ADDRESS` / `ENB_ADDRESS` | gNodeB / eNodeB IP |
| `DNN` / `APN` | Data network name (5G / 4G) |
| `ENABLE_IMS` | `true` = also provision IMS subscribers to pyHSS |
| `UPF_IP` / `PCSCF_IP` / `PCSCF_PORT` | VoNR IMS settings |

See `.env.example` for the complete list. Every key can also be set on
the command line (CLI always wins) — run `coresimrunner --help` for the mapping.

Use a different `.env` per run:

```bash
coresimrunner --env-file /path/to/my.env --mode ue-test --core-network open5gs
```

## Usage

After installation the `coresimrunner` command runs from any directory
(no `python3` prefix needed).

```bash
# Provision 5 subscriptions (Open5GS WebUI + pyHSS when ENABLE_IMS=true)
coresimrunner --mode provision --count 5 --core-network open5gs

# Delete 5 subscriptions
coresimrunner --mode provision --count 5 --core-network open5gs --delete

# Delete EVERYTHING: pyHSS (ims_subscriber -> subscriber -> auc -> apn),
# then all Open5GS WebUI subscribers — ignores --count
coresimrunner --mode provision --delete-all --core-network open5gs

# 5G: register multiple UEs + establish PDU sessions
coresimrunner --mode ue-test --count 10 --core-network open5gs

# 4G: attach multiple UEs + establish EPS bearers
coresimrunner --mode 4g-test --count 10 --core-network open5gs

# Sequential 2-round registration with GTP-U encapsulation
coresimrunner --mode seq-reg --imsi 0000000001 0000000002 --core-network open5gs

# VoNR: 5G registration + IMS PDU + SIP REGISTER + INVITE call
coresimrunner --mode vonr --imsi 0000000001 --core-network open5gs
```

Override anything on the command line:

```bash
coresimrunner --mode provision --count 5 --core-network open5gs \
        --core-address 192.168.100.11 --webui-port 9999 \
        --username admin --password 1423 --no-ims
```

Full option list and descriptions: `coresimrunner --help`.

## Project Layout

The repository root **is** the `coresimrunner` package — only files
required for installation (plus `.env` / `.env.example`) live at the
top level. Everything else is grouped under `extras/`:

```
core_network/  integration/  ims/  config/    # package code + templates
coresim_runner.py  config_loader.py  ...      # package modules
setup.py  requirements.txt  README.md         # installation files
.env  .env.example                            # configuration
extras/
├── tests/                  # unit tests
├── scripts/                # helper scripts
├── pcaps/                  # sample packet captures
├── ueransim_config/        # UERANSIM gNB/UE reference configs
└── cscf_vulnerabilities/   # CSCF security research PoCs
```
