#!/bin/bash

set -x

cd host_agent
bash build-and-push.sh
sleep 5
kubectl rollout restart statefulset hostagent-node0 hostagent-node1 hostagent-node2 hostagent-node3 hostagent-node4

echo "[SCRIPT] Waiting for all pods to be in running state"
cd ..
bash wait_for_pods.sh