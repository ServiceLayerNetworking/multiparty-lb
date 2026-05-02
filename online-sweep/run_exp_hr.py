from typing import List, Dict, Tuple
from collections import defaultdict
from kubernetes import client, config
from queue import Queue
from threading import Thread
import os
import time
import json
import sys

from set_topology import setup_clutser_with_new_pods, get_curr_gateway_ips, get_gateway_ip

# Everything in seconds:
DURATION = 60
DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC = 5
ADDITIONAL_TIME_FOR_CC_TO_RUN = 10
SLEEP_TIME_AFTER_EACH_RUN = 20

# HotelReservation traffic mix (from online-sweep/setup.txt)
SEARCH_RATIO = 0.6
RECOMMEND_RATIO = 0.39
USER_RATIO = 0.005
RESERVE_RATIO = 0.005

# Optional: override per-workflow request rates directly (RPS).
# If any of these are not None, they take precedence over total_rps+ratios.
# NOTE: These are workflow endpoints on the frontend (not the internal microservices).
SEARCH_RPS: int | None = None
RECOMMEND_RPS: int | None = None
USER_RPS: int | None = None
RESERVE_RPS: int | None = None

# Frontend service info
FRONTEND_SVC_NAME = "frontend"          # used for Host header / logical service
# NOTE: frontend service port is 5000, but we do NOT send traffic directly to the frontend ClusterIP.
# We send traffic to an Istio ingress gateway (port 8080 in this testbed) and rely on Host routing.
FRONTEND_PORT = 5000                    # kept for reference; not used for gateway routing
# get_gateway_ip() in set_topology.py expects a svc-name that maps to an ingress service named
# istio-ingressgateway-<name> in the istio-ingress namespace. There is no istio-ingressgateway-frontend
# in your cluster, but there is istio-ingressgateway-svc0/svc1/svc2.
# We route to frontend via one of those gateways and rely on Host: frontend for the VirtualService match.
FRONTEND_GATEWAY_SVC_NAME = "svc0"
# If your traffic goes through an Istio VirtualService that matches host "frontend",
# setting Host is usually safest. hit will set req.Host when this key is present.
FRONTEND_HOST_HEADER = "frontend"

# Query params (matching examples in setup.txt)
HR_LAT = "38.0235"
HR_LON = "-122.095"
HR_IN_DATE = "2015-04-10"
HR_OUT_DATE = "2015-04-12"
HR_USERNAME = "Cornell_1"
HR_PASSWORD = "1111111111"
HR_HOTEL_ID = "5"
HR_CUSTOMER_NAME = "Cornell_1"
HR_NUMBER_ROOMS = "1"

LOG_FOLDER = "logs/debug_HR_May1"

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
    """Deprecated for HotelReservation workload; kept to avoid breaking other imports."""
    load = svc_load / 100.0
    default_duration_ms = 80.0
    max_cpu_per_time = 1
    if load == 0:
        return 0, default_duration_ms * DURATION + 10
    consumption = max_cpu_per_time * default_duration_ms
    req_interval_ms = default_duration_ms / (load / max_cpu_per_time)
    return int(consumption), float(req_interval_ms)


def _req_interval_ms_from_rps(rps: float) -> float:
    if rps <= 0:
        # a large interval effectively means no requests
        return float((DURATION + 1) * 1000)
    return 1000.0 / float(rps)


def _split_total_rps(total_rps: int) -> Dict[str, int]:
    """Split total RPS into 4 workflows. Keeps the sum equal to total_rps."""
    if total_rps < 0:
        raise ValueError("total_rps must be >= 0")

    # floor allocations
    search = int(total_rps * SEARCH_RATIO)
    recommend = int(total_rps * RECOMMEND_RATIO)
    user = int(total_rps * USER_RATIO)
    reserve = int(total_rps * RESERVE_RATIO)

    # allocate remainder to search (largest class)
    remainder = total_rps - (search + recommend + user + reserve)
    search += remainder

    return {
        "search": search,
        "recommend": recommend,
        "user": user,
        "reserve": reserve,
    }


def _frontend_base_url() -> str:
    """Return the HTTP base URL used by `hit`.

    IMPORTANT: for HR we route through an Istio ingress gateway (not the frontend service ClusterIP).
    `get_gateway_ip(..., use_pod_ip=False)` returns the gateway Service ClusterIP (often not reachable
    from outside the cluster). We instead use the ingress gateway pod IP on :8080.
    """

    gw = get_gateway_ip(FRONTEND_GATEWAY_SVC_NAME)  # e.g. "172.24.x.y:8080"

    # Ensure it includes scheme
    if gw.startswith("http://") or gw.startswith("https://"):
        return gw
    return f"http://{gw}"


def _hr_workflow_urls() -> Dict[str, str]:
    base = _frontend_base_url()
    return {
        "recommend": (
            f"{base}/recommendations?require=price&lat={HR_LAT}&lon={HR_LON}"
        ),
        "search": (
            f"{base}/hotels?inDate={HR_IN_DATE}&outDate={HR_OUT_DATE}&lat={HR_LAT}&lon={HR_LON}"
        ),
        "user": (
            f"{base}/user?username={HR_USERNAME}&password={HR_PASSWORD}"
        ),
        "reserve": (
            f"{base}/reservation?inDate={HR_IN_DATE}&outDate={HR_OUT_DATE}"
            f"&lat={HR_LAT}&lon={HR_LON}&hotelId={HR_HOTEL_ID}"
            f"&customerName={HR_CUSTOMER_NAME}&username={HR_USERNAME}"
            f"&password={HR_PASSWORD}&number={HR_NUMBER_ROOMS}"
        ),
    }


def _get_workflow_rps(total_rps: int) -> Dict[str, int]:
    """Return per-workflow RPS, either from explicit overrides or by splitting total_rps."""

    overrides = {
        "search": SEARCH_RPS,
        "recommend": RECOMMEND_RPS,
        "user": USER_RPS,
        "reserve": RESERVE_RPS,
    }

    if any(v is not None for v in overrides.values()):
        # use 0 for any unset workflow when overrides are active
        rps = {k: int(v) if v is not None else 0 for k, v in overrides.items()}
        for k, v in rps.items():
            if v < 0:
                raise ValueError(f"{k} rps must be >= 0")
        return rps

    return _split_total_rps(total_rps)


def run_hit_hr(q, variation: str, total_rps: int, arr_distr: str):
    """Generate HotelReservation workload by sending requests to frontend.

    If per-workflow RPS overrides are set (SEARCH_RPS/RECOMMEND_RPS/USER_RPS/RESERVE_RPS),
    they are used; otherwise the workload is derived from total_rps and the ratios.

    Implementation detail: `hit` supports multiple Config entries in one JSON file.
    We model per-workflow RPS as separate configs so each gets its own request rate.
    """

    curr_dir = os.path.dirname(os.path.abspath(__file__))

    if total_rps < 0:
        raise ValueError("total_rps must be >= 0")

    workflow_rps = _get_workflow_rps(total_rps)
    urls = _hr_workflow_urls()
    headers_json = json.dumps({"Host": FRONTEND_HOST_HEADER}) if FRONTEND_HOST_HEADER else "{}"

    configs = []
    for name in ["search", "recommend", "user", "reserve"]:
        rps = workflow_rps[name]
        req_interval_ms = _req_interval_ms_from_rps(float(rps))
        configs.append({
            "endpoints": [{
                "url": urls[name],
                "node": 0,
                "app": 0,
                "headers": headers_json,
            }],
            "reqIntervalMs": req_interval_ms,
            "durationMs": DURATION * 1000,
            "logFileName": f"{curr_dir}/{LOG_FOLDER}/{variation}_{name}_hit.log",
            "stallTimeMs": 0,
        })

    with open(f"{curr_dir}/{LOG_FOLDER}/{variation}_hit.json", "w") as f:
        f.write(json.dumps(configs))

    cmd = f"../hit/hit -distr {arr_distr} -f {curr_dir}/{LOG_FOLDER}/{variation}_hit.json"
    print(f"Command: {cmd}")
    print(f"Frontend base: {_frontend_base_url()}")
    print(f"Workflow RPS: {workflow_rps}")

    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()

    q.put((
        "hit",
        start_time,
        end_time,
        f"hit HR finished: total_rps={total_rps} workflow_rps={workflow_rps} exit={exit_status}",
    ))


def run_exp(variation, total_rps: int, enforcement, arr_distr, append_to_times=None):

    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at total_rps={total_rps}")

    queues = []

    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    queues.append(q)
    time.sleep(DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC)

    # run the hotelReservation workloads through a single hit invocation
    q = Queue()
    Thread(target=run_hit_hr, args=(q, variation, total_rps, arr_distr)).start()
    queues.append(q)

    times = []

    # wait for the commands to finish
    for q in queues:
        thread_name, start_time, end_time, finish_status = q.get()
        times.append((thread_name, start_time, end_time))
        print(finish_status)

    with open(f"{LOG_FOLDER}/{variation}.times", "w") as f:
        if append_to_times is not None:
            f.write(append_to_times + "\n")
        for thread_name, start_time, end_time in times:
            f.write(f"{thread_name} {start_time} {end_time}\n")

    print(f"Completed experiment with {variation} at total_rps={total_rps}")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")

    print(f"Sleeping for {SLEEP_TIME_AFTER_EACH_RUN} seconds after the run...")
    time.sleep(SLEEP_TIME_AFTER_EACH_RUN)


def run_exp_for_cluster_state(
    state_id: int,
    total_rps: int,
    svc_to_nodes: Dict[str, List[str]],
    pod_names: List[str],
    lbs: List[str] = [
        "leastrequest",
        "leastrequest_plus",
        "only_nodal_leastrequest",
        "leastrequest_rl",
        "leastrequest_plus_rl",
        "nodal_leastrequest",
        "minimize_diff"]):

    time_started = time.time()
    print(
        f"Running experiment w/ state {state_id} i.e. total_rps={total_rps} & podnames={pod_names} at {time.ctime(time_started)}"
    )

    for lb in lbs:

        print(
            f"Running experiment w/ state {state_id} && lb {LB_NAME[lb]} i.e. total_rps={total_rps} & podnames={pod_names}"
        )

        if "-b" not in sys.argv:
            print(f"Building wasm plugin for {lb}...")
            modify_wasm_plugin(lb)
        else:
            print("Skipping building wasm plugin and setting up topology as per command line argument '-b'...")

        if "-t" in sys.argv:
            print("Only setting up topology as per command line argument '-t'...")
            continue

        print("Seting the correct objective in the optimizer...")
        set_correct_objective(lb)

        # for iteration in [1, 2, 3]:
        for iteration in [1]:
            for distr in ["exponential"]:
                # for load_scale_factor in [0.7, 0.75, 0.8, 0.85, 0.9]:
                for load_scale_factor in [0.8]:

                    scaled_total_rps = int(total_rps * load_scale_factor)

                    print(f"Starting iteration {iteration} for run_id {state_id}...")

                    print(
                        f"Running experiment [iteration {iteration}] w/ state {state_id} && lb {LB_NAME[lb]} && distr {distr} i.e. total_rps={scaled_total_rps} & podnames={pod_names}"
                    )

                    intended_topology = svc_to_nodes
                    to_append = get_topology_str(intended_topology)

                    run_exp(
                        f"{distr}_hr_frontend_mplb_{LB_NAME[lb]}_{state_id}_{iteration}_{load_scale_factor}",
                        scaled_total_rps,
                        "LB",
                        distr,
                        append_to_times=to_append,
                    )

    time_taken = time.time() - time_started
    print(f"Time taken for experiment: {time_taken} seconds")


def set_correct_objective(lb):
    if lb == "minimize_diff":
        os.system("curl http://localhost:4876/complicate_objective")
    else:
        os.system("curl http://localhost:4876/simplify_objective")


def prep_for_exps():

    # create the logs directory
    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)

    build_central_controller()


def main():

    prep_for_exps()

    state_id = 1
    total_rps = 400

    # Topology metadata is still recorded for debugging, but the workload is now frontend-only.
    svc_to_nodes = {
        "frontend": ["node0"],
    }
    pod_names = []

    run_exp_for_cluster_state(
        state_id,
        total_rps,
        svc_to_nodes,
        pod_names,
        lbs=[
            "nodal_leastrequest",
            "minimize_diff",
            "leastrequest_plus_rlpb",
            "nodal_leastrequest_rlpb",
        ],
    )

if __name__ == "__main__":
    start_time = time.time()
    
    main()
    
    time_taken = time.time() - start_time
    print(f"Total time taken: {time_taken} seconds")


# choose a number - requests per second per request