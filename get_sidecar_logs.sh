kubectl logs --tail 5000 frontend-0 -c istio-proxy > log-fe
kubectl logs --tail 5000 recommendation-0 -c istio-proxy > log-r
kubectl logs --tail 5000 hostagent-node0-0 > log-ha
kubectl logs --tail 5000 istio-ingressgateway-6fc5889967-5wjfw -c istio-proxy -n istio-system > log-gw