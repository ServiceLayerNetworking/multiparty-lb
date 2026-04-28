from typing import List, Dict, Tuple
from queue import Queue
from threading import Thread
import os
import time
import json
import sys

from set_topology import setup_clutser_with_new_pods, get_curr_gateway_ips, get_gateway_ips

DURATION = 60
DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC = 5
ADDITIONAL_TIME_FOR_CC_TO_RUN = 10
SLEEP_TIME_AFTER_EACH_RUN = 20

CORES_PER_NODE = 8
REQUEST_CPU_CONSUMPTION_MS = 80.0
NODE_LOAD_CAP = 100

LOG_FOLDER = "logs/online_sweep_fairness_Apr26"
OFFLINE_LOG = "../offline-sweep/logs/offline_sweep_spike_fairness_Apr26_lb_0.80_ub_0.80_topo_sampling_2.log"

LB_NAME = {
    "nodal_leastrequest":       "nlr",
    "minimize_diff":            "md",
    "leastrequest":             "lr",
    "weighted_random":          "wr",
    "locality_aware_weighted_random": "lawr",
    "weighted_roundrobin":      "wrr",
    "tmp_nodal_leastrequest":   "tnlr",
    "leastrequest_plus":        "lr++",
    "only_nodal_leastrequest":  "onlr",
    "leastrequest_plus_rl":     "lr++_rl",
    "leastrequest_rl":          "lr_rl",
    "leastrequest_plus_rlpb":   "lr++_rlpb",
    "nodal_leastrequest_rlpb":  "nlr_rlpb",
}


def build_central_controller():
    curr_dir = os.path.dirname(os.path.abspath(__file__))
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


def set_correct_objective(lb):
    if lb == "minimize_diff":
        os.system("curl http://localhost:4876/complicate_objective")
    else:
        os.system("curl http://localhost:4876/simplify_objective")


def get_nodes_for_pods():
    from kubernetes import client, config
    config.load_kube_config()
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace='default', watch=False)
    pod_nodes = {}
    for pod in pods.items:
        pod_nodes[pod.metadata.name] = pod.spec.node_name
    return pod_nodes


def get_nodes_for_apps(nodes_for_pods):
    nodes_for_apps = {}
    for pod, node in nodes_for_pods.items():
        app = "-".join(pod.split("-")[:-1])
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


def parse_svc_load(svc_load: float) -> Tuple[int, float]:
    load = svc_load / 100.0
    default_duration_ms = REQUEST_CPU_CONSUMPTION_MS
    max_cpu_per_time = 1

    if load == 0:
        return 0, default_duration_ms * DURATION + 10

    consumption = max_cpu_per_time * default_duration_ms
    req_interval_ms = default_duration_ms / (load / max_cpu_per_time)
    return int(consumption), float(req_interval_ms)


def run_cc(q, variation, enforcement, duration=DURATION):
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = (
        f"../centralcontroller/centralcontroller"
        f" -logfile {curr_dir}/{LOG_FOLDER}/{variation}_cc.log"
        f" -enforcement={enforcement}"
        f" -d={(duration + ADDITIONAL_TIME_FOR_CC_TO_RUN + DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC) * 1000}"
    )
    print(f"Command: {cmd}")
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    q.put(("cc", start_time, end_time, f"CC finished with exit status: {exit_status}"))


def run_hit(q, variation, svc_loads, arr_distr, proc_distr):
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    configs = []

    for svc_num, svc_load in enumerate(svc_loads):
        svc_name = f"svc{svc_num}"
        cpu_consumption, req_interval_ms = parse_svc_load(svc_load)
        assert req_interval_ms > 0

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

        configs.append({
            "endpoints": endpoints,
            "reqIntervalMs": req_interval_ms,
            "durationMs": DURATION * 1000,
            "logFileName": f"{curr_dir}/{LOG_FOLDER}/{variation}_{svc_name}_hit.log",
            "stallTimeMs": 0,
            "requestIntervalUpdates": []
        })

    with open(f"{curr_dir}/{LOG_FOLDER}/{variation}_hit.json", "w") as f:
        f.write(json.dumps(configs))

    cmd = f"../hit/hit -distr {arr_distr} -f {curr_dir}/{LOG_FOLDER}/{variation}_hit.json"
    print(f"Command: {cmd}")
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    q.put(("hit", start_time, end_time, f"hit for apps{svc_loads} finished with exit status: {exit_status}"))


def run_exp(variation, svc_loads, enforcement, arr_distr, proc_distr, append_to_times=None):
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {svc_loads} RPS")

    queues = []

    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    queues.append(q)
    time.sleep(DELAY_IN_RUNNING_HIT_AFTER_RUNNING_CC)

    q = Queue()
    Thread(target=run_hit, args=(q, variation, svc_loads, arr_distr, proc_distr)).start()
    queues.append(q)

    times = []
    for q in queues:
        thread_name, start_time, end_time, finish_status = q.get()
        times.append((thread_name, start_time, end_time))
        print(finish_status)

    with open(f"{LOG_FOLDER}/{variation}.times", "w") as f:
        f.write(append_to_times + "\n")
        for thread_name, start_time, end_time in times:
            f.write(f"{thread_name} {start_time} {end_time}\n")

    print(f"Completed experiment with {variation} at {svc_loads} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Sleeping for {SLEEP_TIME_AFTER_EACH_RUN} seconds after the run...")
    time.sleep(SLEEP_TIME_AFTER_EACH_RUN)


def prep_for_exps():
    if not os.path.exists(LOG_FOLDER):
        os.makedirs(LOG_FOLDER)
    build_central_controller()


def read_json_line(filename, line_number):
    with open(filename, 'r') as file:
        for i, line in enumerate(file, start=0):
            if i == line_number:
                try:
                    return json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Line {line_number} is not valid JSON: {e}")
        raise IndexError(f"Line {line_number} not found in file.")


def effective_spiked_load(svc: str, data: dict) -> float:
    s_local  = data["SpikeResultsLocal"][svc]
    s_global = data["SpikeResultsGlobal"][svc]
    s_nodal  = data["SpikeResultsNodal"][svc]
    local_alloc  = sum(s_local["result"].values())
    global_alloc = sum(s_global["result"].values())
    nodal_alloc  = sum(s_nodal["result"].values())
    cap = s_local["n_nodes"] * NODE_LOAD_CAP
    return min(1.25 * max(local_alloc, global_alloc, nodal_alloc), cap)


def run_fairness_exp_for_cluster_state(
    state_id: int,
    svc_loads: List[int],
    svc_to_nodes: Dict[str, List[str]],
    pod_names: List[str],
    lbs: List[str],
):
    time_started = time.time()
    print(f"Running fairness experiment w/ state {state_id}, loads={svc_loads}, pods={pod_names} at {time.ctime(time_started)}")

    for lb in lbs:
        for iteration in [0, 1]:
            
            print(f"Running fairness experiment w/ state {state_id} && lb {LB_NAME[lb]} && iteration {iteration}...")


            if "-b" not in sys.argv:
                print(f"Building wasm plugin for {lb}...")
                modify_wasm_plugin(lb)

                print(f"Setting up the topology...")
                done = setup_clutser_with_new_pods(pod_names)
                if not done:
                    print("!!!!!!!\n!!!!!!! Failed to set up the cluster with new pods.\n\n\n\n")
                    continue
            else:
                print("Skipping wasm + topology setup due to '-b' flag...")

            if "-t" in sys.argv:
                print("Only setting up topology due to '-t' flag...")
                continue

            print("Setting the correct objective in the optimizer...")
            set_correct_objective(lb)

            for distr in ["exponential"]:
            
                for load_scale_factor in [0.8]:
                    scaled_svc_loads = [int(svc_load * load_scale_factor) for svc_load in svc_loads]
                    print(f"Starting iteration {iteration} for state {state_id}...")
                    to_append = get_topology_str(svc_to_nodes)
                    run_exp(
                        f"{distr}_{distr}_mplb_{LB_NAME[lb]}_{state_id}_{iteration}_{load_scale_factor}",
                        scaled_svc_loads, "LB", distr, distr,
                        append_to_times=to_append,
                    )

    time_taken = time.time() - time_started
    print(f"Time taken for fairness experiment state {state_id}: {time_taken:.1f}s")


def run_fairness_exp_for_state_id(state_id: int, lbs: List[str]):
    data = read_json_line(OFFLINE_LOG, state_id)

    selected  = set(data["SelectedServices"])
    tenants   = data["Tenants"]
    base_loads = {t["name"]: float(t["load"]) for t in tenants}
    num_svcs  = len(tenants)

    svc_loads = []
    for i in range(num_svcs):
        svc_name = f"svc{i}"
        if svc_name in selected:
            load = effective_spiked_load(svc_name, data)
        else:
            load = base_loads.get(svc_name, 0.0)
        svc_loads.append(int(load * CORES_PER_NODE))

    svc_to_nodes = {}
    for node_id, n_svcs in enumerate(data["State"]["NodesToSvc"]):
        for svc_id, n_pods in enumerate(n_svcs):
            for _ in range(n_pods):
                svc_to_nodes.setdefault(f"svc{svc_id}", []).append(f"node{node_id}")

    pod_names = [w["name"] for w in data["Workers"]]

    print(f"\n=== State {state_id} | Selected: {sorted(selected)} | Loads: {svc_loads} ===")

    run_fairness_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=lbs,
    )


def _main():
    prep_for_exps()

    state_id = 9999
    svc_loads = [200 * CORES_PER_NODE, 200 * CORES_PER_NODE] + [0] * 13  # svc0..svc14

    svc_to_nodes = {
        "svc0":  ["node0", "node1", "node1"],
        "svc1":  ["node1", "node1", "node2", "node2", "node2", "node2"],
        "svc2":  ["node0"],
        "svc3":  ["node0", "node3"],
        "svc4":  ["node0", "node4"],
        "svc5":  ["node5"],
        "svc6":  ["node6"],
        "svc7":  ["node7"],
        "svc8":  ["node8"],
        "svc9":  ["node9"],
        "svc10": ["node10"],
        "svc11": ["node11"],
        "svc12": ["node12"],
        "svc13": ["node13"],
        "svc14": ["node14"],
    }

    pod_names = [
        "svc0-node0-0",
        "svc0-node1-0",
        "svc0-node1-1",
        "svc1-node1-0",
        "svc1-node1-1",
        "svc1-node2-0",
        "svc1-node2-1",
        "svc1-node2-2",
        "svc1-node2-3",
        "svc2-node0-0",
        "svc3-node0-0",
        "svc3-node3-0",
        "svc4-node0-0",
        "svc4-node4-0",
        "svc5-node5-0",
        "svc6-node6-0",
        "svc7-node7-0",
        "svc8-node8-0",
        "svc9-node9-0",
        "svc10-node10-0",
        "svc11-node11-0",
        "svc12-node12-0",
        "svc13-node13-0",
        "svc14-node14-0",
    ]

    run_fairness_exp_for_cluster_state(
        state_id,
        svc_loads,
        svc_to_nodes,
        pod_names,
        lbs=[
            "nodal_leastrequest",
            "nodal_leastrequest_rlpb",
            "leastrequest_plus_rlpb",
            "minimize_diff",
        ],
    )

    os.system("curl -d 'FAIRNESS EXPERIMENT DONE' ntfy.sh/mplb")


def main():
    prep_for_exps()

    for state_id in [2]:
        run_fairness_exp_for_state_id(state_id, lbs=[
            # "nodal_leastrequest",
            "nodal_leastrequest_rlpb",
            # "leastrequest_plus_rlpb",
            # "minimize_diff",
        ])

    os.system("curl -d 'FAIRNESS EXPERIMENT DONE' ntfy.sh/mplb")


if __name__ == "__main__":
    start_time = time.time()
    _main()
    print(f"Total time: {time.time() - start_time:.1f}s")
