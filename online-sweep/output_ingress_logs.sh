#!/bin/bash

mkdir -p proxy-logs

kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc0 -o jsonpath='{.items[0].metadata.name}') > ../proxy-logs/gw-svc0-0.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc0 -o jsonpath='{.items[1].metadata.name}') > ../proxy-logs/gw-svc0-1.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc0 -o jsonpath='{.items[2].metadata.name}') > ../proxy-logs/gw-svc0-2.log

kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc1 -o jsonpath='{.items[0].metadata.name}') > ../proxy-logs/gw-svc1-0.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc1 -o jsonpath='{.items[1].metadata.name}') > ../proxy-logs/gw-svc1-1.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc1 -o jsonpath='{.items[2].metadata.name}') > ../proxy-logs/gw-svc1-2.log

kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc2 -o jsonpath='{.items[0].metadata.name}') > ../proxy-logs/gw-svc2-0.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc2 -o jsonpath='{.items[1].metadata.name}') > ../proxy-logs/gw-svc2-1.log
kubectl logs -n istio-ingress --tail=10000 $(kubectl get pods -n istio-ingress -l istio=ingressgateway-svc2 -o jsonpath='{.items[2].metadata.name}') > ../proxy-logs/gw-svc2-2.log