import sys
import os
import time
from threading import Thread
from queue import Queue
import itertools
import yaml
import json
from kubernetes import client, config

LOG_FOLDER = "logs_arb"

def get_gateway_ip():
    """
    get gateway ip from this command
    GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath="{.spec.clusterIP}")
    """
    cmd = "kubectl get svc istio-ingressgateway -n istio-system -o jsonpath=\"{.spec.clusterIP}\""
    ip = os.popen(cmd).read().strip()
    return ip

IP = get_gateway_ip()

def run_wrk(q, variation, app_num, rps):
    
    c, t = (1, 1) if rps <= 25 else (5, 5)
    cmd = f"../wrk2/wrk -H \"Host: app{app_num}.mplb.com\" -t {t} -c {c} -d 30 -L \"http://{IP}/?loopCount=25&base=6&exp=6\" -R{rps} > {LOG_FOLDER}/{variation}_app{app_num}_{rps}rps_wrk.log"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put((f"app{app_num}", start_time, end_time, 
           f"wrk for app{app_num} finished with exit status: {exit_status}"))

def run_cc(q, variation, enforcement):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../centralcontroller/centralcontroller -logfile {curr_dir}/{LOG_FOLDER}/{variation}_cc.log -enforcement={enforcement} -d={40_000}"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put(("cc", start_time, end_time, 
           f"CC finished with exit status: {exit_status}"))

def run_exp(variation, rpses, enforcement, append_to_times=""):
      
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {rpses} RPS")

    # run the wrk command in a separate thread
    qeues = []
    for i, rps in enumerate(rpses):
        # if i+1 > 1:
        #     continue
        q = Queue()
        Thread(target=run_wrk, args=(q, variation, i+1, rps)).start()
        qeues.append(q)
        
    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    qeues.append(q)
    
    times = []
    
    # wait for the wrk commands to finish
    for q in qeues:
        thread_name, start_time, end_time, finish_status = q.get()
        times.append((thread_name, start_time, end_time))
        print(finish_status)
        
    # print the times to file "logs/{variation}.times"
    with open(f"{LOG_FOLDER}/{variation}.times", "w") as f:
        f.write(append_to_times + "\n")
        for thread_name, start_time, end_time in times:
            f.write(f"{thread_name} {start_time} {end_time}\n")
    
    print(f"Completed experiment with {variation} at {rpses} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    
    print("Sleeping for 15 seconds...")
    time.sleep(15)

def update_yaml(app_name, yaml_data, selected_nodes):
    data = yaml.safe_load(yaml_data)

    data['metadata']['name'] = app_name
    data['metadata']['labels']['app'] = app_name
    data['spec']['replicas'] = len(selected_nodes)
    data['spec']['selector']['matchLabels']['app'] = app_name
    data['spec']['template']['metadata']['labels']['app'] = app_name
    data['spec']['template']['spec']['containers'][0]['name'] = app_name
    

    selected_nodes = list(selected_nodes)
    print("Selected nodes: ", selected_nodes)
    # input()

    for i, node in enumerate(selected_nodes):
        data['spec']['template']['spec']['tolerations'][i]['value'] = node

    data['spec']['template']['spec']['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchExpressions'][0]['values'] = selected_nodes
    return yaml.dump(data, default_flow_style=False)

def set_topology(app, nodes):
    yaml_data = """
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: app1
  labels:
    app: app1
spec:
  replicas: 2
  selector:
    matchLabels:
      app: app1
  template:
    metadata:
      labels:
        app: app1
    spec:
      containers:
        - name: app1
          image: ghcr.io/talha-waheed/generic-app:latest
          imagePullPolicy: Always
          ports:
            - containerPort: 3333
              protocol: TCP
      tolerations:
        - key: "node"
          value: "node1"
          effect: "NoSchedule"
        - key: "node"
          value: "node2"
          effect: "NoSchedule"
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: node-role.kubernetes.io/worker
                operator: In
                values:
                - node1
                - node2
    """

    # updated_yaml = update_yaml(app, yaml_data, nodes)
    # print(updated_yaml)
    
    # Update the YAML structure with the app and node selection
    updated_yaml = update_yaml(app, yaml_data, nodes)
    
    # Save the updated YAML to a temporary file
    yaml_file_path = f"/tmp/{app}_deployment.yaml"
    with open(yaml_file_path, "w") as yaml_file:
        yaml_file.write(updated_yaml)
    
    print(f"Applied YAML for {app} with nodes {nodes}")
    
    # Apply the updated YAML to the Kubernetes cluster
    os.system(f"kubectl apply -f {yaml_file_path}")

def wait_for_pods_in_running_state(namespace="default", target_pod_count=5, interval=2):
    # Load kube config
    config.load_kube_config()  # Use config.load_incluster_config() if running inside a cluster

    # Create an instance of the CoreV1Api
    v1 = client.CoreV1Api()

    while True:
        # Get the list of pods in the specified namespace
        pods = v1.list_namespaced_pod(namespace)

        # Filter the pods that are in 'Running' state
        running_pods = [pod for pod in pods.items if pod.status.phase == "Running"]
        print(f"Found {[pod.spec.name for pod in running_pods]} running pods")

        # Check if the number of running pods matches the target
        if len(running_pods) == target_pod_count:
            print(f"All {target_pod_count} pods are running.")
            break
        else:
            print(f"Found {len(running_pods)} running pods, waiting for {target_pod_count} pods to be running...")
        
        # Wait before the next check
        time.sleep(interval)

def get_nodes_for_pods():

    # Load Kubernetes configuration
    config.load_kube_config()  # for local environments
    # config.load_incluster_config()  # Uncomment this if running inside a Kubernetes pod

    # Create API client
    v1 = client.CoreV1Api()

    # List all pods in default namespace
    pods = v1.list_namespaced_pod(namespace='default', watch=False)

    pod_nodes = {}

    # Iterate through the pods and print app name (pod name) and node
    for pod in pods.items:
        pod_name = pod.metadata.name       # Pod name
        node_name = pod.spec.node_name     # Node where the pod is running
        print(f"App (Pod) Name: {pod_name}, Node: {node_name}")
        pod_nodes[pod_name] = node_name
        
    return pod_nodes

def get_topology_str(intended_topology):
    actual_topology = get_nodes_for_pods()
    return json.dumps({
        "actual": actual_topology,
        "intended": intended_topology
    })

def restart_k8s():
    os.chdir("../")
    os.system("bash restart_k8s.sh")
    os.chdir("./exp_3_node")
    
    global IP
    IP = get_gateway_ip()
    
def run():
    
    # change dir to previous directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../centralcontroller")
    os.system("go build .")
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../exp_3_node")
    
    nodes = ['node1', 'node2', 'node3']
    
    run_id = 0
    
    # Sweep through all combinations
    for nodes_app1 in itertools.combinations(nodes, 2):
        for nodes_app2 in itertools.combinations(nodes, 2):
            for nodes_app3 in itertools.combinations(nodes, 1):
                print(f"Running experiment with: app1={nodes_app1}, app2={nodes_app2}, app3={nodes_app3}")
                
                run_id += 1
                
                if run_id == 17:
                    
                    restart_k8s()
                        
                    time.sleep(60)
                    
                    # Set topology for app1, app2, app3
                    set_topology("app1", nodes_app1)
                    set_topology("app2", nodes_app2)
                    set_topology("app3", nodes_app3)
                        
                    time.sleep(5 * 60) # sleep for 10 minutes
                    
                    for iteration in range(1, 6):
                        print(f"Starting iteration {iteration}...")
                        
                        intended_topology = {
                            "app1": nodes_app1,
                            "app2": nodes_app2,
                            "app3": nodes_app3
                        }
                        print(intended_topology)
                        # input()
                        
                        to_append = get_topology_str(intended_topology)
                        print(to_append)
                        # input()
                        
                        # Define the RPS for each app
                        rpses = [75, 50, 25]
                    
                        # Run the experiment
                        run_exp(f"lr_{iteration}", rpses, "NONE", append_to_times=to_append)
                        run_exp(f"mplb_{iteration}", rpses, "LB", append_to_times=to_append)

def print_all_combinations(): 
    
    run = 0
    
    nodes = ['node1', 'node2', 'node3']
    for nodes_app1 in itertools.combinations(nodes, 2):
        for nodes_app2 in itertools.combinations(nodes, 2):
            for nodes_app3 in itertools.combinations(nodes, 1):
                
                intended_topology = {
                    "app1": nodes_app1,
                    "app2": nodes_app2,
                    "app3": nodes_app3
                }
                
                run += 1
                print(f"Run {run}:", intended_topology)


# def run():
    
#     # change dir to previous directory
#     os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../centralcontroller")
#     os.system("go build .")
#     os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../exp_3_node")
    
#     rpses = [75, 50, 25]
    
    
#     experiment_config = {
#         "apps"
#     }
    
#     app = "app1"
#     nodes = "node1,node2"
#     os.system(f"bash {app}, {nodes}")
    
#     run_exp(f"lr_{5}", rpses, "NONE")
#     run_exp(f"lr_{6}", rpses, "NONE")
    
#     # for run in range(5, 10):
#     #     run_exp(f"lr_{run}", rpses, "NONE")
#     #     run_exp(f"mplb_{run}", rpses, "LB")

def run_once(nodes_app1, nodes_app2, nodes_app3):
    
    # change dir to previous directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../centralcontroller")
    os.system("go build .")
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../exp_3_node")

    # restart_k8s()
        
    # time.sleep(60)
    
    # # Set topology for app1, app2, app3
    # set_topology("app1", nodes_app1)
    # set_topology("app2", nodes_app2)
    # set_topology("app3", nodes_app3)
        
    # time.sleep(5 * 60) # sleep for 10 minutes
    
    intended_topology = {
        "app1": nodes_app1,
        "app2": nodes_app2,
        "app3": nodes_app3
    }
    print(intended_topology)
    # input()
    
    to_append = get_topology_str(intended_topology)
    print(to_append)
    # input()
    
    # Define the RPS for each app
    rpses = [75, 50, 25]

    # Run the experiment
    run_exp(f"lr_arb1_{0}", rpses, "NONE", append_to_times=to_append)
    # run_exp(f"mplb_{iteration}", rpses, "LB", append_to_times=to_append)

if __name__ == '__main__':
    # Run the experiment
    # run()
    
    run_once(['node1', 'node2'], ['node2', 'node3'], ['node1'])
    
    # print_all_combinations()    
    # set_topology("app2")
