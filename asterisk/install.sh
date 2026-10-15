#!/usr/bin/env bash
set -euo pipefail

ASTERISK_VERSION="22.10.1"
BUILD_DIR="$HOME/asterisk-build"

echo "Installing Asterisk ${ASTERISK_VERSION}..."

sudo apt-get update

sudo apt-get install -y \
    build-essential \
    curl \
    ca-certificates \
    pkg-config \
    libssl-dev \
    libedit-dev \
    libjansson-dev \
    libsqlite3-dev \
    libxml2-dev \
    uuid-dev \
    libcurl4-openssl-dev \
    libncurses-dev \
    libnewt-dev \
    bison \
    flex

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

curl -fL --retry 3 \
    "https://downloads.asterisk.org/pub/telephony/asterisk/old-releases/asterisk-${ASTERISK_VERSION}.tar.gz" \
    -o "asterisk-${ASTERISK_VERSION}.tar.gz"

tar -xzf "asterisk-${ASTERISK_VERSION}.tar.gz"

cd "asterisk-${ASTERISK_VERSION}"

./configure \
    --with-pjproject-bundled \
    --with-jansson-bundled

echo "Review required modules in menuselect:"
echo "chan_websocket"
echo "res_websocket_client"
echo "res_http_websocket"
echo "res_pjsip_transport_websocket"
echo "res_pjsip"

make menuselect

make -j2

sudo make install

echo "Asterisk installation finished."
asterisk -V

echo "Next: configure Asterisk for MedMind."
