#!/bin/bash

set -x

# if $1 is empty, then set it to latest
if [ -z "$1" ]
then
    echo "[SCRIPT] No tag provided. Setting it to latest"
    TAG="latest"
else
    TAG=$1
fi

cd mplb-wasm-plugin

# replace every instance of mplb-plugin:<whatever> with mplb-plugin:$TAG in wasm.yaml
sed -i "s/mplb-plugin:.*/mplb-plugin:$TAG/g" wasm.yaml

# bash build-and-push.sh
kubectl delete -f wasm.yaml
sleep 5
kubectl apply -f wasm.yaml
sleep 5
kubectl rollout restart deployment istio-ingressgateway -n istio-system
kubectl rollout restart statefulset
sleep 5

echo "[SCRIPT] Waiting for all pods to be in running state"
cd ..
bash wait_for_pods.sh