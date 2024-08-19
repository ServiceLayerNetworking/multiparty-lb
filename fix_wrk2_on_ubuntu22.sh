#!/bin/bash

set -e
set -x

wget http://nz2.archive.ubuntu.com/ubuntu/pool/main/o/openssl/libssl1.1_1.1.1f-1ubuntu2.23_amd64.deb

sudo dpkg -i libssl1.1_1.1.1f-1ubuntu2.23_amd64.deb

rm libssl1.1_1.1.1f-1ubuntu2.23_amd64.deb


sudo apt-get install libssl-dev

sudo apt install luarocks
sudo luarocks --lua-version 5.1 install luasocket