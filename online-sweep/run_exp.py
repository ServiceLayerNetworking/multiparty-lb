from typing import List, Dict, Tuple
from collections import defaultdict
from kubernetes import client, config
from queue import Queue
from threading import Thread
import os
import time
import json

from set_topology import setup_clutser_with_new_pods, get_curr_gateway_ips

# Everything in seconds:
DURATION = 60 
DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC = 5 
ADDITIONAL_TIME_FOR_CC_TO_RUN = 30
SLEEP_DURATION_AFTER_TOPOLOGY_CHANGE = 5 
SLEEP_TIME_AFTER_EACH_RUN = 10

LOG_FOLDER = "logs/logs0"

GATEWAY_IPs = get_curr_gateway_ips()

def build_central_controller():
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    # change dir to previous directory
    os.chdir(curr_dir + "/../centralcontroller")
    os.system("go build .")
    os.chdir(curr_dir)
    
def modify_wasm_plugin(lb):
    print(f"Modifying wasm plugin to use {lb}...")
    os.system(f'sed -i "s/mplb-plugin:.*/mplb-plugin:{lb}/g" ../mplb-wasm-plugin/wasm.yaml')
    os.system('kubectl delete -f ../mplb-wasm-plugin/wasm.yaml')
    time.sleep(1)
    os.system('kubectl apply -f ../mplb-wasm-plugin/wasm.yaml')
    time.sleep(1)

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
 
def get_topology_str(intended_topology):
    actual_topology = get_nodes_for_pods()
    
    nodes_for_apps = get_nodes_for_apps(actual_topology)
    print("Nodes for apps: ", nodes_for_apps)
    
    return json.dumps({
        "actual": actual_topology,
        "intended": intended_topology
    })
    
LB_NAME = {
    "nodal_leastrequest": "nlr",
    "minimize_diff": "md",
    "leastrequest": "lr",
    "weighted_random": "wr",
    "locality_aware_weighted_random": "lawr",
    "weighted_roundrobin": "wrr",
    "tmp_nodal_leastrequest": "tnlr",
    "leastrequest_plus": "lr++",
}
    
def get_svc_to_nodes(nodes_to_svc: List[List[int]]) -> Dict[str, List[str]]:
    # a 2d array of node_ids to service_ids
    # e.g. [[0, 1], [2, 1], [2, 0]]
    
    svc_to_nodes = defaultdict(list)
    
    for node_id, svc_ids in enumerate(nodes_to_svc):
        node_name = f"node{node_id}"
        for svc_id in svc_ids:
            svc_name = f"svc{svc_id}"
            svc_to_nodes[svc_name].append(node_name)
            
    return dict(svc_to_nodes)

def run_cc(q, variation, enforcement):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../centralcontroller/centralcontroller -logfile {curr_dir}/{LOG_FOLDER}/{variation}_cc.log -enforcement={enforcement} -d={(DURATION + ADDITIONAL_TIME_FOR_CC_TO_RUN + DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC) * 1000}"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put(("cc", start_time, end_time, 
           f"CC finished with exit status: {exit_status}"))
    
def parse_svc_load(svc_load: float) -> Tuple[int, float]:
    """
    we have load in percentage of cores in unit time
    output corresponding:
    - consumption per request (coreMs)
    - request_interval_ms (ms)
    
    unit test:
        print(parse_svc_load(0))
        print(parse_svc_load(3.34))
        print(parse_svc_load(50))
        print(parse_svc_load(82))
        print(parse_svc_load(100))
        print(parse_svc_load(300))
        print(parse_svc_load(600))
        print(parse_svc_load(10000))
        print(parse_svc_load(10002))
    prints:
        (0, 30.0)
        (1, 30.0)
        (15, 30.0)
        (24, 30.0)
        (30, 30.0)
        (30, 10.0)
        (30, 5.0)
        (30, 0.3)
        (30, 0.2999400119976005)
        
    flaw in algorithm: if svc_load <= 3.33%, the svc CPU utilization will be 0%
    flaw in algorithm: if svc_load == 82%,
        the svc CPU utilization will be 80% (if svc_load is < 100%, utilization is rounded)
    """
    
    # convert load from percentage of cores in unit time to number of cores per unit time
    load = svc_load / 100.0
    
    # default duration of each request (only when load > 1 core per unit time)
    default_duration_ms = 30.0
    
    # max cpu cores per unit time that a request can consume
    max_cpu_per_time = 1
    
    if load <= 1.0:
        # consumption = (load/1) * default_duration
        consumption = (load / max_cpu_per_time) * default_duration_ms
        req_interval_ms = default_duration_ms
    else:
        # need more requests in parallel
        consumption = max_cpu_per_time * default_duration_ms
        req_interval_ms = default_duration_ms / (load / max_cpu_per_time)
    
    return int(consumption), float(req_interval_ms)

def run_hit(q, variation, svc_loads, arr_distr, proc_distr):

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    
    configs = []
    
    for svc_num, svc_load in enumerate(svc_loads):
        
        svc_name = f"svc{svc_num}"
        
        cpu_consumption, req_interval_ms = parse_svc_load(svc_load)
        
        assert(req_interval_ms > 0)
        
        gateway_ip = GATEWAY_IPs[svc_name]
        
        if proc_distr == "none" or proc_distr == "uniform":
            url = f"http://{gateway_ip}/?cpu_coreMs={cpu_consumption}"
        else:
            url = f"http://{gateway_ip}/?cpu_coreMs=EXP<{cpu_consumption}>"
        
        configs.append({
            "endpoints": [
                {
                    "url": url,
                    "node": 1,
                    "app": svc_name,
                    "headers": "{\"Host\":\"" + svc_name + ".mplb.com\"}"
                }
            ],
            "reqIntervalMs": req_interval_ms,
            "durationMs": DURATION * 1000,
            "logFileName": f"{curr_dir}/{LOG_FOLDER}/{variation}_{svc_name}_hit.log",
            "stallTimeMs": 0
        })
        
    with open(f"{curr_dir}/{LOG_FOLDER}/{variation}_hit.json", "w") as f:
        f.write(json.dumps(configs))
        
    cmd = f"../hit/hit -distr {arr_distr} -f {curr_dir}/{LOG_FOLDER}/{variation}_hit.json"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put((f"hit", start_time, end_time, 
           f"hit for apps{svc_loads} finished with exit status: {exit_status}"))

def run_exp(variation, svc_loads, enforcement, arr_distr, proc_distr, append_to_times=None):
    
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {svc_loads} RPS")
    
    queues = []
        
    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    queues.append(q)
    time.sleep(DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC)    
    
    # run the app workloads through a single hit
    q = Queue()
    Thread(target=run_hit, args=(q, variation, svc_loads, arr_distr, proc_distr)).start()
    
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
    
    print(f"Completed experiment with {variation} at {svc_loads} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    
        
    
def run_exp_for_cluster_state(
    state_id: int, svc_loads: List[int], svc_to_nodes: Dict[str, List[str]], pod_names: List[str]):
    
    print(f"Running experiment w/ state {state_id} i.e. loads={svc_loads} & podnames={pod_names}")
    
    for lb in ["leastrequest", "leastrequest_plus", "nodal_leastrequest", "minimize_diff"]: # [leastrequest_plus|tmp_nodal_leastrequest|nodal_leastrequest|minimize_diff|locality_aware_weighted_random|leastrequest|weighted_random|weighted_roundrobin|weighted_leastrequest]

        print(f"Running experiment w/ state {state_id} && lb {LB_NAME[lb]} i.e. loads={svc_loads} & podnames={pod_names}")

        # build new wasm
        print(f"Building wasm plugin for {lb}...")
        modify_wasm_plugin(lb)
        
        print(f"Setting up the topology...")
        done = setup_clutser_with_new_pods(pod_names)
        if not done:
            print("!!!!!!!\n!!!!!!! Failed to set up the cluster with new pods.\n\n\n\n")
            continue
    
        for iteration in [1]:
        
            for distr in ["none"]:
                
                for proc_distr in ["none"]:
                                                    
                    print(f"Starting iteration {iteration} for run_id {state_id}...")
                    
                    print(f"Running experiment [iteration {iteration}] w/ state {state_id} && lb {LB_NAME[lb]} && distr {(distr, proc_distr)} i.e. loads={svc_loads} & podnames={pod_names}")
                    
                    intended_topology = svc_to_nodes
                    print(intended_topology)
                    
                    to_append = get_topology_str(intended_topology)
                    print(to_append)
                    
                    run_exp(f"{distr}_{proc_distr}_mplb_{LB_NAME[lb]}_{state_id}_{iteration}", svc_loads, "LB", distr, proc_distr, append_to_times=to_append)

def test():
    print(parse_svc_load(0))
    print(parse_svc_load(3.34))
    print(parse_svc_load(50))
    print(parse_svc_load(100))
    print(parse_svc_load(300))
    print(parse_svc_load(600))
    print(parse_svc_load(10000))
    print(parse_svc_load(10002))

def prep_for_exps():
    
    # create the logs directory
    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)
    
    build_central_controller()

if __name__ == "__main__":
    
    prep_for_exps()
    
    state_id = 0
    svc_loads = [300, 200, 100]
    svc_to_nodes = {
        "svc0": ["node0", "node1"],
        "svc1": ["node1", "node2"],
        "svc2": ["node0"],
    }
    pod_names = [
        "svc0-node0-0",
        "svc0-node1-0",
        "svc1-node1-0",
        "svc1-node2-0",
        "svc2-node0-0",
    ]
    
    run_exp_for_cluster_state(state_id, svc_loads, svc_to_nodes, pod_names)
    