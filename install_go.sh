#!/bin/bash

set -e
set -x

wget https://golang.org/dl/go1.23.0.linux-amd64.tar.gz
sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.23.0.linux-amd64.tar.gz
rm go1.23.0.linux-amd64.tar.gz
export PATH=$PATH:/usr/local/go/bin
go version