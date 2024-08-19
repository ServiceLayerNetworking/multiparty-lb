bash clear_k8s_cluster.sh

sleep 15

bash setup_k8s_cluster.sh

sleep 15

FRONTEND_IP=$(kubectl get svc frontend -n default -o jsonpath='{.spec.clusterIP}')
GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath='{.spec.clusterIP}')