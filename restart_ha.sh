#!/bin/bash

set -x

cd host_agent
bash build-and-push.sh
sleep 5
kubectl rollout restart statefulset -n mplb-system hostagent-node0 hostagent-node1 hostagent-node2 hostagent-node3 hostagent-node4 hostagent-node5 hostagent-node6 hostagent-node7 hostagent-node8 hostagent-node9 hostagent-node10 hostagent-node11 hostagent-node12 hostagent-node13 hostagent-node14 hostagent-node15 hostagent-node16 hostagent-node17 hostagent-node18 hostagent-node19
sleep 5

echo "[SCRIPT] Waiting for all pods to be in running state"
cd ..
bash wait_for_pods.sh