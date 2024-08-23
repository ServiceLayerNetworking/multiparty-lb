#!/bin/bash

set -e
set -x

wget https://github.com/tinygo-org/tinygo/releases/download/v0.32.0/tinygo_0.32.0_amd64.deb
sudo dpkg -i tinygo_0.32.0_amd64.deb

echo "export PATH=$PATH:/usr/local/bin" >> ~/.bashrc && source ~/.bashrc