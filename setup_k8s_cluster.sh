#!/bin/bash

# set -x
set -e

NODES=3

minikube delete --all

minikube start --nodes $((NODES+1)) --cpus 2 --memory 4096 --driver=virtualbox

sleep 10

# set labels
for i in $(seq 1 $NODES);
do
  kubectl label node minikube-m0$(($i+1)) node-role.kubernetes.io/worker=node$i
done

# spawn host agents on each node
for i in $(seq 1 $NODES)
do
  sed -i "s/node0/node$i/g" node$i.yaml
  kubectl apply -f host_agent/pod_svc.yaml
  sed -i "s/node$i/node0/g" node$i.yaml
done