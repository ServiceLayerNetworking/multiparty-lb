import sys
import os
import time
from threading import Thread
from queue import Queue
import itertools
import yaml
import json
from kubernetes import client, config

DURATION = 30 # 5s
ADDITIONAL_TIME_FOR_CC_TO_RUN = 15 # 5 seconds
SLEEP_DURATION_AFTER_TOPOLOGY_CHANGE = 3 * 60 # 3 minutes
SLEEP_DURATION_AFTER_RESTARTING_K8S = 1 * 60 # 1 minute
SLEEP_TIME_AFTER_EACH_RUN = 1 * 15 # 1 minute
SLEEP_TIME_AFTER_WASM_BUILD = 100 # 100s
LOG_FOLDER = "logs30"
MANUAL_BUILD = True

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
    
    cmd = f"../hit/hit -d {DURATION} -distr exponential -rps {rps} -l {LOG_FOLDER}/{variation}_app{app_num}_{rps}rps_wrk.log -headers \"" + "{\\\"Host\\\": " +  f"\\\"app{app_num}.mplb.com\\" + "\"}\"" + f" -url \"http://{IP}/?loopCount=25&base=6&exp=6\""
    # e.g.: hit/hit -d 10 -distr exponential -rps 10 -l logs.t -headers "{\"Host\": \"app1.mplb.com\"}" -url "http://$GATEWAY_IP/?loopCount=EXP<25>&base=6&exp=6"
    # cmd = f"../wrk2/wrk -H \"Host: app{app_num}.mplb.com\" -t {t} -c {c} -d {DURATION} -L \"http://{IP}/?loopCount=25&base=6&exp=6\" -R{rps} > {LOG_FOLDER}/{variation}_app{app_num}_{rps}rps_wrk.log"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put((f"app{app_num}", start_time, end_time, 
           f"wrk for app{app_num} finished with exit status: {exit_status}"))

def run_cc(q, variation, enforcement):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../centralcontroller/centralcontroller -logfile {curr_dir}/{LOG_FOLDER}/{variation}_cc.log -enforcement={enforcement} -d={(DURATION + ADDITIONAL_TIME_FOR_CC_TO_RUN) * 1000}"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put(("cc", start_time, end_time, 
           f"CC finished with exit status: {exit_status}"))

def run_hit(q, variation, proc_distr, app_nums, rpses, distr):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    
    configs = []
    
    if proc_distr == "none" or proc_distr == "uniform":
        url = f"http://{IP}/?loopCount=25&base=6&exp=6"
    else:
        url = f"http://{IP}/?loopCount=EXP<25>&base=6&exp=6"
    
    for i, app_num in enumerate(app_nums):
        
        rps = rpses[i]
        
        configs.append({
            "endpoints": [
                {
                    "url": url,
                    "node": 1,
                    "app": app_num,
                    "headers": "{\"Host\":\"app" + str(app_num) + ".mplb.com\"}"
                }
            ],
            "reqIntervalMs": 1000.0 / float(rps),
            "durationMs": DURATION * 1000,
            "logFileName": f"{curr_dir}/{LOG_FOLDER}/{variation}_app{app_num}_{rps}rps_hit.log",
            "stallTimeMs": 0
        })
        
    with open(f"{curr_dir}/{LOG_FOLDER}/{variation}_hit.json", "w") as f:
        f.write(json.dumps(configs))
        
    cmd = f"../hit/hit -distr {distr} -f {curr_dir}/{LOG_FOLDER}/{variation}_hit.json"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put((f"hit", start_time, end_time, 
           f"hit for apps{app_nums} finished with exit status: {exit_status}"))
        
        

def run_exp(variation, rpses, enforcement, distr, proc_distr, append_to_times=""):
      
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {rpses} RPS")
    
    # send a request to the gurobi server to reset previous weights
    os.system("curl http://localhost:5000/reset")

    queues = []
    
    # run the wrk command in a separate thread
    # for i, rps in enumerate(rpses):
    #     # if i+1 > 1:
    #     #     continue
    #     q = Queue()
    #     Thread(target=run_wrk, args=(q, variation, i+1, rps)).start()
    #     queues.append(q)
        
    n_apps = len(rpses)
        
    # run the app workloads through a single hit
    q = Queue()
    Thread(target=run_hit, args=(q, variation, proc_distr, list(range(1, n_apps+1)), rpses, distr)).start()
        
    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    queues.append(q)
    
    times = []
    
    # wait for the wrk commands to finish
    for q in queues:
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
    
    print(f"Sleeping for {SLEEP_TIME_AFTER_EACH_RUN} seconds...")
    time.sleep(SLEEP_TIME_AFTER_EACH_RUN)

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
          resources:
            requests:
              cpu: 100m
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

def get_nodes_for_apps(nodes_for_pods):
    
    nodes_for_apps = {}
    
    for pod, node in nodes_for_pods.items():
        
        app = "-".join(pod.split("-")[:-1])
        print(app)
        
        if app not in nodes_for_apps:
            nodes_for_apps[app] = []
        
        nodes_for_apps[app].append(node)    

    return nodes_for_apps

def are_both_topologies_equal(intended_topology, actual_topology):
    
    for app in intended_topology:
        if app not in actual_topology:
            return False
        
        if intended_topology[app] != actual_topology[app]:
            return False
        
    return True

def get_topology_str(intended_topology):
    actual_topology = get_nodes_for_pods()
    
    nodes_for_apps = get_nodes_for_apps(actual_topology)
    print("Nodes for apps: ", nodes_for_apps)
    
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
    
def update_history_size_in_wasm(new_history_size):
    
    # edit `LOCALITY_AWARE_HISTORY_SIZE = (\d+)` in lb_locality_aware_weighted_random.go to new_history_size with `LOCALITY_AWARE_HISTORY_SIZE = new_history_size`
    
    with open("../mplb-wasm-plugin/lb_locality_aware_weighted_random.go", "r") as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if "\tLOCALITY_AWARE_HISTORY_SIZE = " in line:
            lines[i] = f"\tLOCALITY_AWARE_HISTORY_SIZE = {new_history_size}\n"
            
    with open("../mplb-wasm-plugin/lb_locality_aware_weighted_random.go", "w") as f:
        f.writelines(lines)
        
def update_load_balance_strategy(new_strategy):
    
    with open("../mplb-wasm-plugin/main.go", "r") as f:
        lines = f.readlines()
        
    for i, line in enumerate(lines):
        if "[locality_aware_weighted_random|leastrequest|weighted_random|weighted_roundrobin|weighted_leastrequest]" in line:
            lines[i] = f"\tLOAD_BALANCING_STRATEGY            = \"{new_strategy}\" // [locality_aware_weighted_random|leastrequest|weighted_random|weighted_roundrobin|weighted_leastrequest]\n"
            
    with open("../mplb-wasm-plugin/main.go", "w") as f:
        f.writelines(lines)
        
def build_wasm():
    os.chdir("../")
    os.system("bash restart_wasm.sh")
    os.chdir("./exp_3_node")
    
    if MANUAL_BUILD:
        print("WASM built and restarted. Press enter to continue...")
        input()
    else:
        print(f"Sleeping for {SLEEP_TIME_AFTER_WASM_BUILD}s after building wasm...")
        time.sleep(SLEEP_TIME_AFTER_WASM_BUILD)
    
LB_NAME = {
    "leastrequest": "lr",
    "weighted_random": "wr",
    "locality_aware_weighted_random": "lawr",
    "weighted_roundrobin": "wrr"
}
    
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
                
                if run_id in [3]:
                    
                    # restart_k8s()
                    
                    # if MANUAL_BUILD:
                    #     print("K8S restarted. Press enter to continue...")
                    #     input()
                    # else:
                    #     time.sleep(SLEEP_DURATION_AFTER_RESTARTING_K8S)
                    
                    # # Set topology for app1, app2, app3
                    # set_topology("app1", nodes_app1)
                    # set_topology("app2", nodes_app2)
                    # set_topology("app3", nodes_app3)
                    
                    # if MANUAL_BUILD:
                    #     print("Topology set. Press enter to continue...")
                    #     input()
                    # else:
                    #     time.sleep(SLEEP_DURATION_AFTER_TOPOLOGY_CHANGE)
                        
                    # rpses = [60*2]
                        
                    for lb in ["leastrequest"]: # [locality_aware_weighted_random|leastrequest|weighted_random|weighted_roundrobin|weighted_leastrequest]
                        
                        update_load_balance_strategy(lb)
                        build_wasm()
                                
                        # Define the RPS for 1 cpu
                        for rps in [35]:
                            
                            rpses = [rps*3, rps*2, rps*1]
                        
                            for iteration in [4]:
                            
                                for distr in ["none"]:
                                    
                                    for proc_distr in ["none"]:
                                
                                        # if distr != proc_distr:
                                        #     continue
                                    
                                        # print(f"Starting iteration {iteration} for run_id {run_id}...")
                                        
                                        intended_topology = {
                                            "app1": nodes_app1,
                                            "app2": nodes_app2,
                                            "app3": nodes_app3
                                        }
                                        print(intended_topology)
                                        
                                        to_append = get_topology_str(intended_topology)
                                        print(to_append)
                                        
                                        # # input()
                                        # run_exp(f"{distr}_lr_{run_id}_{iteration}", rpses, "NONE", distr, proc_distr, append_to_times=to_append)
                                        
                                        # input()
                                        run_exp(f"{distr}_{proc_distr}_mplb_{LB_NAME[lb]}rpsb_{run_id}_{rps}rps_{iteration}", rpses, "LB", distr, proc_distr, append_to_times=to_append)

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
    # rpses = [75, 50, 25]
    rpses = [100]

    # Run the experiment
    run_exp(f"lr_arb1_{0}", rpses, "NONE", append_to_times=to_append)
    # run_exp(f"mplb_{iteration}", rpses, "LB", append_to_times=to_append)

if __name__ == '__main__':
    
    # actual_topology = get_nodes_for_pods()
    # print(actual_topology)
    
    # Run the experiment
    run()
    
    # run_once(['node1', 'node2'], ['node2', 'node3'], ['node1'])
    
    # print_all_combinations()    
    # set_topology("app2")
    
