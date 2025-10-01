#!/bin/bash

# sudo apt update && sudo apt install socat
# kubectl create namespace istio-ingress

set -x
set -e

# check if istio is installed
if ! command -v istioctl &> /dev/null; then
    echo "istioctl could not be found. Please install Istio CLI first."
    exit 1
fi

# number of nodes in the cluster
ALL_NODES=20
# number of control plane nodes
CP_NODES=1
# number of worker nodes
NODES=19
# number of worker nodes to be used as load balancer nodes
LB_NODES=4
# number of services
N_SVCS=15

# echo "[SCRIPT] Deleting any previous minikube cluster..."
# minikube delete --all

# echo "[SCRIPT] Starting empty minikube cluster with $NODES nodes [2 CPU / 3072 MB] using VirtualBox..."
# minikube start --nodes $((NODES+1)) --cpus 2 --memory 4096 --driver=virtualbox

# SLEEP_TIME=10
# echo "[SCRIPT] Sleeping for $SLEEP_TIME seconds..."
# sleep $SLEEP_TIME

# set metrics-server
# minikube addons enable metrics-server
kubectl apply -f https://raw.githubusercontent.com/pythianarora/total-practice/master/sample-kubernetes-code/metrics-server.yaml


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

echo "[SCRIPT] Setting labels on each node..."
for i in $(seq 1 $NODES);
do
  kubectl label node node$i.$CLUSTER_NAME node-role.kubernetes.io/worker=node$i --overwrite
done
kubectl label node node0.$CLUSTER_NAME node-role.kubernetes.io/control-plane=master --overwrite

# if nodes <= 3 then label master node as the mplb/lb-node else label last LB_NODES worker nodes as mplb/lb-node
if [ "$NODES" -le 3 ]; then
  kubectl label node node0.$CLUSTER_NAME mplb/lb-node=master --overwrite
else
  for i in $(seq $((NODES-LB_NODES+1)) $NODES); do
    kubectl label node node$i.$CLUSTER_NAME mplb/lb-node=worker --overwrite
  done
fi

# kubectl label node node16.$CLUSTER_NAME mplb/lb-node=worker --overwrite
# kubectl label node node17.$CLUSTER_NAME mplb/lb-node=worker --overwrite
# kubectl label node node18.$CLUSTER_NAME mplb/lb-node=worker --overwrite
# kubectl label node node19.$CLUSTER_NAME mplb/lb-node=worker --overwrite

sudo apt update && sudo apt install socat -y
NAMESPACE="istio-ingress"
if ! kubectl get namespace "$NAMESPACE" > /dev/null 2>&1; then
  kubectl create namespace "$NAMESPACE"
fi

# remove master node taint if NODES <=3
if [ "$NODES" -le 3 ]; then
  kubectl taint nodes node0.$CLUSTER_NAME node-role.kubernetes.io/control-plane:NoSchedule-
fi

python3 generate_istio_gateways.py $N_SVCS > dst-rules_virtual-svcs/istio-multi-gateways.yaml

istioctl install -y -f ~/multiparty-lb/dst-rules_virtual-svcs/istio-multi-gateways.yaml
kubectl label namespace default istio-injection=enabled --overwrite
kubectl rollout restart statefulset

echo "[SCRIPT] Applying jaeger..."
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/jaeger.yaml

# bash restart_wasm.sh
echo "[SCRIPT] installing WASM plugins.."
kubectl apply -f dst-rules_virtual-svcs/node-env-var-labels.yaml
kubectl apply -f dst-rules_virtual-svcs/arbitrarySvc.yaml
kubectl apply -f mplb-wasm-plugin/wasm.yaml

# Loop through all deployments in the istio-ingress namespace and remove the resource limits
for d in $(kubectl get deploy -n istio-ingress -o jsonpath='{.items[*].metadata.name}'); do
    echo "Patching deployment: $d"
    # Patch the deployment to remove the resource limits
    kubectl patch deployment "$d" -n istio-ingress \
        --type='json' \
        -p='[
            {
                "op": "remove",
                "path": "/spec/template/spec/containers/0/resources/limits"
            }
        ]'
    echo "Limits removed from deployment: $d"
done

echo "Limits have been removed from all deployments in istio-ingress."
echo "[SCRIPT] Applying taints to three nodes..."
kubectl taint nodes node1.$CLUSTER_NAME node=node1:NoSchedule --overwrite
kubectl taint nodes node2.$CLUSTER_NAME node=node2:NoSchedule --overwrite
kubectl taint nodes node3.$CLUSTER_NAME node=node3:NoSchedule --overwrite

# echo "[SCRIPT] Starting the Docker registry..."
# kubectl apply -f docker-registry/registry.yaml

# echo "[SCRIPT] Starting HotelReservation..."
# kubectl apply -Rf DeathStarBench/hotelReservation/kubernetes

# echo "[SCRIPT] Starting Generic Apps..."
# kubectl apply -Rf generic-app/3-node-scenario

echo "[SCRIPT] Creating namespace mplb-system if it doesn't exist..."
kubectl get namespace mplb-system > /dev/null 2>&1 || kubectl create namespace mplb-system

# kubectl apply -f dst-rules_virtual-svcs/hotelReservation.yaml

echo "[SCRIPT] Creating high priority class for host agents..."
kubectl apply -f host_agent/priority_class.yaml 

echo "[SCRIPT] Spawning host agents on each node..."
kubectl apply -f host_agent/pod_svc_for_master_node.yaml
for i in $(seq 1 $NODES)
do
  sed -i "s/node0/node$i/g" host_agent/pod_svc.yaml
  kubectl apply -f host_agent/pod_svc.yaml
  sed -i "s/node$i/node0/g" host_agent/pod_svc.yaml
done

# echo "[SCRIPT] Applying istio configs for hotelReservation..."
# kubectl apply -f dst-rules_virtual-svcs/hotelReservation.yaml
# dst-rules_virtual-svcs/virtualservice-headermatch/vs-headermatch -exclude
# kubectl rollout restart statefulset
# kubectl rollout restart deploy istio-ingressgateway -n istio-system

# echo "Run these commands to get the frontend and gateway IPs:"
# echo 'GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath="{.spec.clusterIP}")'
