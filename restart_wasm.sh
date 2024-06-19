#!/bin/bash

set -x

cd mplb-wasm-plugin
bash build-and-push.sh
kubectl delete -f wasm.yaml
sleep 5
kubectl apply -f wasm.yaml
sleep 5
kubectl rollout restart statefulset
sleep 5

echo "[SCRIPT] Waiting for all pods to be in running state"
cd ..
bash wait_for_pods.sh