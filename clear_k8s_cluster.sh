#!/bin/bash

set -x

kubectl delete -Rf generic-app/3-node-scenario
kubectl delete pod --all -n default

bash hostagents_delete.sh

kubectl delete -f dst-rules_virtual-svcs/hotelReservation.yaml
kubectl delete destinationrules --all
kubectl delete virtualservices --all

kubectl delete -f mplb-wasm-plugin/wasm.yaml

kubectl delete -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/jaeger.yaml

istioctl uninstall -y --purge

kubectl delete -f https://raw.githubusercontent.com/pythianarora/total-practice/master/sample-kubernetes-code/metrics-server.yaml

# Extract cluster name from 'kubectl get nodes' output
NODE0_LINE=$(kubectl get nodes --no-headers | grep node0)
if [[ -z "$NODE0_LINE" ]]; then
  echo "Could not find node0 in kubectl get nodes output."
  exit 1
fi
NODE0_NAME=$(echo "$NODE0_LINE" | awk '{print $1}')
CLUSTER_NAME=${NODE0_NAME#node0.}
export CLUSTER_NAME
echo "[SCRIPT] Detected cluster name: $CLUSTER_NAME"

# Get the number of worker nodes
NODES=$(kubectl get nodes --no-headers | grep -c "node[1-9]")
echo "[SCRIPT] Found $NODES worker nodes"

# Remove labels from all nodes
echo "[SCRIPT] Removing labels from all nodes..."
kubectl label node node0.$CLUSTER_NAME node-role.kubernetes.io/control-plane- || true
kubectl label node node0.$CLUSTER_NAME mplb/lb-node- || true

for i in $(seq 1 $NODES); do
  kubectl label node node$i.$CLUSTER_NAME node-role.kubernetes.io/worker- || true
  kubectl label node node$i.$CLUSTER_NAME mplb/lb-node- || true
done

# Remove taints from all nodes
echo "[SCRIPT] Removing taints from all nodes..."
kubectl taint nodes node0.$CLUSTER_NAME node-role.kubernetes.io/control-plane:NoSchedule- || true

for i in $(seq 1 $NODES); do
  kubectl taint nodes node$i.$CLUSTER_NAME node=node$i:NoSchedule- || true
done
