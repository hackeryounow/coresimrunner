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
python3 -m pip install git+https://github.com/hackeryounow/coresimrunner.git@v1.4.0
```

> Use `@<branch>` to pick any branch; the default branch works without it.

### From source

```bash
git clone git@github.com:hackeryounow/coresimrunner.git
cd coresimrunner
python3 -m pip install .
```

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
> `cd /tmp && git clone https://github.com/mitshell/CryptoMobile.git && cd CryptoMobile && python3 -m pip install .`

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
the command line (CLI always wins) — run `coresim --help` for the mapping.

Use a different `.env` per run:

```bash
coresim --env-file /path/to/my.env --mode ue-test --core-network open5gs
```

## Usage

After installation the `coresim` command runs from any directory
(no `python3` prefix needed).

```bash
# Provision 5 subscriptions (Open5GS WebUI + pyHSS when ENABLE_IMS=true)
coresim --mode provision --count 5 --core-network open5gs

# Delete 5 subscriptions
coresim --mode provision --count 5 --core-network open5gs --delete

# Delete EVERYTHING: pyHSS (ims_subscriber -> subscriber -> auc -> apn),
# then all Open5GS WebUI subscribers — ignores --count
coresim --mode provision --delete-all --core-network open5gs

# 5G: register multiple UEs + establish PDU sessions
coresim --mode ue-test --count 10 --core-network open5gs

# 4G: attach multiple UEs + establish EPS bearers
coresim --mode 4g-test --count 10 --core-network open5gs

# Sequential 2-round registration with GTP-U encapsulation
coresim --mode seq-reg --imsi 0000000001 0000000002 --core-network open5gs

# VoNR: 5G registration + IMS PDU + SIP REGISTER + INVITE call
coresim --mode vonr --imsi 0000000001 --core-network open5gs
```

Override anything on the command line:

```bash
coresim --mode provision --count 5 --core-network open5gs \
        --core-address 192.168.100.11 --webui-port 9999 \
        --username admin --password 1423 --no-ims
```

Full option list and descriptions: `coresim --help`.
