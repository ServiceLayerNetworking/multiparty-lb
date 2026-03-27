from typing import Dict, List
from kubernetes import client, config, dynamic
from kubernetes.dynamic.exceptions import ResourceNotFoundError
from kubernetes.client import api_client
from collections import defaultdict
import re
import time
import subprocess
import json
import yaml
import os

def get_gateway_ip(svc_name, use_pod_ip=False):
    """
    Get the Cluster IP address of the Istio ingress gateway for a specific service.
    If use_pod_ip is True, returns the pod IP with :8080 instead.
    """
    # Load Kubernetes config
    config.load_kube_config()
    v1 = client.CoreV1Api()

    if use_pod_ip:
        # Get the pod IP instead of cluster IP
        max_retries = 10
        initial_delay = 2
        for attempt in range(max_retries):
            try:
                # List pods with the matching label selector
                pods = v1.list_namespaced_pod(
                    namespace="istio-ingress",
                    label_selector=f"istio=ingressgateway-{svc_name}"
                )
                if pods.items:
                    pod_ip = pods.items[0].status.pod_ip
                    return f"{pod_ip}:8080"
                else:
                    raise Exception(f"No pods found for istio-ingressgateway-{svc_name}")
            except client.exceptions.ApiException as e:
                if e.status == 500 and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⚠️ Webhook error (500) reading pods for {svc_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise
        raise Exception(f"Failed to read pods for {svc_name} after {max_retries} attempts")
    else:
        # Get the service object with retry logic
        max_retries = 10
        initial_delay = 2
        for attempt in range(max_retries):
            try:
                service = v1.read_namespaced_service(name=f"istio-ingressgateway-{svc_name}", namespace="istio-ingress")
                cluster_ip = service.spec.cluster_ip
                return cluster_ip
            except client.exceptions.ApiException as e:
                if e.status == 500 and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⚠️ Webhook error (500) reading service {svc_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise
        
        raise Exception(f"Failed to read service {svc_name} after {max_retries} attempts")

def get_gateway_ips(svc_name: str, use_pod_ip: bool = False) -> List[str]:
    """
    Get the Cluster IP address of the Istio ingress gateways for a specific service.
    If use_pod_ip is True, returns the pod IPs with :8080 instead.
    """
    # Load Kubernetes config
    config.load_kube_config()
    v1 = client.CoreV1Api()

    if use_pod_ip:
        # Get the pod IP instead of cluster IP
        max_retries = 10
        initial_delay = 2
        for attempt in range(max_retries):
            try:
                # List pods with the matching label selector
                pods = v1.list_namespaced_pod(
                    namespace="istio-ingress",
                    label_selector=f"istio=ingressgateway-{svc_name}"
                )
                if pods.items:
                    pod_ips = [pod.status.pod_ip for pod in pods.items]
                    return [f"{ip}:8080" for ip in pod_ips]
                else:
                    raise Exception(f"No pods found for istio-ingressgateway-{svc_name}")
            except client.exceptions.ApiException as e:
                if e.status == 500 and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⚠️ Webhook error (500) reading pods for {svc_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise
        raise Exception(f"Failed to read pods for {svc_name} after {max_retries} attempts")
    else:
        # Get the service object with retry logic
        max_retries = 10
        initial_delay = 2
        for attempt in range(max_retries):
            try:
                service = v1.read_namespaced_service(name=f"istio-ingressgateway-{svc_name}", namespace="istio-ingress")
                cluster_ip = service.spec.cluster_ip
                return [cluster_ip]
            except client.exceptions.ApiException as e:
                if e.status == 500 and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⚠️ Webhook error (500) reading service {svc_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise
        
        raise Exception(f"Failed to read service {svc_name} after {max_retries} attempts")

def get_curr_gateway_ips():
    svc_gateway_ips = {}
    for app in get_current_app_and_pods():
        svc_gateway_ips[app] = get_gateway_ip(app)
    return svc_gateway_ips

# Generate IstioOperator manifest
def generate_istio_operator(apps):
    operator = {
        "apiVersion": "install.istio.io/v1alpha3",
        "kind": "IstioOperator",
        "metadata": {
            "name": "istio-multi-gateways"
        },
        "spec": {
            "profile": "default",
            "components": {
                "ingressGateways": []
            }
        }
    }

    for app in apps:
        operator["spec"]["components"]["ingressGateways"].append({
            "name": f"istio-ingressgateway-{app}",
            "namespace": "istio-ingress",
            "enabled": True,
            "label": {
                "istio": f"ingressgateway-{app}"
            },
            "k8s": {
                "service": {
                    "type": "LoadBalancer"
                }
            }
        })

    with open("multi-gateways.yaml", "w") as f:
        yaml.dump(operator, f)

    print("Applying IstioOperator...")
    subprocess.run(["istioctl", "install", "-f", "multi-gateways.yaml", "-y"])

# Helper: Apply a manifest dict using the dynamic client
def apply_manifest(dyn_client, manifest, max_retries=10, initial_delay=2):
    kind = manifest["kind"]
    api_version = manifest["apiVersion"]
    namespace = manifest.get("metadata", {}).get("namespace", "default")

    group, _, version = api_version.partition("/")
    if group == "":
        group = "core"

    for attempt in range(max_retries):
        try:
            resource = dyn_client.resources.get(api_version=api_version, kind=kind)
            resource.create(body=manifest, namespace=namespace)
            print(f"✅ Created {kind}: {manifest['metadata']['name']}")
            print(manifest)
            print("-----")
            return
        except ResourceNotFoundError:
            print(f"❌ Could not find resource for kind {kind}")
            return
        except client.exceptions.ApiException as e:
            if e.status == 409:
                # Resource exists, replace it
                resource.patch(name=manifest["metadata"]["name"], namespace=namespace, body=manifest)
                print(f"🔁 Updated {kind}: {manifest['metadata']['name']}")
                return
            elif e.status == 500 and attempt < max_retries - 1:
                # Retry on 500 Internal Server Error (webhook issues)
                delay = initial_delay * (2 ** attempt)  # Exponential backoff
                print(f"⚠️ Webhook error (500) for {kind}: {manifest['metadata']['name']}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                raise
    
    # If we've exhausted retries
    raise Exception(f"Failed to apply {kind}: {manifest['metadata']['name']} after {max_retries} attempts")

# Get all pods in default namespace
def get_current_app_and_pods() -> Dict[str, List[str]]:
    output = subprocess.check_output(["kubectl", "get", "pods", "-n", "default", "-o", "json"]).decode()
    import json
    data = json.loads(output)
    pod_map = defaultdict(list)
    for item in data["items"]:
        name = item["metadata"]["name"]
        app_label = item["metadata"]["labels"].get("app")
        if app_label:
            pod_map[app_label].append(name)    
    return pod_map

def set_istio_routing_rules(apps_to_pods: Dict[str, List[str]]):

    # Load Kubernetes config (assumes you're running this locally with `~/.kube/config`)
    # Load kubeconfig
    config.load_kube_config()
    v1 = client.CoreV1Api()
    dyn_client = dynamic.DynamicClient(api_client.ApiClient())

    # Pods grouped by app label
    apps = apps_to_pods

    for app, pod_names in apps.items():
        # ---------------- Gateway ----------------
        gateway = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "Gateway",
            "metadata": {"name": f"ingress-gateway-{app}"},
            "spec": {
                "selector": {"istio": f"ingressgateway-{app}"},
                "servers": [{
                    "port": {
                        "number": 80,
                        "name": "http",
                        "protocol": "HTTP"
                    },
                    "hosts": [f"{app}.mplb.com"]
                }]
            }
        }
        # apply_manifest(dyn_client, gateway)

        # ---------------- DestinationRule ----------------
        destination_rule = {
            "apiVersion": "networking.istio.io/v1beta1",
            "kind": "DestinationRule",
            "metadata": {"name": f"{app}-destination", "namespace": "default"},
            "spec": {
                "host": app,
                "trafficPolicy": {
                    "loadBalancer": {
                        "simple": "LEAST_REQUEST"
                    }
                },
                "subsets": [{
                    "name": pod_name,
                    "labels": {"pod-name": pod_name}
                } for pod_name in pod_names]
            }
        }
        # apply_manifest(dyn_client, destination_rule)
        # kubectl get pods -n istio-ingress -l istio=ingressgateway-svc0 -o jsonpath='{.items[0].metadata.name}'


        # ---------------- VirtualService ----------------
        http_routes = []
        for pod_name in pod_names:
            http_routes.append({
                "match": [{
                    "headers": {
                        "x-lb-endpt": {
                            "exact": pod_name
                        }
                    }
                }],
                "route": [{
                    "destination": {
                        "host": app,
                        "subset": pod_name,
                        "port": {"number": 3333}
                    }
                }]
            })

        # Fallback route (least request)
        http_routes.append({
            "route": [{
                "destination": {
                    "host": app,
                    "port": {"number": 3333}
                }
            }]
        })

        virtual_service = {
            "apiVersion": "networking.istio.io/v1alpha3",
            "kind": "VirtualService",
            "metadata": {"name": f"{app}-virtualservice"},
            "spec": {
                "hosts": [f"{app}.mplb.com"],
                "gateways": [f"ingress-gateway-{app}"],
                "http": http_routes
            }
        }
        # apply_manifest(dyn_client, virtual_service)
        print(f"Applying Istio configs for app: {app}")
        print("----- Gateway -----")
        print(yaml.dump(gateway))
        print("----- DestinationRule -----")
        print(yaml.dump(destination_rule))
        print("----- VirtualService -----")
        print(yaml.dump(virtual_service))
        apply_manifest(dyn_client, gateway)
        apply_manifest(dyn_client, destination_rule)
        apply_manifest(dyn_client, virtual_service)

    print("\n✅ All Istio configs applied successfully.")

def get_curr_pod_count(namespace="default"):
    try:
        output = subprocess.check_output(
            f"kubectl get pods -n {namespace} --no-headers | wc -l",
            shell=True
        ).decode().strip()
        return int(output)
    except subprocess.CalledProcessError as e:
        print(f"Error fetching pod count: {e}")
        return -1

def wait_until_no_pods(timeout_seconds=60*5, check_interval=2, namespace="default"):
    start = time.time()
    while True:
        remaining = get_curr_pod_count(namespace)
        if remaining == 0:
            print("✅ No pods left in the default namespace.")
            return True
        elif remaining == -1:
            print("⚠️ Error while checking pods. Retrying...")

        elapsed = time.time() - start
        if elapsed > timeout_seconds:
            print(f"⏱️ Timeout reached after {timeout_seconds} seconds. {remaining} pod(s) still exist.")
            return False

        print(f"⏳ {remaining} pod(s) remaining... checking again in {check_interval}s.")
        time.sleep(check_interval)

def start_new_pods(pod_names: List[str]):
    """
    Set the topology of pods in a Kubernetes cluster based on the provided pod names.
    Each pod name should be in the format: svc<svc_id>-node<node_id>-<pod_id>.
    The function will create pods and services for each unique service ID (svc_id).
    The pods will be scheduled on the specified nodes (node_id) with a specific naming convention.
    The function will also create services for each app (unique svc_id) with NodePort type.
    Args:
        pod_names (list): List of pod names in the format: svc<svc_id>-node<node_id>-<pod_id>.
    """

    # Load kubeconfig from default location (~/.kube/config)
    config.load_kube_config()

    v1 = client.CoreV1Api()

    # Regular expression to match the pod name format (svc_id and node_id are digits)
    pod_name_regex = r"svc(\d+)-node(\d+)-(\d+)"

    # Group by service name and node, keep track of pod numbers
    svc_number_of_pods = {}

    # Parse each pod name and create the pod
    for pod_name in pod_names:
        # Use regular expression to parse the pod name
        match = re.match(pod_name_regex, pod_name)
        if match:
            svc_id = match.group(1)  # Extract svc_id (digits after 'svc')
            node_id = match.group(2)  # Extract node_id (digits after 'node')
            pod_id = match.group(3)   # Extract pod_id (arbitrary integer)
            
            svc_name = f"svc{svc_id}"
            node_name = f"node{int(node_id)+1}"

            # Assign a sequential pod number within each service
            if svc_id not in svc_number_of_pods:
                svc_number_of_pods[svc_id] = 0
            pod_number = svc_number_of_pods[svc_id]

            # Create the new pod name: svc<svc_id>-<pod_number>
            new_pod_name = f"svc{svc_id}-{pod_number}"
            
            print(f"Creating {pod_name} as {new_pod_name} on {node_name}")

            # Create the Pod
            pod = client.V1Pod(
                metadata=client.V1ObjectMeta(name=new_pod_name, labels={"app": svc_name, "pod-name": new_pod_name}),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name=svc_id,
                            image="ghcr.io/talha-waheed/generic-app:latest",
                            image_pull_policy="Always",
                            ports=[client.V1ContainerPort(container_port=3333)],
                            resources=client.V1ResourceRequirements(
                                requests={"cpu": "100m"}
                            ),
                        )
                    ],
                    tolerations=[
                        client.V1Toleration(key="node", value=node_name, effect="NoSchedule"),
                        client.V1Toleration(key="worker-pod", value="true", effect="NoSchedule")
                    ],
                    affinity=client.V1Affinity(
                        node_affinity=client.V1NodeAffinity(
                            required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                                node_selector_terms=[
                                    client.V1NodeSelectorTerm(
                                        match_expressions=[
                                            client.V1NodeSelectorRequirement(
                                                key="node-role.kubernetes.io/worker",
                                                operator="In",
                                                values=[node_name],
                                            )
                                        ]
                                    )
                                ]
                            )
                        )
                    ),
                ),
            )

            # Print and create the pod with retry logic
            print(f"Creating pod: {new_pod_name} on {node_id}")
            max_retries = 10
            initial_delay = 2
            for attempt in range(max_retries):
                try:
                    v1.create_namespaced_pod(namespace="default", body=pod)
                    svc_number_of_pods[svc_id] += 1
                    break
                except client.exceptions.ApiException as e:
                    if e.status == 500 and attempt < max_retries - 1:
                        delay = initial_delay * (2 ** attempt)
                        print(f"⚠️ Webhook error (500) creating pod {new_pod_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                    else:
                        raise
            else:
                raise Exception(f"Failed to create pod {new_pod_name} after {max_retries} attempts")
        else:
            print(f"Invalid pod name format: {pod_name}")

    # Create services for each app (unique svc_id)
    for svc_id in svc_number_of_pods:
        
        svc_name = f"svc{svc_id}"
        
        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=svc_name, labels={"app": svc_name}),
            spec=client.V1ServiceSpec(
                type="NodePort",
                selector={"app": svc_name},
                ports=[
                    client.V1ServicePort(port=3333, target_port=3333),
                ],
            ),
        )
        print(f"Creating service for app: {svc_name}")
        max_retries = 10
        initial_delay = 2
        for attempt in range(max_retries):
            try:
                v1.create_namespaced_service(namespace="default", body=service)
                break
            except client.exceptions.ApiException as e:
                if e.status == 500 and attempt < max_retries - 1:
                    delay = initial_delay * (2 ** attempt)
                    print(f"⚠️ Webhook error (500) creating service {svc_name}. Retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                else:
                    raise
        else:
            raise Exception(f"Failed to create service {svc_name} after {max_retries} attempts")
        
    print("All pods and services created successfully.")

def get_all_pods_status(namespace="default"):
    try:
        output = subprocess.check_output([
            "kubectl", "get", "pods", "-n", namespace, "-o", "json"
        ]).decode()
        pod_data = json.loads(output)
        return pod_data["items"]
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching pods: {e}")
        return []

def all_pods_ready(pods):
    for pod in pods:
        name = pod["metadata"]["name"]
        # print(f"Checking pod: {name}: {pod['status']}", pod["metadata"].get("deletionTimestamp"))
        phase = pod["status"].get("phase", "")
        container_statuses = pod["status"].get("containerStatuses", [])

        if phase != "Running" or pod["metadata"].get("deletionTimestamp") is not None:
            print(f"⏳ Pod {name} is in phase '{phase}' or is being deleted.")
            return False

        for c in container_statuses:
            if not c.get("ready", False):
                print(f"⏳ Container {c['name']} in pod {name} is not ready")
                return False

    return True

def wait_until_all_pods_ready(timeout_seconds=60*5, check_interval=2, namespace="default"):
    
    # wait for a grace period first before checking the status of pods
    time.sleep(5)
    
    start = time.time()
    while True:
        pods = get_all_pods_status(namespace=namespace)
        print(f"Found {len(pods)} pods in namespace '{namespace}'")
        if not pods:
            print("ℹ️ No pods found in the namespace.")
            return True

        if all_pods_ready(pods):
            print("✅ All pods and containers are running and ready.")
            return True

        elapsed = time.time() - start
        if elapsed > timeout_seconds:
            print("⏱️ Timeout waiting for pods to be ready.")
            return False

        time.sleep(check_interval)

def clear_cluster():
    """
    Clear all
    pods, services, statefulsets, deployments
    destinationrules, virtualservices, gateways.networking.istio.io
    from the default namespace.
    """
    
    os.system("kubectl delete pods --all -n default")
    os.system("kubectl delete services --all -n default")
    os.system("kubectl delete statefulsets --all -n default")
    os.system("kubectl delete deployments --all -n default")
    
    os.system("kubectl delete destinationrules.networking.istio.io --all -n default")
    os.system("kubectl delete virtualservices.networking.istio.io --all -n default")
    os.system("kubectl delete gateways.networking.istio.io --all -n default")
    
    print("All pods, services, statefulsets, deployments, " + 
          "destinationrules, virtualservices, and gateways " + 
          "deleted from the default namespace.")
    
    os.system("kubectl delete destinationrules.networking.istio.io --all -n istio-ingress")
    os.system("kubectl delete virtualservices.networking.istio.io --all -n istio-ingress")
    os.system("kubectl delete gateways.networking.istio.io --all -n istio-ingress")

    print("All destination rules, virtual services, and gateways deleted from the istio-ingress namespace.")

def setup_clutser_with_new_pods(pod_names: List[str]) -> bool:
    
    # assume that istio is set up with the wasm plugins that have the right LB 
    
    # first clear the cluster
    print("Clearing the cluster...")
    clear_cluster()
    
    # wait until all pods are gone
    print("Waiting for all pods to be deleted...")
    done = wait_until_no_pods(timeout_seconds=60*5, check_interval=2)
    if not done:
        print("❌ Timeout waiting for pods to be deleted.")
        return False
    else:
        print("All pods are deleted.")
    
    # start new pods
    print("Starting new pods...")
    start_new_pods(pod_names)
    
    # wait until all pods are ready
    print("Waiting for all pods to be ready...")
    done = wait_until_all_pods_ready(timeout_seconds=60*5, check_interval=2, namespace="default")
    if not done:
        print("❌ Timeout waiting for pods to get ready.")
        return False
    else:
        print("All pods are ready.")
    
    # get current apps and pods
    print("Getting current apps and pods...")
    curr_app_to_pods = get_current_app_and_pods()
    
    # set routing rules
    print("Setting Istio gateway, destination rules, and virtual services...")
    set_istio_routing_rules(curr_app_to_pods)
    
    # restart the ingress gateways
    print("Restarting ingress gateways...")
    os.system("kubectl rollout restart deploy -n istio-ingress")
    
    # wait until all pods are ready
    print("Waiting for all istio-ingress pods to be ready...")
    done = wait_until_all_pods_ready(timeout_seconds=60*5, check_interval=2, namespace="istio-ingress")
    if not done:
        print("❌ Timeout waiting for gateway pods to get ready.")
        return False
    else:
        print("All pods are ready.")

    return True

def test():
    print(get_curr_gateway_ips())
    
if __name__ == "__main__":
    
    # for i in range(15):
    #     print(f"svc{i}", "\t", get_gateway_ip(f"svc{i}", use_pod_ip=True))
    
    # os.system("kubectl delete destinationrules.networking.istio.io --all -n default")
    # os.system("kubectl delete virtualservices.networking.istio.io --all -n default")
    # os.system("kubectl delete gateways.networking.istio.io --all -n default")
    
    # # print("All pods, services, statefulsets, deployments, " + 
    # #       "destinationrules, virtualservices, and gateways " + 
    # #       "deleted from the default namespace.")
    
    # os.system("kubectl delete destinationrules.networking.istio.io --all -n istio-ingress")
    # os.system("kubectl delete virtualservices.networking.istio.io --all -n istio-ingress")
    # os.system("kubectl delete gateways.networking.istio.io --all -n istio-ingress")
    
    # # get current apps and pods
    # print("Getting current apps and pods...")
    # curr_app_to_pods = get_current_app_and_pods()
    
    # print("Current apps and pods:", curr_app_to_pods)
    
    # # set routing rules
    # print("Setting Istio gateway, destination rules, and virtual services...")
    # set_istio_routing_rules(curr_app_to_pods)
    
    # pod_names = [
    #     "svc0-node0-0",
    #     "svc0-node1-0",
    #     "svc1-node1-0",
    #     "svc1-node2-0",
    #     "svc2-node0-0",
    # ]
    # setup_clutser_with_new_pods(pod_names)
    
    # # config 71296
    # pod_names = [
    #     'svc0-node0-0',
    #     'svc0-node0-1',
    #     'svc0-node0-2',
    #     'svc1-node0-0',
    #     'svc1-node0-1',
    #     'svc1-node1-0',
    #     'svc1-node1-1',
    #     'svc1-node1-2',
    #     'svc2-node1-0',
    #     'svc2-node1-1',
    #     'svc2-node2-0',
    #     'svc2-node2-1',
    #     'svc2-node2-2',
    #     'svc2-node2-3',
    #     'svc2-node2-4'
    # ]
    
    # setup_clutser_with_new_pods(pod_names)
    
    
    
    # # restart the ingress gateways
    # print("Restarting ingress gateways...")
    # os.system("kubectl rollout restart deploy -n istio-ingress")
    
    # # wait until all pods are ready
    # print("Waiting for all istio-ingress pods to be ready...")
    # done = wait_until_all_pods_ready(timeout_seconds=60*5, check_interval=2, namespace="istio-ingress")
    # if not done:
    #     print("❌ Timeout waiting for gateway pods to get ready.")
    # else:
    #     print("All pods are ready.")
    
    pod_names = [
        "svc0-node0-0",
        "svc0-node1-0",
        "svc1-node1-0",
        "svc2-node2-0",
    ]
    
    setup_clutser_with_new_pods(pod_names)