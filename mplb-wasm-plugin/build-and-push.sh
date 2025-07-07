#!/bin/bash

set -e
# set -x

# Define the list of load balancing strategies
# LB_VALUES=("leastrequest_plus_rl" "leastrequest_rl" "leastrequest_plus" "nodal_leastrequest" "only_nodal_leastrequest" "tmp_nodal_leastrequest" "minimize_diff" "locality_aware_weighted_random" "leastrequest" "weighted_random" "weighted_roundrobin" "weighted_leastrequest")
LB_VALUES=("nodal_leastrequest" "leastrequest_rl" "leastrequest_plus" "nodal_leastrequest" "only_nodal_leastrequest" "minimize_diff" "leastrequest")
# LB_VALUES=("locality_aware_weighted_random" "tmp_nodal_leastrequest")

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
