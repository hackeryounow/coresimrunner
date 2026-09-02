"""
Setup script for CoreSimRunner.

The repository root IS the package itself (`coresimrunner`), so the
package directory is mapped onto "." and subpackages are listed
explicitly.

Install:
    python3 -m pip install .

After installation the CLI is available without the python3 prefix:
    coresim --help
    coresim --mode provision --count 5 --core-network open5gs

Note: editable installs (`pip install -e .`) are NOT supported because
the repository root is the package itself; for development, run
`python3 coresim_runner.py ...` directly from the source tree.
"""

import os
from setuptools import setup

HERE = os.path.abspath(os.path.dirname(__file__))

# All runtime dependencies so a plain `pip install` yields a fully
# working CLI (provision, UE tests, VoNR). Version pins are loose so
# installs also work against pre-installed system packages.
#
#   - requests/pycryptodome/loguru/tqdm: core libraries
#   - pycrate:  ASN.1 codec for NGAP/S1AP/NAS
#   - pysctp:   SCTP transport (build needs libsctp-dev when no
#               matching wheel exists: sudo apt-get install libsctp-dev)
#   - CryptoMobile: 3GPP Milenage algorithms; NOT on PyPI, fetched
#               straight from GitHub
_REQUIRES = [
    "requests",
    "pycryptodome",
    "loguru",
    "tqdm",
    "pycrate",
    "pysctp",
    "CryptoMobile @ git+https://github.com/mitshell/CryptoMobile.git",
]


def read_long_description():
    readme = os.path.join(HERE, "README.md")
    if os.path.exists(readme):
        with open(readme, "r", encoding="utf-8") as f:
            return f.read()
    return ""


setup(
    name="coresimrunner",
    version="1.0.0",
    description=(
        "5G/4G Core Network Subscription Provisioning and Multi-UE Testing "
        "(Free5GC / Open5GS + pyHSS IMS)"
    ),
    long_description=read_long_description(),
    long_description_content_type="text/markdown",
    python_requires=">=3.8",
    # The repository root is the `coresimrunner` package itself
    package_dir={"coresimrunner": "."},
    packages=[
        "coresimrunner",
        "coresimrunner.core_network",
        "coresimrunner.integration",
        "coresimrunner.ims",
    ],
    # Ship subscription templates, the config template (.env.example,
    # always committed) and the local .env (when present, e.g. local
    # installs). Note: .env is gitignored, so installs from GitHub only
    # contain .env.example — copy it to .env and edit for your setup.
    package_data={
        "coresimrunner": [
            "config/*.json",
            ".env",
            ".env.example",
            # setuptools skips dotfiles when globbing package_data —
            # this non-dot pattern is what actually ships .env.example
            "*.example",
        ],
    },
    include_package_data=True,
    install_requires=_REQUIRES,
    extras_require={
        "test": ["pytest"],
    },
    entry_points={
        "console_scripts": [
            "coresimrunner=coresimrunner.coresim_runner:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Topic :: System :: Networking",
        "Topic :: Software Development :: Testing",
    ],
)
