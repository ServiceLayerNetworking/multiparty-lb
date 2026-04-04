#!/usr/bin/env python3
import argparse
import sys

def main():
    p = argparse.ArgumentParser(
        description="Generate an IstioOperator YAML with N ingress gateways (svc0..svc{N-1})."
    )
    p.add_argument("count", type=int, help="Number of services/gateways to generate (e.g., 20)")
    p.add_argument("--start", type=int, default=0, help="Starting index for svcN (default: 0)")
    p.add_argument("--name", default="istio-multi-gateways", help="IstioOperator metadata.name")
    p.add_argument("--namespace", default="istio-ingress", help="Gateway namespace")
    p.add_argument("--profile", default="default", help="Istio profile")
    p.add_argument("--service-type", default="LoadBalancer", help="K8s Service type")
    p.add_argument("--min-replicas", type=int, default=1, help="HPA minReplicas")
    p.add_argument("--max-replicas", type=int, default=1, help="HPA maxReplicas")
    p.add_argument("--cpu", default="100m", help="CPU request")
    p.add_argument("--memory", default="128Mi", help="Memory request")
    p.add_argument("--label-key", default="istio", help="Label key used under 'label:'")
    p.add_argument("--node-affinity-key", default="mplb/lb-node", help="Node affinity key")
    args = p.parse_args()

    if args.count <= 0:
        sys.exit("count must be >= 1")

    header = f"""apiVersion: install.istio.io/v1alpha3
kind: IstioOperator
metadata:
  name: {args.name}
spec:
  profile: {args.profile}
  components:
    ingressGateways:
"""

    def gateway_block(i: int) -> str:
        return f"""      - name: istio-ingressgateway-svc{i}
        namespace: {args.namespace}
        enabled: true
        label:
          {args.label_key}: ingressgateway-svc{i}
        k8s:
          service:
            type: {args.service_type}
          hpaSpec:
            minReplicas: {args.min_replicas}
            maxReplicas: {args.max_replicas}
          resources:
            requests:
              cpu: {args.cpu}
              memory: {args.memory}
          affinity:
            nodeAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
                nodeSelectorTerms:
                - matchExpressions:
                  - key: {args.node_affinity_key}
                    operator: Exists
"""

    blocks = []
    for i in range(args.start, args.start + args.count):
        blocks.append(gateway_block(i))

    sys.stdout.write(header + "".join(blocks))

if __name__ == "__main__":
    main()
