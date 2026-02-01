from random import random
from typing import List, Dict, Tuple
from collections import defaultdict
from kubernetes import client, config
from queue import Queue
from threading import Thread
import os
import time
import json
import sys

from set_topology import get_gateway_ips, setup_clutser_with_new_pods, get_curr_gateway_ips, get_gateway_ip

# Everything in seconds:
DURATION = 60
DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC = 5
ADDITIONAL_TIME_FOR_CC_TO_RUN = 10
SLEEP_TIME_AFTER_EACH_RUN = 10

CORES_PER_NODE = 8
SCALE_FACTOR = 0.8
REQUEST_CPU_CONSUMPTION_MS = 80.0 # each request consumes 80 coreMs by default

LOG_FOLDER = "logs/online_sweep_Feb1"

# GATEWAY_IPs = get_curr_gateway_ips()

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
    "only_nodal_leastrequest": "onlr",
    "leastrequest_plus_rl": "lr++_rl",
    "leastrequest_rl": "lr_rl",
    "leastrequest_plus_rlpb": "lr++_rlpb",
    "nodal_leastrequest_rlpb": "nlr_rlpb",
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

def run_cc(q, variation, enforcement, duration):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../centralcontroller/centralcontroller -logfile {curr_dir}/{LOG_FOLDER}/{variation}_cc.log -enforcement={enforcement} -d={(duration + ADDITIONAL_TIME_FOR_CC_TO_RUN + DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC) * 1000}"
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
    default_duration_ms = REQUEST_CPU_CONSUMPTION_MS
    
    # max cpu cores per unit time that a request can consume
    max_cpu_per_time = 1
    
    if load == 0:
        return 0, default_duration_ms * DURATION + 10
    
    # if load <= 1.0:
    #     # consumption = (load/1) * default_duration
    #     consumption = (load / max_cpu_per_time) * default_duration_ms
    #     req_interval_ms = default_duration_ms
    # else:
    # need more requests in parallel
    consumption = max_cpu_per_time * default_duration_ms
    req_interval_ms = default_duration_ms / (load / max_cpu_per_time)
    
    return int(consumption), float(req_interval_ms)

def get_request_interval_updates(spike_result: Dict, load_scale_factor: float, lb_name: str) -> Tuple[int, List[Dict]]:
    
    """
    Returns the total duration and a list of request interval updates based on the intended spike.
    
    After each 10 seconds, the svc_load is increased by 10 until we reach > 15 + max of the svc_load. The request interval is
    recalculated accordingly.
    """
    """
    like the following:
    [{
                        "atMs": 30000.0,
                    "reqIntervalMs": req_interval_ms
                    
                    }, ...]
    """
    
    max_load = spike_result["seed_local"] if "lr++" in lb_name else spike_result["max"]
    base_load = spike_result["base"] * load_scale_factor
    
    request_interval_updates = []
    
    curr_load = base_load
    
    _cpu_consumption, _ = parse_svc_load(curr_load * CORES_PER_NODE)
    
    additional_time = 25 # if "lr++" in lb_name else 15
    
    while curr_load <= max_load + 25:
        
        cpu_consumption, req_interval_ms = parse_svc_load(curr_load * CORES_PER_NODE)
        assert(_cpu_consumption == cpu_consumption)
        
        time_at_ms = (len(request_interval_updates) + 1) * 10000
        
        request_interval_updates.append({
            "atMs": time_at_ms,
            "reqIntervalMs": req_interval_ms,
            # "currentLoad": curr_load
        })
        
        curr_load += 10
    
    duration = 10 + len(request_interval_updates) * 10
    
    return duration, request_interval_updates

def run_hit(q, variation, svc_loads, arr_distr, proc_distr, duration, request_interval_updates, spiking_svc):

    curr_dir = os.path.dirname(os.path.abspath(__file__))
    
    configs = []
    
    for svc_num, svc_load in enumerate(svc_loads):
        
        svc_name = f"svc{svc_num}"
        
        cpu_consumption, req_interval_ms = parse_svc_load(svc_load)
        
        assert(req_interval_ms > 0)
        
        # gateway_ip = GATEWAY_IPs[svc_name]
        gateway_ips = get_gateway_ips(svc_name, use_pod_ip=True)
        
        endpoints = []
        for gateway_ip in gateway_ips:
            if proc_distr == "none" or proc_distr == "uniform":
                url = f"http://{gateway_ip}/?cpu_coreMs={cpu_consumption}"
            else:
                url = f"http://{gateway_ip}/?cpu_coreMs=EXP<{cpu_consumption}>"
            endpoints.append({
                    "url": url,
                    "node": 1,
                    "app": int(svc_name[3:]),
                    "headers": "{\"Host\":\"" + svc_name + ".mplb.com\"}"
                })
        
        if svc_name == spiking_svc:
            print(f"+++++++++ Spiking service: {svc_name} ++++++++++")
        
        configs.append({
            "endpoints": endpoints,
            "reqIntervalMs": req_interval_ms,
            "durationMs": duration * 1000,
            "logFileName": f"{curr_dir}/{LOG_FOLDER}/{variation}_{svc_name}_hit.log",
            "stallTimeMs": 0,
            "requestIntervalUpdates": request_interval_updates if svc_name == spiking_svc else []
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

def run_exp(variation, svc_loads, load_scale_factor, enforcement, arr_distr, proc_distr, spike_results, spiking_svc, lb_name, append_to_times=None):
    
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {svc_loads} RPS")
    
    if spike_results:
        duration, request_interval_updates = get_request_interval_updates(spike_results[spiking_svc], load_scale_factor, lb_name)
    else:
        duration = DURATION
        request_interval_updates = []
    
    queues = []
        
    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement, duration)).start()
    queues.append(q)
    time.sleep(DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC)    
    
    # run the app workloads through a single hit
    q = Queue()
    Thread(target=run_hit, args=(q, variation, svc_loads, arr_distr, proc_distr, duration, request_interval_updates, spiking_svc)).start()
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
    
    print(f"Completed experiment with {variation} at {svc_loads} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    
    print(f"Sleeping for {SLEEP_TIME_AFTER_EACH_RUN} seconds after the run...")
    time.sleep(SLEEP_TIME_AFTER_EACH_RUN)
    
def set_correct_objective(lb):
    if lb == "minimize_diff":
        os.system("curl http://localhost:4876/complicate_objective")
    else:
        os.system("curl http://localhost:4876/simplify_objective")
    
def run_spike_exp_for_cluster_state(
    state_id: int,
    svc_loads: List[int],
    svc_to_nodes: Dict[str, List[str]],
    pod_names: List[str],
    spike_results: Dict = None,
    spiking_svc: str = "svc0",
    lbs: List[str] = [
        "leastrequest",
        "leastrequest_plus",
        "only_nodal_leastrequest",
        "leastrequest_rl",
        "leastrequest_plus_rl",
        "nodal_leastrequest",
        "minimize_diff"]):
    
    time_started = time.time()
    print(f"Running experiment w/ state {state_id} i.e. loads={svc_loads} & podnames={pod_names} at {time.ctime(time_started)}")
    
    for lb in lbs: # [leastrequest|leastrequest_plus|nodal_leastrequest|only_nodal_leastrequest|minimize_diff]
        
        for iteration in [700, 701, 702]:
        
            print(f"Running experiment w/ state {state_id} && lb {LB_NAME[lb]} [{spiking_svc}] [{iteration}] i.e. loads={svc_loads} & podnames={pod_names}")

            if "-b" not in sys.argv:

                # build new wasm
                print(f"Building wasm plugin for {lb}...")
                modify_wasm_plugin(lb)
                
                print(f"Setting up the topology...")
                done = setup_clutser_with_new_pods(pod_names)
                if not done:
                    print("!!!!!!!\n!!!!!!! Failed to set up the cluster with new pods.\n\n\n\n")
                    continue
                
            else:
                print("Skipping building wasm plugin and setting up topology as per command line argument '-b'...")
            
            if "-t" in sys.argv:
                print("Only setting up topology as per command line argument '-t'...")
                continue
            
            print("Seting the correct objective in the optimizer...")
            set_correct_objective(lb)
        
            for distr in ["exponential"]: #, "exponential"]:
                
                proc_distr = distr
                
                for load_scale_factor in [SCALE_FACTOR]:
                    
                    scaled_svc_loads = [int(svc_load * load_scale_factor) for svc_load in svc_loads]
                                                    
                    print(f"Starting iteration {iteration} for run_id {state_id}...")
                    
                    print(f"Running experiment [iteration {iteration}] w/ state {state_id} && lb {LB_NAME[lb]} && distr {(distr, proc_distr)} i.e. loads={scaled_svc_loads} & podnames={pod_names}")
                    
                    intended_topology = svc_to_nodes
                    print(intended_topology)
                    
                    to_append = get_topology_str(intended_topology)
                    print(to_append)
                    
                    run_exp(f"{distr}_{proc_distr}_mplb_{LB_NAME[lb]}_{state_id}_{iteration}_{load_scale_factor}_spike_{spiking_svc}", scaled_svc_loads, load_scale_factor, "LB", distr, proc_distr, spike_results, spiking_svc, LB_NAME[lb], append_to_times=to_append)

        message = f"Completed #{state_id} [{LB_NAME[lb]} {spiking_svc}]"
        os.system(f'curl -d "{message}" ntfy.sh/mplb')
    
    # message = f"Completed #{state_id}"
    # os.system(f'curl -d "{message}" ntfy.sh/mplb')
    
    time_taken = time.time() - time_started
    print(f"Time taken for experiment: {time_taken} seconds")

def run_spike_exp_for_cluster_state_id(state_id: int,
                                 spiking_svc: str,
                                 lbs: List[str] = ["leastrequest_plus",
                                                   "leastrequest_plus_rl",
                                                   "nodal_leastrequest",
                                                   "only_nodal_leastrequest",
                                                   "minimize_diff"]):
    data = read_json_line("../offline-sweep/logs/offline_sweep_spike_Jan4_lb_0.00_ub_1.60_topo_sampling_2.log", state_id)
    
    svc_loads = data["State"]["SvcLoads"]
    svc_loads = [int(svc_load*CORES_PER_NODE) for svc_load in svc_loads]

    svc_to_nodes = {}
    for node_id, n_svcs in enumerate(data["State"]["NodesToSvc"]):
        for svc_id, n_svc in enumerate(n_svcs):
            for i in range(n_svc):
                svc_name = f"svc{svc_id}"
                node_name = f"node{node_id}"
                if svc_name not in svc_to_nodes:
                    svc_to_nodes[svc_name] = []
                svc_to_nodes[svc_name].append(node_name)

    pod_names = [worker["name"] for worker in data["Workers"]]
    
    run_spike_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        spike_results=data["SpikeResultsGlobal"],
        spiking_svc=spiking_svc,
        lbs=lbs)
    
def test():
    # print(parse_svc_load(0))
    # print(parse_svc_load(3.34))
    # print(parse_svc_load(50))
    # print(parse_svc_load(100))
    # print(parse_svc_load(300))
    # print(parse_svc_load(600))
    # print(parse_svc_load(10000))
    # print(parse_svc_load(10002))
    # print(parse_svc_load(300*0.9))
    # print(parse_svc_load(200*0.9))
    # print(parse_svc_load(100*0.9))
    
    state_id = 71296
    data = read_json_line("../offline-sweep/logs/offline_sweep_Apr3_1350.log", state_id+1)
    
    svc_loads = data["State"]["SvcLoads"]
    svc_loads = [int(svc_load*2) for svc_load in svc_loads]

    svc_to_nodes = {}
    for node_id, n_svcs in enumerate(data["State"]["NodesToSvc"]):
        for svc_id, n_svc in enumerate(n_svcs):
            for i in range(n_svc):
                svc_name = f"svc{svc_id}"
                node_name = f"node{node_id}"
                if svc_name not in svc_to_nodes:
                    svc_to_nodes[svc_name] = []
                svc_to_nodes[svc_name].append(node_name)

    pod_names = [worker["name"] for worker in data["Workers"]]
    
    print(f"svc_loads: {svc_loads}")
    print(f"svc_to_nodes: {svc_to_nodes}")
    print(f"pod_names: {pod_names}")

def prep_for_exps():
    
    # create the logs directory
    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)
    
    build_central_controller()

def read_json_line(filename, line_number):
    """
    Reads a specific line from a file and parses it as JSON.

    Args:
        filename (str): Path to the file.
        line_number (int): The 1-based line number to read.

    Returns:
        dict: The parsed JSON object from the specified line.

    Raises:
        ValueError: If the line does not contain valid JSON.
        IndexError: If the line number is out of range.
    """
    with open(filename, 'r') as file:
        for i, line in enumerate(file, start=0):
            if i == line_number:
                try:
                    return json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Line {line_number} is not valid JSON: {e}")
        raise IndexError(f"Line {line_number} not found in file.")

def main_exp_state_2():
    
    # print(parse_svc_load(300*0.7))
    # print(parse_svc_load(200*0.7))
    # return
    
    prep_for_exps()
    
    state_id = 2
    svc_loads = [800] * 15  # total 15 services
    svc_to_nodes = {
        "svc0": ["node0"],
        "svc1": ["node0", "node1"],
        "svc2": ["node0", "node2"],
        "svc3": ["node0", "node3"],
        "svc4": ["node0", "node4"],
        "svc5": ["node0", "node5"],
        "svc6": ["node0", "node6"],
        "svc7": ["node0", "node7"],
        "svc8": ["node0", "node8"],
        "svc9": ["node0", "node9"],
        "svc10": ["node0", "node10"],
        "svc11": ["node0", "node11"],
        "svc12": ["node0", "node12"],
        "svc13": ["node0", "node13"],
        "svc14": ["node0", "node14"],
    }
    pod_names = [
        "svc0-node0-0",
        "svc1-node0-0",
        "svc1-node1-0",
        "svc2-node0-0",
        "svc2-node2-0",
        "svc3-node0-0",
        "svc3-node3-0",
        "svc4-node0-0",
        "svc4-node4-0",
        "svc5-node0-0",
        "svc5-node5-0",
        "svc6-node0-0",
        "svc6-node6-0",
        "svc7-node0-0",
        "svc7-node7-0",
        "svc8-node0-0",
        "svc8-node8-0",
        "svc9-node0-0",
        "svc9-node9-0",
        "svc10-node0-0",
        "svc10-node10-0",
        "svc11-node0-0",
        "svc11-node11-0",
        "svc12-node0-0",
        "svc12-node12-0",
        "svc13-node0-0",
        "svc13-node13-0",
        "svc14-node0-0",
        "svc14-node14-0",
    ]
    
    # svc_to_nodes = {
    #     "svc0": ["node0", "node1"],
    #     "svc1": ["node1"],
    #     "svc2": ["node2"],
    # }
    # pod_names = [
    #     "svc0-node0-0",
    #     "svc0-node1-0",
    #     "svc1-node1-0",
    #     "svc2-node2-0",
    # ]
    
    run_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=[
            "nodal_leastrequest_rlpb",
            "nodal_leastrequest",
            "only_nodal_leastrequest",
            "minimize_diff",
            "leastrequest_plus_rlpb",
            "leastrequest_plus",
            # "leastrequest_plus_rl",
        ])

    # state_id = 2
    # svc_loads = [300, 200, 0]
    
    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "leastrequest_plus",
    #         # "leastrequest_plus_rl",
    #         "leastrequest_plus_rlpb",
    #         "only_nodal_leastrequest",
    #         "nodal_leastrequest_rlpb",
    #         "nodal_leastrequest",
    #         "minimize_diff",
    #     ])

    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "nodal_leastrequest",
    #         "leastrequest_plus_rl",
    #         "minimize_diff"
    #     ])

def main_exp_state_3():
    
    # print(parse_svc_load(300*0.7))
    # print(parse_svc_load(200*0.7))
    # return
    
    prep_for_exps()
    
    state_id = 3
    svc_loads = [800] * 15 # total 15 services
    svc_to_nodes = {
        "svc0": ["node0"],
        "svc1": ["node0", "node1"],
        "svc2": ["node1", "node2"],
        "svc3": ["node2", "node3"],
        "svc4": ["node3", "node4"],
        "svc5": ["node4", "node5"],
        "svc6": ["node5", "node6"],
        "svc7": ["node6", "node7"],
        "svc8": ["node7", "node8"],
        "svc9": ["node8", "node9"],
        "svc10": ["node9", "node10"],
        "svc11": ["node10", "node11"],
        "svc12": ["node11", "node12"],
        "svc13": ["node12", "node13"],
        "svc14": ["node13", "node14"],
    }
    pod_names = [
        "svc0-node0-0",
        
        "svc1-node0-0",
        "svc1-node1-0",
        
        "svc2-node1-0",
        "svc2-node2-0",
        
        "svc3-node2-0",
        "svc3-node3-0",
        
        "svc4-node3-0",
        "svc4-node4-0",
        
        "svc5-node4-0",
        "svc5-node5-0",
        
        "svc6-node5-0",
        "svc6-node6-0",
        
        "svc7-node6-0",
        "svc7-node7-0",
        
        "svc8-node7-0",
        "svc8-node8-0",
        
        "svc9-node8-0",
        "svc9-node9-0",
        
        "svc10-node9-0",
        "svc10-node10-0",
        
        "svc11-node10-0",
        "svc11-node11-0",
        
        "svc12-node11-0",
        "svc12-node12-0",
        
        "svc13-node12-0",
        "svc13-node13-0",
        
        "svc14-node13-0",
        "svc14-node14-0",
    ]
    
    # svc_to_nodes = {
    #     "svc0": ["node0", "node1"],
    #     "svc1": ["node1"],
    #     "svc2": ["node2"],
    # }
    # pod_names = [
    #     "svc0-node0-0",
    #     "svc0-node1-0",
    #     "svc1-node1-0",
    #     "svc2-node2-0",
    # ]
    
    run_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=[
            "nodal_leastrequest_rlpb",
            "nodal_leastrequest",
            "only_nodal_leastrequest",
            "minimize_diff",
            "leastrequest_plus_rlpb",
            "leastrequest_plus",
            # "leastrequest_plus_rl",
        ])

    # state_id = 2
    # svc_loads = [300, 200, 0]
    
    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "leastrequest_plus",
    #         # "leastrequest_plus_rl",
    #         "leastrequest_plus_rlpb",
    #         "only_nodal_leastrequest",
    #         "nodal_leastrequest_rlpb",
    #         "nodal_leastrequest",
    #         "minimize_diff",
    #     ])

    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "nodal_leastrequest",
    #         "leastrequest_plus_rl",
    #         "minimize_diff"
    #     ])

def main_exp_state_4():
    
    # print(parse_svc_load(300*0.7))
    # print(parse_svc_load(200*0.7))
    # return
    
    prep_for_exps()
    
    # this exp is to determine the allowed rps we should have for each svc
    # we will have svc0 with 200% util and the rest with 0% util
    # check latency of svc0. This will be our target rps
    
    state_id = 4
    svc_loads = [800] + ([0] * 14) # total 15 services
    svc_to_nodes = {
        "svc0": ["node0"],
        "svc1": ["node0", "node1"],
        "svc2": ["node1", "node2"],
        "svc3": ["node2", "node3"],
        "svc4": ["node3", "node4"],
        "svc5": ["node4", "node5"],
        "svc6": ["node5", "node6"],
        "svc7": ["node6", "node7"],
        "svc8": ["node7", "node8"],
        "svc9": ["node8", "node9"],
        "svc10": ["node9", "node10"],
        "svc11": ["node10", "node11"],
        "svc12": ["node11", "node12"],
        "svc13": ["node12", "node13"],
        "svc14": ["node13", "node14"],
    } 
    pod_names = [
        "svc0-node0-0",
        
        "svc1-node0-0",
        "svc1-node1-0",
        
        "svc2-node1-0",
        "svc2-node2-0",
        
        "svc3-node2-0",
        "svc3-node3-0",
        
        "svc4-node3-0",
        "svc4-node4-0",
        
        "svc5-node4-0",
        "svc5-node5-0",
        
        "svc6-node5-0",
        "svc6-node6-0",
        
        "svc7-node6-0",
        "svc7-node7-0",
        
        "svc8-node7-0",
        "svc8-node8-0",
        
        "svc9-node8-0",
        "svc9-node9-0",
        
        "svc10-node9-0",
        "svc10-node10-0",
        
        "svc11-node10-0",
        "svc11-node11-0",
        
        "svc12-node11-0",
        "svc12-node12-0",
        
        "svc13-node12-0",
        "svc13-node13-0",
        
        "svc14-node13-0",
        "svc14-node14-0",
    ]
    
    # svc_to_nodes = {
    #     "svc0": ["node0", "node1"],
    #     "svc1": ["node1"],
    #     "svc2": ["node2"],
    # }
    # pod_names = [
    #     "svc0-node0-0",
    #     "svc0-node1-0",
    #     "svc1-node1-0",
    #     "svc2-node2-0",
    # ]
    
    run_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=[
            # "only_nodal_leastrequest",
            # "nodal_leastrequest",
            # "leastrequest_plus_rlpb",
            # "nodal_leastrequest_rlpb",
            # "minimize_diff",
            "leastrequest_plus",
            # "leastrequest_plus_rl",
        ])
  
    # state_id = 2
    # svc_loads = [300, 200, 0]
    
    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "leastrequest_plus",
    #         # "leastrequest_plus_rl",
    #         "leastrequest_plus_rlpb",
    #         "only_nodal_leastrequest",
    #         "nodal_leastrequest_rlpb",
    #         "nodal_leastrequest",
    #         "minimize_diff",
    #     ])

    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "nodal_leastrequest",
    #         "leastrequest_plus_rl",
    #         "minimize_diff"
    #     ])

def main_exp_state_5():
    
    # print(parse_svc_load(300*0.7))
    # print(parse_svc_load(200*0.7))
    # return
    
    prep_for_exps()
    
    state_id = 5
    svc_loads = [800] + ([800*(1 + 1/15.0)] * 14) # total 15 services
    svc_to_nodes = {
        "svc0": ["node0"],
        "svc1": ["node0", "node1"],
        "svc2": ["node0", "node2"],
        "svc3": ["node0", "node3"],
        "svc4": ["node0", "node4"],
        "svc5": ["node0", "node5"],
        "svc6": ["node0", "node6"],
        "svc7": ["node0", "node7"],
        "svc8": ["node0", "node8"],
        "svc9": ["node0", "node9"],
        "svc10": ["node0", "node10"],
        "svc11": ["node0", "node11"],
        "svc12": ["node0", "node12"],
        "svc13": ["node0", "node13"],
        "svc14": ["node0", "node14"],
    }
    pod_names = [
        "svc0-node0-0",
        "svc1-node0-0",
        "svc1-node1-0",
        "svc2-node0-0",
        "svc2-node2-0",
        "svc3-node0-0",
        "svc3-node3-0",
        "svc4-node0-0",
        "svc4-node4-0",
        "svc5-node0-0",
        "svc5-node5-0",
        "svc6-node0-0",
        "svc6-node6-0",
        "svc7-node0-0",
        "svc7-node7-0",
        "svc8-node0-0",
        "svc8-node8-0",
        "svc9-node0-0",
        "svc9-node9-0",
        "svc10-node0-0",
        "svc10-node10-0",
        "svc11-node0-0",
        "svc11-node11-0",
        "svc12-node0-0",
        "svc12-node12-0",
        "svc13-node0-0",
        "svc13-node13-0",
        "svc14-node0-0",
        "svc14-node14-0",
    ]
    
    # svc_to_nodes = {
    #     "svc0": ["node0", "node1"],
    #     "svc1": ["node1"],
    #     "svc2": ["node2"],
    # }
    # pod_names = [
    #     "svc0-node0-0",
    #     "svc0-node1-0",
    #     "svc1-node1-0",
    #     "svc2-node2-0",
    # ]
    
    run_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=[
            "leastrequest_plus_rlpb",
            "nodal_leastrequest_rlpb",
            "nodal_leastrequest",
            # "only_nodal_leastrequest",
            # "leastrequest_plus",
            "minimize_diff",
            # "leastrequest_plus_rl",
        ])

    # state_id = 2
    # svc_loads = [300, 200, 0]
    
    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "leastrequest_plus",
    #         # "leastrequest_plus_rl",
    #         "leastrequest_plus_rlpb",
    #         "only_nodal_leastrequest",
    #         "nodal_leastrequest_rlpb",
    #         "nodal_leastrequest",
    #         "minimize_diff",
    #     ])

    # run_exp_for_cluster_state(
    #     state_id,
    #     svc_loads,
    #     svc_to_nodes,
    #     pod_names,
    #     lbs=[
    #         "nodal_leastrequest",
    #         "leastrequest_plus_rl",
    #         "minimize_diff"
    #     ])


def main():
    
    prep_for_exps()
    
    for random_state, spiking_svc in [(652,   'svc4')]:
        run_spike_exp_for_cluster_state_id(random_state, spiking_svc, lbs=[
            "nodal_leastrequest",
            # "leastrequest_plus_rlpb",
        ])
        
    os.system("curl -d 'EXPERIMENT FINITO' ntfy.sh/mplb")
    return
    
    # # # test 10 to 15 states
    # start = 298
    # random_states = list(range(start+25, start+50))
    # all_states = random_states
    # all_states = [327, 334, 338]
    # all_states = list(range(1000))
    # random_states = random.sample(range(1000), k=25)
    # print(all_states)
    
    _random_states = [
        (935,   'svc10'),
        (124,   'svc14'),
        (525,   'svc1'),
        (105,   'svc9'),
        (170,   'svc2'),
        # (166,   'svc11'),
        (446,   'svc6'),
        (279,   'svc6'),
        (273,   'svc8'),
        (412,   'svc10'),
        (214,   'svc1'),
        (145,   'svc11'),
        (111,   'svc3'),
        (775,   'svc0'),
        (307,   'svc13'),
        (869,   'svc1'),
        (878,   'svc8'),
        (304,   'svc8'),
        # (63,    'svc6'),
        (464,   'svc1'),
        (286,   'svc1'),
        (976,   'svc7'),
        (811,   'svc9'),
        (98,    'svc3'),
        # (652,   'svc4')
    ]
    
    random_states = [
        (9, 'svc3'),
        (658, 'svc3'),
        (0, 'svc1'),
        (610, 'svc11'),
        (241, 'svc8'),
        (301, 'svc9'),
        (176, 'svc2'),
        (703, 'svc8'),
        (522, 'svc7'),
        # (960, 'svc5'),
        # (186, 'svc11'),
        (608, 'svc3'),
        (9, 'svc5'),
        (620, 'svc12'),
        # (49, 'svc6'),
        # (314, 'svc3'),
        (431, 'svc12'),
        # (223, 'svc7'),
        (673, 'svc8'),
        (468, 'svc4'),
        (569, 'svc3'),
        (911, 'svc3'),
        (967, 'svc2'),
        (650, 'svc0'),
        (749, 'svc9')
    ]
    
    problematic_states = [
        (166,   'svc11'),
        (63,    'svc6'),
        (652,   'svc4'),
        (960, 'svc5'),
        (186, 'svc11'),
        (49, 'svc6'),
        (314, 'svc3'),
        (223, 'svc7'),
    ]
    
    for random_state, spiking_svc in problematic_states:
        run_spike_exp_for_cluster_state_id(random_state, spiking_svc, lbs=[
            "nodal_leastrequest",
            "leastrequest_plus_rlpb",
        ])
    
    os.system("curl -d 'EXPERIMENT ALMOST FINITO [1]' ntfy.sh/mplb")
    
    all_states = _random_states + random_states
    
    for random_state, spiking_svc in all_states:
        run_spike_exp_for_cluster_state_id(random_state, spiking_svc, lbs=[
            "nodal_leastrequest",
            "leastrequest_plus_rlpb",
        ])
        
    os.system("curl -d 'EXPERIMENT ALMOST FINITO [2]' ntfy.sh/mplb")
    
    all_states = problematic_states + _random_states + random_states
        
    for random_state, spiking_svc in all_states:
        run_spike_exp_for_cluster_state_id(random_state, spiking_svc, lbs=[
            "nodal_leastrequest_rlpb",
            "minimize_diff",
        ])

    os.system("curl -d 'EXPERIMENT FINITO' ntfy.sh/mplb")
    

if __name__ == "__main__":
    start_time = time.time()
    
    # main_exp_state_5()
    main()
    
    # print(get_request_interval_updates({"base": 50, "max": 150}, 0.8))
    
    time_taken = time.time() - start_time
    print(f"Total time taken: {time_taken} seconds")
    
    # a, b = parse_svc_load(47.529296875 * CORES_PER_NODE)
    # print(a, 1000.0/b)
    # a, b = parse_svc_load(100.73319911956787 * CORES_PER_NODE)
    # print(a, 1000.0/b)
    