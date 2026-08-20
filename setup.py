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

# Dependencies that are always required and commonly pre-installed.
# Version pins are intentionally loose so `pip install` works on
# air-gapped machines against the system site-packages.
_CORE_REQUIRES = [
    "requests",
    "pycryptodome",
    "loguru",
    "tqdm",
]

# Heavy / niche protocol dependencies. They are documented in
# requirements.txt and the README, but kept out of the mandatory
# install_requires so provisioning works without network access:
#   - pycrate: ASN.1 codec, often vendored on sys.path
#   - pysctp:  SCTP transport, needs libsctp-dev to build
#   - pytest:  only needed for running the test suite
# Install them with: python3 -m pip install coresimrunner[protocol]


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
    # Ship subscription templates and the default .env so the CLI
    # works from any working directory after installation
    package_data={
        "coresimrunner": [
            "config/*.json",
            ".env",
        ],
    },
    include_package_data=True,
    install_requires=_CORE_REQUIRES,
    extras_require={
        "protocol": ["pycrate", "pysctp"],
        "test": ["pytest"],
    },
    entry_points={
        "console_scripts": [
            "coresim=coresimrunner.coresim_runner:main",
            "coresim-runner=coresimrunner.coresim_runner:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Topic :: System :: Networking",
        "Topic :: Software Development :: Testing",
    ],
)
