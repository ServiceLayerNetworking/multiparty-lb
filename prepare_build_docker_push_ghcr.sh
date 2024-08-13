#!/bin/bash

set -e
set -x

# sudo groupadd docker
# sudo usermod -aG docker $USER
# newgrp docker
CR_PAT=$1
echo $CR_PAT | docker login ghcr.io -u talha-waheed --password-stdin