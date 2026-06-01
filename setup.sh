#!/bin/bash

# Setup script for CoreSimRunner
echo "Setting up CoreSimRunner environment..."

# Create necessary directories
mkdir -p logs
mkdir -p config
mkdir -p current

# Install Python dependencies
pip install -r requirements.txt 2>/dev/null || echo "requirements.txt not found, installing basic dependencies..."
pip install loguru pycryptodome pysocks

# Check if pycrate is available
if python -c "import pycrate_asn1dir" &> /dev/null; then
    echo "✓ pycrate is available"
else
    echo "⚠ pycrate not found, please install it separately"
fi

# Check if CryptoMobile is available
if python -c "import CryptoMobile" &> /dev/null; then
    echo "✓ CryptoMobile is available"
else
    echo "⚠ CryptoMobile not found, please install it separately"
fi

# Create a basic .env file if it doesn't exist
if [ ! -f ".env" ]; then
    cat > .env << EOF
# CoreSimRunner Configuration
FREE5GC_WEBUI_URL=http://localhost:5000
FREE5GC_API_KEY=admin
OPEN5GS_WEBUI_URL=http://localhost:3000
OPEN5GS_API_KEY=admin
PLMN_ID=46692
AMF=8000
OP_VALUE=E8ED289DEBA952E4283B54E88E6183CA
OPC_VALUE=71a121bb69baf3c0cc53fb5038a0131f
PERMANENT_KEY=12341234123412341234123412340000
INITIAL_IMSI_INDEX=0000000001
MCC=460
MNC=99
GNB_ADDRESS=192.168.55.9
AMF_ADDRESS=192.168.55.53
ENB_ADDRESS=192.168.55.9
MME_ADDRESS=192.168.55.53
KI=12341234123412341234123412340000
OPC=71a121bb69baf3c0cc53fb5038a0131f
EOF
    echo "Created default .env file"
fi

echo "Setup complete!"
echo ""
echo "To run the tool:"
echo "  5G/4G provisioning: python coresim_runner.py --mode provision --count 1 --core-network free5gc"
echo "  5G testing: python coresim_runner.py --mode ue-test --count 1"
echo "  4G testing: python coresim_runner.py --mode 4g-test --count 1"