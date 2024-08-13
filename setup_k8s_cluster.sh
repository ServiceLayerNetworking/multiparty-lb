#!/bin/bash

# set -x
set -e

NODES=5

# echo "[SCRIPT] Deleting any previous minikube cluster..."
# minikube delete --all

# echo "[SCRIPT] Starting empty minikube cluster with $NODES nodes [2 CPU / 3072 MB] using VirtualBox..."
# minikube start --nodes $((NODES+1)) --cpus 2 --memory 4096 --driver=virtualbox

# SLEEP_TIME=10
# echo "[SCRIPT] Sleeping for $SLEEP_TIME seconds..."
# sleep $SLEEP_TIME

# set metrics-server
# minikube addons enable metrics-server
# kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

echo "[SCRIPT] Setting labels on each node..."
for i in $(seq 1 $NODES);
do
  kubectl label node node$i.k8s-twaheed.mlnetwork.emulab.net node-role.kubernetes.io/worker=node$i --overwrite
done

echo "[SCRIPT] Installing istio..."
curl -L https://istio.io/downloadIstio | sh -
cd istio-1.22.3
export PATH=$PWD/bin:$PATH
cd ..

istioctl install -y
kubectl label namespace default istio-injection=enabled
kubectl rollout restart statefulset

echo "[SCRIPT] Applying jaeger..."
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/jaeger.yaml

# bash restart_wasm.sh
echo "[SCRIPT] installing WASM plugins.."
kubectl apply -f mplb-wasm-plugin/wasm.yaml

# echo "[SCRIPT] Applying taints to three nodes..."
# kubectl taint nodes minikube-m02 node=node1:NoSchedule
# kubectl taint nodes minikube-m03 node=node2:NoSchedule
# kubectl taint nodes minikube-m04 node=node3:NoSchedule

echo "[SCRIPT] Starting HotelReservation..."
kubectl apply -Rf DeathStarBench/hotelReservation/kubernetes

echo "[SCRIPT] Spawning host agents on each node..."
kubectl apply -f host_agent/pod_svc_for_master_node.yaml
for i in $(seq 1 $NODES)
do
  sed -i "s/node0/node$i/g" host_agent/pod_svc.yaml
  kubectl apply -f host_agent/pod_svc.yaml
  sed -i "s/node$i/node0/g" host_agent/pod_svc.yaml
done

echo "[SCRIPT] Applying istio configs for hotelReservation..."
kubectl apply -f istio-configs/hotelReservation.yaml
istio-configs/virtualservice-headermatch/vs-headermatch -services "consul,frontend" -exclude



