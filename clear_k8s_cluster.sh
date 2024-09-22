#!/bin/bash

set -x

kubectl delete -Rf generic-app/3-node-scenario

bash hostagents_delete.sh

kubectl delete -f dst-rules_virtual-svcs/hotelReservation.yaml
kubectl delete destinationrules --all
kubectl delete virtualservices --all

kubectl delete -f mplb-wasm-plugin/wasm.yaml

kubectl delete -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/jaeger.yaml

istioctl uninstall -y --purge

kubectl delete -f https://raw.githubusercontent.com/pythianarora/total-practice/master/sample-kubernetes-code/metrics-server.yaml

