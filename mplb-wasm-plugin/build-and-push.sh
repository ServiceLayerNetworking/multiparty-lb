#!/bin/bash

set -e
# set -x

# Define the list of load balancing strategies
LB_VALUES=("minimize_diff" "locality_aware_weighted_random" "leastrequest" "weighted_random" "weighted_roundrobin" "weighted_leastrequest")

# Path to TinyGo binary (adjust if necessary)
TINYGO_BIN="/usr/local/bin/tinygo"

# Loop through each LB strategy
for LB in "${LB_VALUES[@]}"; do
    echo "Building for Load Balancing Strategy: $LB"

    sed -i 's/\(\s*LOAD_BALANCING_STRATEGY = \).*/\1'"\"$LB\""'/' main.go

    # Compile with TinyGo
    GOARCH=wasm GOOS=js $TINYGO_BIN build -o wasm-out/slate_plugin.wasm -gc=custom -tags="custommalloc nottinygc_envoy" \
        -scheduler=none -target=wasi .

    # Docker build
    docker build -t ghcr.io/talha-waheed/mplb-plugin:$LB .

    # Docker push
    docker push ghcr.io/talha-waheed/mplb-plugin:$LB

    echo "Completed for $LB"
done

echo "All builds and pushes completed!"
