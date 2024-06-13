#!/bin/bash

set -x
set -e

NODES=3

# echo "[SCRIPT] Deleting any previous minikube cluster..."
# minikube delete --all

# echo "[SCRIPT] Starting empty minikube cluster with $NODES nodes [2 CPU / 4096 MB] using VirtualBox..."
# minikube start --nodes $((NODES+1)) --cpus 2 --memory 4096 --driver=virtualbox

# SLEEP_TIME=10
# echo "[SCRIPT] Sleeping for $SLEEP_TIME seconds..."
# sleep $SLEEP_TIME

# echo "[SCRIPT] Setting labels on each node..."
# for i in $(seq 1 $NODES);
# do
#   kubectl label node minikube-m0$(($i+1)) node-role.kubernetes.io/worker=node$i --overwrite
# done

# echo "[SCRIPT] Installing istio..."
# istioctl install -y
# kubectl label namespace default istio-injection=enabled
# # kubectl rollout restart deploy

# echo "[SCRIPT] Starting HotelReservation..."
# kubectl apply -Rf hotelReservation/kubernetes

# echo "[SCRIPT] Applying istio configs for hotelReservation..."
# kubectl apply -f istio-configs/hotelReservation.yaml

echo "[SCRIPT] Spawning host agents on each node..."
kubectl apply -f host_agent/pod_svc_for_master_node.yaml
for i in $(seq 1 $NODES)
do
  sed -i "s/node0/node$i/g" host_agent/pod_svc.yaml
  kubectl apply -f host_agent/pod_svc.yaml
  sed -i "s/node$i/node0/g" host_agent/pod_svc.yaml
done