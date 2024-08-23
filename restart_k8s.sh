bash clear_k8s_cluster.sh

sleep 15

bash setup_k8s_cluster.sh

sleep 15

echo "Run these commands to get the frontend and gateway IPs:"
echo 'FRONTEND_IP=$(kubectl get svc frontend -n default -o jsonpath="{.spec.clusterIP}")'
echo 'GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath="{.spec.clusterIP}")'