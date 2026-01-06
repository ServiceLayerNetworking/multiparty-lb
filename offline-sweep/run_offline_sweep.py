from typing import List, Dict, Tuple, Any
from itertools import product, combinations, chain, combinations_with_replacement
from math import comb, ceil, floor
import json
import sys
import os
import numpy as np
import random
import copy

# Get the absolute path of the target directory
parent_dir = os.path.abspath("../gurobi_server")

# Add it to sys.path
sys.path.append(parent_dir)

import locally_optimal_load_distribution as gs_l
import gurobi_server as gs_g
import generate_random_topology as grt

NUM_NODES = 15
NUM_SERVICES = 15
NUM_PODS_PER_NODE = 10
NODE_LOAD_CAP = 100
LOAD_ATOMIC_UNIT = 10 # * NUM_NODES
cluster_cap = NODE_LOAD_CAP * NUM_NODES
CLUSTER_LOADS = list(range(int(cluster_cap*0.6), int(cluster_cap*2)+1, LOAD_ATOMIC_UNIT))
LB_SVC_LOAD = 0.3
UB_SVC_LOAD = 1.3

# autoscaling threshhold
# latency from real data
# app latencies
# threshhold values and the 
# plots the threshhold values 
LOGFILE = "logs/offline_sweep_ٕJan4.log"

def write_config():
    # Ensure log directory exists
    log_dir = os.path.dirname(LOGFILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(LOGFILE, "w") as f:
        f.write(json.dumps({
            "NumOfNodes": NUM_NODES,
            "NumOfSvc": NUM_SERVICES,
            "NumOfPodsPerNode": NUM_PODS_PER_NODE,
            "NodeLoadCap": NODE_LOAD_CAP,
            "LoadAtomicUnit": LOAD_ATOMIC_UNIT,
            "ClusterLoads": CLUSTER_LOADS,
            "LB_Svc_Load": LB_SVC_LOAD,
            "UB_Svc_Load": UB_SVC_LOAD,
            "LogFile": LOGFILE
        }))

def get_valid_svc_to_node_mappings(num_nodes: int, num_services: int) -> List[Dict[int, List[int]]]:
    """
    get number of nodes and services and then return svc to node mapping in the following format:
    [{
        0: [0, 1],
        1: [1, 2],
        2: [0, 2]
    },
    {
        0: [0, 1],
        1: [0, 1, 2],
        2: [0, 2]
    },
    ...
    ]
    """

    nodes = list(range(num_nodes))
    services = list(range(num_services))
    
    # generate all possible mappings for a service (power set of nodes)
    power_set_of_nodes = chain.from_iterable(combinations(nodes, r) for r in range(1, len(nodes) + 1))
    
    all_mappings = []
    
    # generate all possible mappings for all services (cartesian product of power set of nodes)
    for raw_mapping in product(power_set_of_nodes, repeat=len(services)):
        mapping = {}
        for svc_id, node_ids in enumerate(raw_mapping):
            mapping[svc_id] = list(node_ids)
        all_mappings.append(mapping)
    
    return all_mappings

def count_ways(m, n):
    """Returns the number of ways to distribute m identical balls into n distinct bags."""
    return comb(m + n - 1, n - 1)

def generate_distributions(m, n):
    """Generates all ways to distribute m identical balls into n labeled boxes."""
    for partition in combinations_with_replacement(range(n), m):
        yield [partition.count(i) for i in range(n)]

def get_valid_load_distributions(total_load: int, num_services: int) -> List[List[int]]:
    """
    get total load and number of services and then return all possible load distributions in the following format:
    [
        [60, 60, 60],
        [60, 60, 70],
        ...
    ]
    """
    atomic_unit = LOAD_ATOMIC_UNIT
    num_units = total_load // atomic_unit
    
    distributions = list(map(lambda distr: list(map(lambda svc_distr: svc_distr*atomic_unit, distr)), 
                             generate_distributions(num_units, num_services)))
    
    assert count_ways(num_units, num_services) == len(distributions)
    
    return distributions

def get_all_topos(num_nodes, num_services, num_pods_per_node):
    
    '''
    Each node can have 3 pods which you split between the services, 
    e.g. for a node the possible number of pods for each svc can be:
    [svc1, svc2, svc3] can be one of {[3, 0, 0], [2, 1, 0,], [2, 0, 1], [1, 2, 0], …}
    
    we will return topos, where each topo is a node to svc mapping in the following form:
    3D Numpy array of shape (num_topos, num_nodes, num_services)
    where each element is the number of pods for a service on a node
    e.g. for a node the possible number of pods for each svc can be:
    [[
        [3, 0, 0],
        [2, 1, 0],
        [2, 0, 1],
    ],
    [
        [1, 2, 0],
        [1, 1, 1],
        [0, 3, 0],
    ],
    [
        [0, 2, 1],
        [0, 1, 2],
        [0, 0, 3],
    ]]
    '''
    
    # for a node, calculate all combinations for pods to belong to any of the services
    num_of_units = num_pods_per_node
    distributions = list(map(lambda distr: list(map(lambda svc_distr: svc_distr*1, distr)), 
                             generate_distributions(num_of_units, num_services)))
    
    # for each node, we can have any of the distributions
    # so we will take cartesian product of the distributions for all nodes
    topos = np.array(list(product(distributions, repeat=num_nodes)))
    print("Number of topos:", topos.shape[0])
    
    return topos

def get_topos_feasible_for_load(
    topos: np.array,
    svc_loads: List[int],
    lb_svc_load: float,
    ub_svc_load: float,
    cap_per_pod: int):
    
    # Service loads for each service (service 0, service 1, service 2)
    service_loads = np.array(svc_loads)

    # Capacity per pod (e.g. each pod provides 10 units of capacity)
    cap_per_pod = cap_per_pod

    # Calculate total capacity per service for each topology.
    # This sums across nodes (axis=1) for each service.
    capacities = np.sum(topos, axis=1) * cap_per_pod
    # 'capacities' will have shape (n_topologies, n_services)

    # Create a boolean mask: valid if for every service in the topology,
    # the load is between 50% and 150% of the capacity.
    valid_mask = np.all(
        (service_loads >= lb_svc_load * capacities) & (service_loads <= ub_svc_load * capacities),
        axis=1
    )

    # Filter the topologies based on the valid mask
    valid_topologies = topos[valid_mask]

    # print("Capacities per topology:\n", capacities)
    # print("Valid topologies mask:", valid_mask)
    # print("Valid topologies:\n", valid_topologies)
    
    return valid_topologies

def remove_mirror_topologies(topologies):
    """
    Remove mirror topologies from a 3D numpy array.
    
    Each slice in `topologies` is a 2D array where rows represent nodes.
    Two topologies are considered mirrors if their rows (as sets) are identical.
    
    Returns a 3D array with only one copy per unique topology.
    """
    unique = {}
    
    for topo in topologies:
        # Convert each row to a tuple, then sort the list of rows to get a canonical representation.
        canonical = tuple(sorted(map(tuple, topo)))
        if canonical not in unique:
            unique[canonical] = topo
            
    # Convert the unique topologies back into a numpy array.
    return np.array(list(unique.values()))

def generate_cluster_states():
    """
    Exhaustively enumerate feasible cluster states (original slower version).
    """
    
    num_nodes = NUM_NODES
    num_services = NUM_SERVICES
    num_pods_per_node = NUM_PODS_PER_NODE
    node_cap = NODE_LOAD_CAP
    node_caps = [node_cap] * num_nodes
    pod_cap = node_cap // num_pods_per_node
    cluster_loads = CLUSTER_LOADS
    lb_svc_load = LB_SVC_LOAD
    ub_svc_load = UB_SVC_LOAD
    
    # get all possible topos, ensuring that hte 
    topos = get_all_topos(num_nodes, num_services, num_pods_per_node)
    
    # prune the topos where there are no pods for a service
    valid_mask = np.all(np.sum(topos, axis=1) >= 1, axis=1)
    topos = topos[valid_mask]
    print("Number of valid topos:", topos.shape[0])
    
    topos = remove_mirror_topologies(topos)
    print(f"Number of unique topos: {topos.shape}")
    # print(topos)
    
    all_states = []
    
    n_states = 0
    
    for cluster_load in cluster_loads:
        svc_load_distributions = get_valid_load_distributions(cluster_load, num_services)
        print(f"Cluster load: {cluster_load}, # of distributions: {len(svc_load_distributions)}")
        print(f"n_states: {n_states}")
        for svc_loads in svc_load_distributions:
            
            # ensure that the lb*svc_caps <= svc_loads <= ub*svc_caps
            feasible_topos = get_topos_feasible_for_load(topos, svc_loads, lb_svc_load, ub_svc_load, pod_cap)
            n_states += feasible_topos.shape[0]
            
            for topology in feasible_topos:
                cluster_state = {
                    "NumOfNodes": num_nodes,
                    "NumOfSvc": num_services,
                    "NodesToSvc": topology,
                    "NodeCaps": node_caps,
                    "SvcLoads": svc_loads,
                }
                all_states.append(cluster_state)
    
    print(f"Total number of states: {n_states}")
    
    return all_states

# stars-and-bars uniform sampler (no bounds). Used in fast generator with rejection.
def _sample_stars_bars_uniform(R: int, n: int, rng: np.random.Generator) -> np.ndarray:
    if n == 1:
        return np.array([R], dtype=int)
    if R == 0:
        return np.zeros(n, dtype=int)
    # Choose n-1 bar positions uniformly from 1..(R + n - 1)
    # Use sentinel at (R + n - 1) + 1 so total length accounts for all stars
    bars = np.sort(rng.choice(R + n - 1, size=n - 1, replace=False) + 1)
    y = np.concatenate(([0], bars, [R + n]))  # last sentinel must be R + n for correct sum
    z = np.diff(y) - 1  # gaps minus 1 yield part sizes; sum(z) == R
    return z.astype(int)

def random_split_with_caps(T, n, U, rng: np.random.Generator):
    """
    Randomly split T items into n holes with per-hole caps U.
    Returns an array of size n with the number of items in each hole.
    """
    
    # Create all allowed placements according to remaining capacity
    choices = np.repeat(np.arange(n), U)

    # Randomly pick T placements and count occurrences
    return np.bincount(rng.choice(choices, T), minlength=n)

def get_load(fshare: float, lb: int, ub: int) -> float:
    # return (np.random.exponential(scale=mean_ms_util) / 100.0) * fshare
    # return (random.randint(int(lb*100), int(ub*100)) / 100.0) * fshare
    return (80.0 / 100.0) * fshare

def generate_cluster_states_fast(k: int, seed: int | None = None):
    """
    Generate k random feasible cluster states (fast sampling version).
    Process:
    - Pick ONE cluster load T from CLUSTER_LOADS per state.
    - Randomly sample service loads that sum to T using stars-and-bars.
    - Accept if each service load <= UB * capacity(topology); otherwise retry service distribution.
    - If repeated failures for a topology, resample topology but keep the SAME T.
    """
    # Local aliases and RNG
    num_nodes = NUM_NODES
    num_services = NUM_SERVICES
    num_pods_per_node = NUM_PODS_PER_NODE
    node_cap = NODE_LOAD_CAP
    node_caps = [node_cap] * num_nodes
    pod_cap = node_cap // num_pods_per_node
    ub_svc_load = UB_SVC_LOAD
    au = LOAD_ATOMIC_UNIT
    cluster_loads_units = [L // au for L in CLUSTER_LOADS]
    rng = np.random.default_rng(seed)

    # Helper to sample a topology and ensure each service has at least one pod overall
    def sample_topology() -> np.ndarray:
        topo = np.zeros((num_nodes, num_services), dtype=int)
        for n in range(num_nodes):
            alloc = rng.multinomial(num_pods_per_node, [1.0 / num_services] * num_services)
            topo[n, :] = alloc
        # col_sums = np.sum(topo, axis=0)
        # zero_svcs = np.where(col_sums == 0)[0]
        # for svc in zero_svcs:
        #     donor_candidates = [j for j in range(num_services) if j != svc and col_sums[j] > 1]
        #     if donor_candidates:
        #         donor = int(rng.choice(donor_candidates))
        #         donor_nodes = np.where(topo[:, donor] > 0)[0]
        #         if len(donor_nodes) > 0:
        #             node_idx = int(rng.choice(donor_nodes))
        #             topo[node_idx, donor] -= 1
        #             topo[node_idx, svc] += 1
        #             col_sums[donor] -= 1
        #             col_sums[svc] += 1
        return topo

    sampled_states = []
    error_count = 0
    max_dist_attempts = 50000

    for _ in range(k):
        # Pick cluster load once
        T_units = int(rng.choice(cluster_loads_units))

        # Assume topology can support T (per instructions)
        topology = sample_topology()
        caps = np.sum(topology, axis=0) * pod_cap
        U_units = np.array([floor(ub_svc_load * c / au) for c in caps], dtype=int)

        # Sample service loads summing to T; reject if any exceeds U
        accepted = False
        for _attempt in range(max_dist_attempts):
            # z_units = rng.multinomial(T_units, np.ones(num_services)/num_services)
            z_units = random_split_with_caps(T_units, num_services, U_units, rng)
            # _sample_stars_bars_uniform(T_units, num_services, rng)
            if np.all(z_units <= U_units):
                accepted = True
                break
        if not accepted:
            print(f"z_units: {z_units}")
            print("U_units:", U_units)
            print(f"Error: could not find feasible distribution for cluster load {T_units*au} after {max_dist_attempts} attempts")
            error_count += 1
            continue  # move to next sample

        svc_units = z_units
        # Sanity check on units sum before converting to loads
        if int(np.sum(svc_units)) != int(T_units):
            print(f"Error: units sum mismatch (sum={int(np.sum(svc_units))}, T_units={int(T_units)}). Skipping sample.")
            error_count += 1
            continue
        svc_loads = (svc_units * au).astype(int).tolist()
        if sum(svc_loads) != T_units * au:
            print(f"Error: load sum mismatch (sum={sum(svc_loads)}, T={T_units * au}). Skipping sample.")
            error_count += 1
            continue

        cluster_state = {
            "NumOfNodes": num_nodes,
            "NumOfSvc": num_services,
            "NodesToSvc": topology,
            "NodeCaps": node_caps,
            "SvcLoads": svc_loads,
        }
        sampled_states.append(cluster_state)
        
        # if len(sampled_states) % 1000 == 0:
        print(f"\rGenerated {len(sampled_states)}/{k} random states so far...", end='', flush=True)

    print(f"Generated {len(sampled_states)} random states (errors: {error_count})")
    if error_count > 0:
        try:
            resp = input(f"Encountered {error_count} errors. Continue? [y/N]: ").strip().lower()
        except EOFError:
            resp = 'n'
        if resp not in ('y', 'yes'):
            print("Aborting due to errors.")
            return []
    return sampled_states
    # Helper to sample a topology and ensure each service has at least one pod overall

def sample_topology(num_nodes, num_services, num_pods_per_node, rng) -> np.ndarray:
    topo = np.zeros((num_nodes, num_services), dtype=int)
    for n in range(num_nodes):
        alloc = rng.multinomial(num_pods_per_node, [1.0 / num_services] * num_services)
        topo[n, :] = alloc
    return topo

def sample_topology_2(num_nodes, num_services, rng, l: float = 2.0) -> np.ndarray:
    """
    Strategy 2: Draw from exponential distribution to determine how many nodes a service will have pods on.
    
    For each service, draw from an exponential 
    distribution with mean l (default 2) to get n_svc_nodes, i.e. the number of nodes this service 
    will have a pod on. Cap this value to the total number of nodes. Place one pod for the 
    service on n_svc_nodes randomly selected nodes. Note that each service gets at most one pod per node.
    
    Note: Increasing l increases the number of nodes each service is present on.
    
    Args:
        l: Mean of exponential distribution for number of nodes per service
    
    Returns:
        Topology array of shape (num_nodes, num_services) with 0/1 values
    """
    topo = np.zeros((num_nodes, num_services), dtype=int)
    
    for svc in range(num_services):
        # Draw from exponential distribution and cap to num_nodes
        n_svc_nodes = int(rng.exponential(scale=l))
        n_svc_nodes = min(n_svc_nodes, num_nodes)
        
        # Ensure at least one node hosts this service
        n_svc_nodes = max(n_svc_nodes, 1)
        
        # Randomly select n_svc_nodes nodes to host this service
        selected_nodes = rng.choice(num_nodes, size=n_svc_nodes, replace=False)
        topo[selected_nodes, svc] = 1
    
    return topo

def sample_topology_2_fixed_l(num_nodes, num_services, rng, l: float = 2.0) -> np.ndarray:
    """
    Strategy 2: Draw from exponential distribution to determine how many nodes a service will have pods on.
    
    For each service, draw from an exponential 
    distribution with mean l (default 2) to get n_svc_nodes, i.e. the number of nodes this service 
    will have a pod on. Cap this value to the total number of nodes. Place one pod for the 
    service on n_svc_nodes randomly selected nodes. Note that each service gets at most one pod per node.
    
    Note: Increasing l increases the number of nodes each service is present on.
    
    Args:
        l: Mean of exponential distribution for number of nodes per service
    
    Returns:
        Topology array of shape (num_nodes, num_services) with 0/1 values
    """
    topo = np.zeros((num_nodes, num_services), dtype=int)
    
    for svc in range(num_services):
        # Draw from exponential distribution and cap to num_nodes
        n_svc_nodes = int(np.ceil(l))
        n_svc_nodes = min(n_svc_nodes, num_nodes)
        
        # Ensure at least one node hosts this service
        n_svc_nodes = max(n_svc_nodes, 1)
        
        # Randomly select n_svc_nodes nodes to host this service
        selected_nodes = rng.choice(num_nodes, size=n_svc_nodes, replace=False)
        topo[selected_nodes, svc] = 1
    
    return topo

def sample_topology_3(num_nodes, num_services, rng, l: float = 2.0) -> np.ndarray:
    """
    Strategy 3: Draw from exponential distribution to determine the total number of pods a service will have.
    
    For each service, draw from an exponential distribution with mean l (default 2) to get 
    n_svc_pods—the total number of pods this service will have. Assign each pod to a random 
    node (with replacement, allowing multiple pods per node).
    
    Note: Increasing l increases the total number of pods each service has.
    
    Args:
        l: Mean of exponential distribution for number of pods per service
    
    Returns:
        Topology array of shape (num_nodes, num_services)
    """
    topo = np.zeros((num_nodes, num_services), dtype=int)
    
    for svc in range(num_services):
        # Draw from exponential distribution to get number of pods
        n_svc_pods = int(np.ceil(rng.exponential(scale=l)))
        
        # Ensure at least one pod per service
        n_svc_pods = max(n_svc_pods, 1)
        
        # Assign each pod to a random node (with replacement - allows multiple pods per node)
        for _ in range(n_svc_pods):
            node = rng.integers(0, num_nodes)
            topo[node, svc] += 1
    
    return topo

def generate_cluster_states_fast_wo_total_cluster_load(
    k: int,
    seed: int | None = None,
    lb: float = LB_SVC_LOAD,
    ub: float = UB_SVC_LOAD,
    topo_sample_strategy: int = 2):
    """
    Generate k random feasible cluster states (fast sampling version).
    Process:
    - Pick ONE cluster load T from CLUSTER_LOADS per state.
    - Randomly sample service loads that sum to T using stars-and-bars.
    - Accept if each service load <= UB * capacity(topology); otherwise retry service distribution.
    - If repeated failures for a topology, resample topology but keep the SAME T.
    """
    # Local aliases and RNG
    num_nodes = NUM_NODES
    num_services = NUM_SERVICES
    num_pods_per_node = NUM_PODS_PER_NODE
    node_cap = NODE_LOAD_CAP
    node_caps = [node_cap] * num_nodes
    pod_cap = node_cap // num_pods_per_node
    ub_svc_load = UB_SVC_LOAD
    au = LOAD_ATOMIC_UNIT
    cluster_loads_units = [L // au for L in CLUSTER_LOADS]
    rng = np.random.default_rng(seed)

    sampled_states = []

    for _ in range(k):
        
        topology = None
        if topo_sample_strategy == 1:
            topology = sample_topology(num_nodes, num_services, num_pods_per_node, rng)
        elif topo_sample_strategy == 2:
            topology = sample_topology_2(num_nodes, num_services, rng, l=3.0)
        elif topo_sample_strategy == 3:
            topology = sample_topology_3(num_nodes, num_services, rng, l=3.0)
        else:
            raise ValueError(f"Unknown topo_sample_strategy: {topo_sample_strategy}")
        
        # Calculate fair share for each service
        # Fair share = sum across all nodes of (service's fair share on that node)
        # Fair share on node = (num_pods_of_service_on_node / total_pods_on_node) * node_cap
        fshares = np.zeros(num_services)
        for node_id in range(num_nodes):
            total_pods_on_node = np.sum(topology[node_id, :])
            if total_pods_on_node > 0:
                for svc_id in range(num_services):
                    num_pods_of_svc = topology[node_id, svc_id]
                    fshares[svc_id] += (num_pods_of_svc / total_pods_on_node) * node_cap

        svc_loads = [get_load(fs, lb, ub) for fs in fshares]

        cluster_state = {
            "NumOfNodes": num_nodes,
            "NumOfSvc": num_services,
            "NodesToSvc": topology,
            "NodeCaps": node_caps,
            "SvcLoads": svc_loads,
        }
        sampled_states.append(cluster_state)
        
        # if len(sampled_states) % 1000 == 0:
        print(f"\rGenerated {len(sampled_states)}/{k} random states so far...", end='', flush=True)

    print(f"Generated {len(sampled_states)} random states")
    return sampled_states


def _generate_cluster_states():   
    """
    this is deprecated: in this each service could have a maximum of 1 pod on a node,
        and load on a service was not correlated with the number of pods
    """
    
    num_nodes = 3
    num_services = 3
    node_caps = [100] * num_nodes
    load_values = range(180, 361, 30)
    
    valid_topos = get_valid_svc_to_node_mappings(num_nodes, num_services)
    print(f"Total number of topologies: {len(valid_topos)}")
    all_states = []
    
    for total_load in load_values:
        for svc_loads in get_valid_load_distributions(total_load, num_services):
            for topology in valid_topos:
                cluster_state = {
                    "NumOfNodes": num_nodes,
                    "NumOfSvc": num_services,
                    "SvcToNodes": topology,
                    "NodeCaps": node_caps,
                    "SvcLoads": svc_loads,
                }
                all_states.append(cluster_state)
    
    return all_states

def populate_pods_from_topology(topology):
    """
    Given a 2D topology configuration where each row corresponds to a node and
    each column to a service (with the cell value indicating the number of pods),
    this function returns a list of pod dictionaries.
    """
    pods = []
    
    topology = np.array(topology)
    num_nodes, num_services = topology.shape

    for node_id in range(num_nodes):
        for svc_id in range(num_services):
            num_pods = topology[node_id, svc_id]
            for pod_id in range(num_pods):
                pods.append({
                    "name": f"svc{svc_id}-node{node_id}-{pod_id}",
                    "host": f"node{node_id}",
                    "tenant": f"svc{svc_id}"
                })
    return pods

def parse_cluster_state_for_gs(
    
    state: Dict[str, any]) -> Tuple[Dict[str, any], Dict[str, any], Dict[str, any]]:
    """
    return Hosts, Tenants, Workers as dictionaries parsable by both global and local gurobi servers
    """
    
    hosts = []
    for i in range(state["NumOfNodes"]):
        hosts.append({
            "name": f"node{i}",
            "cap": state["NodeCaps"][i]
        })
        
    tenants = {}
    for i in range(state["NumOfSvc"]):
        name = f"svc{i}"
        tenants[name] = {
            "name": name,
            "load": state["SvcLoads"][i],
            "fshareload": 0
        }
        
    workers = []
    if "SvcToNodes" in state:
        for svc_id, nodes in state["SvcToNodes"].items():
            for node_id in nodes:
                workers.append({
                    "name": f"svc{svc_id}-node{node_id}",
                    "host": f"node{node_id}",
                    "tenant": f"svc{svc_id}"
                })
    else:
        workers = populate_pods_from_topology(state["NodesToSvc"])
    
    # calculate the fshareload for each tenant
    # fshareload_of_tenant_t = sum(fshareload_of_worker_w when w.tenant == t)
    # fshareload_of_worker_w = host.cap / number of workers on host
    for host in hosts:
        workers_on_host = [worker for worker in workers if worker["host"] == host["name"]]
        
        n_workers_on_host = len(workers_on_host)
        
        for worker in workers_on_host:
            tenant_name = worker["tenant"]
            tenants[tenant_name]["fshareload"] += host["cap"] / n_workers_on_host
        
    return hosts, list(tenants.values()), workers

def is_load_satisfied(tenants: List[Dict[str, Any]], global_result: Any) -> bool:
    """
    check if the load is satisfied in the global result
    """
    
    """
    "GlobalResult": {
        "status": 2,
        "result": {
            "svc2": {
                "svc2-node0-0": 0.0,
                "svc2-node0-1": 99.99999999864023,
                "svc2-node1-0": 45.28459492205221,
                "svc2-node3-0": 22.33848423291218,
                "svc2-node7-0": 19.623148891255752,
                "svc2-node8-0": 13.727212320016577,
                "svc2-node11-0": 33.02655963482034
            }
        }
    }
    """
    
    for tenant in tenants:
        tenant_name = tenant["name"]
        required_load = tenant["load"]
        assigned_load = sum(global_result["result"][tenant_name].values())
        if abs(assigned_load - required_load) > 1.00:
            print(f"Load unsatisfied for {tenant_name}: required {required_load}, assigned: {assigned_load}")
            return False
    return True

def get_max_load_for_tenant(tenant_name: str, hosts: List[Dict[str, Any]], workers: List[Dict[str, Any]]) -> float:
    return 15*NODE_LOAD_CAP

def _solver_feasible(tenants: List[Dict[str, Any]], solver_result: Any) -> bool:
    """
    Returns True iff solver_result looks valid and is_load_satisfied(...) holds.
    Treats any missing/invalid structure as infeasible.
    """
    try:
        # Optional: check a common "status" field if present (Gurobi often uses status==2 for optimal).
        # We won't require it strictly, but if it's present and not 2, consider infeasible.
        if isinstance(solver_result, dict) and "status" in solver_result:
            if solver_result["status"] != 2:
                print("\n\nSolver status not optimal:", solver_result["status"], "\n\n\n")
                return False
        return is_load_satisfied(tenants, solver_result)
    except Exception:
        return False

def _binary_search_max_load_for_one_tenant(
    hosts: List[Dict[str, Any]],
    tenants: List[Dict[str, Any]],
    workers: List[Dict[str, Any]],
    tenant_idx: int,
    solver_fn,
    lo: float,
    hi: float,
    delta: float = 1.0,
    max_iters: int = 80,
) -> Tuple[float, int]:
    """
    Binary search maximum feasible load for tenants[tenant_idx]["load"] in [lo, hi].

    IMPORTANT:
    - This function MUST NOT mutate the caller's `tenants`.
    - We therefore work on a deep copy of tenants.
    """
    calls = 0

    # Deep copy tenants to avoid mutating caller state
    tenants_local = copy.deepcopy(tenants)
    t = tenants_local[tenant_idx]

    # Require feasibility at lo
    t["load"] = float(lo)
    res = solver_fn(hosts, tenants_local, workers)
    calls += 1
    if not _solver_feasible(tenants_local, res):
        raise RuntimeError(
            f"Binary search precondition failed: lo={lo} infeasible for tenant={t['name']}"
        )

    best = lo

    for _ in range(max_iters):
        if (hi - best) <= delta:
            break

        mid = (best + hi) / 2.0
        t["load"] = float(mid)
        res = solver_fn(hosts, tenants_local, workers)
        calls += 1

        if _solver_feasible(tenants_local, res):
            best = mid
        else:
            hi = mid

    return float(best), calls


def run_offline_exp_spike(
    state: Dict[str, any],
    hosts=None,
    tenants=None,
    workers=None,
    delta: float = 1.0,
):
    """
    Spike experiment:
      1) For each service: run LOCAL binary search from current load -> max to get max_local.
      2) For each service: set load=max_local and REQUIRE global feasibility at that seed.
         If infeasible, RAISE (per your request).
      3) If feasible, run GLOBAL binary search from max_local -> max to get max_global.
    Logs SpikeResultsLocal and SpikeResultsGlobal.
    """
    if hosts is None or tenants is None or workers is None:
        hosts, tenants, workers = parse_cluster_state_for_gs(state)

    # Ensure loads are floats (binary search uses floats)
    for t in tenants:
        t["load"] = float(t["load"])

    spike_local = {}
    spike_global = {}

    # LOCAL first (compute base max per-service)
    for i, t in enumerate(tenants):
        tenant_name = t["name"]
        base_load = float(t["load"])
        max_load = float(get_max_load_for_tenant(tenant_name, hosts, workers))

        best_local, calls_local = _binary_search_max_load_for_one_tenant(
            hosts=hosts,
            tenants=tenants,
            workers=workers,
            tenant_idx=i,
            solver_fn=gs_l.run_from_json,
            lo=base_load,
            hi=max_load,
            delta=delta,
        )

        spike_local[tenant_name] = {
            "base": base_load,
            "max": best_local,
            "ub": max_load,
            "delta": delta,
            "solver_calls": calls_local,
        }

    print(f"\nSpike Local Results: {json.dumps(spike_local, indent=2)}\n")
    print("\n Local spike search complete. Proceeding to Global spike search...\n")

    # GLOBAL seeded by LOCAL (STRICT: raise if seed infeasible)
    for i, t in enumerate(tenants):
        tenant_name = t["name"]
        base_load = float(t["load"])
        seed = float(spike_local[tenant_name]["max"])
        max_load = float(get_max_load_for_tenant(tenant_name, hosts, workers))

        # Strict seed feasibility check
        tenants_seed = copy.deepcopy(tenants)
        tenants_seed[i]["load"] = seed
        global_seed_res = gs_g.run_from_json(hosts, tenants_seed, workers)

        if not _solver_feasible(tenants_seed, global_seed_res):
            raise RuntimeError(
                f"Global infeasible at local seed for tenant={tenant_name}: seed={seed}, base={base_load}"
            )

        best_global, calls_global = _binary_search_max_load_for_one_tenant(
            hosts=hosts,
            tenants=tenants,
            workers=workers,
            tenant_idx=i,
            solver_fn=gs_g.run_from_json,
            lo=seed,
            hi=max_load,
            delta=delta,
        )

        spike_global[tenant_name] = {
            "base": base_load,
            "seed_local": seed,
            "max": best_global,
            "ub": max_load,
            "delta": delta,
            "solver_calls": calls_global,
        }

    # Preserve your original state serialization behavior
    if "NodesToSvc" in state:
        state["NodesToSvc"] = np.array(state["NodesToSvc"]).tolist()

    output = {
        "State": state,
        "Hosts": hosts,
        "Tenants": tenants,
        "Workers": workers,
        "SpikeResultsLocal": spike_local,
        "SpikeResultsGlobal": spike_global,
    }

    with open(LOGFILE, "a") as f:
        f.write(json.dumps(output) + "\n")


def run_offline_exp(state: Dict[str, any], hosts=None, tenants=None, workers=None):
    
    if hosts is None or tenants is None or workers is None:
        # parse the state to get Hosts, Tenants, Workers
        hosts, tenants, workers = parse_cluster_state_for_gs(state)
    
    global_result = gs_g.run_from_json(hosts, tenants, workers)
    local_result = gs_l.run_from_json(hosts, tenants, workers)
    
    if "NodesToSvc" in state:
        state["NodesToSvc"] = np.array(state["NodesToSvc"]).tolist()
    
    output = {
        "State": state,
        "Hosts": hosts,
        "Tenants": tenants,
        "Workers": workers,
        "GlobalResult": global_result,
        "LocalResult": local_result
    }
     
    # append output to log file
    with open(LOGFILE, "a") as f:
        f.write(json.dumps(output) + "\n")

def generate_alibaba_based_cluster_states(l: float = 0.08, k: int = 10000):
    sampled_states = []

    for _ in range(k):
        hosts, tenants, workers = grt.get_topology(NUM_NODES, load_lambda=l*NODE_LOAD_CAP, host_capacity=NODE_LOAD_CAP)
        
        hosts = [{"name": h.name, "cap": h.cap} for h in hosts]
        tenants = [{"name": t.name, "load": t.load, "fshareload": t.fshareload} for t in tenants]
        workers = [{"name": w.name, "host": w.host, "tenant": w.tenant} for w in workers]
        
        sampled_states.append((hosts, tenants, workers))
        print(f"\rGenerated {len(sampled_states)}/{k} random states so far...", end='', flush=True)

    print(f"Generated {len(sampled_states)} random states")
        
    return sampled_states

def run_offline_sweep():
    
    global LOGFILE
    
    for topo_sample_strategy in [3]:
    
        for ub in [1.60]: #]np.arange(1.2, 2.0+0.01, 0.10):
            
            lb = 0.00
                        
            LOGFILE = f"logs/offline_sweep_Nov26_lb_{lb:.2f}_ub_{ub:.2f}_topo_sampling_{topo_sample_strategy}.log"
            
            # clear log file
            with open(LOGFILE, "w") as f:
                f.write("")
        
            # Local knobs for faster experiments; modify as needed.
            use_fast = True   # Set to False to run exhaustive (slow) path
            k = 10000           # Number of random states to generate in fast mode
            # seed = 42         # RNG seed for reproducibility in fast mode

            if use_fast:
                # states = generate_cluster_states_fast_wo_total_cluster_load(l=l, k=k) #, seed=seed)
                states = generate_cluster_states_fast_wo_total_cluster_load(
                    k=k, lb=lb, ub=ub, topo_sample_strategy=topo_sample_strategy, seed=seed)
            else:
                # Exhaustive path: original behavior (restrict to elected indices)
                states = generate_cluster_states()
            
            # sample 100 states from all the states
            states = random.sample(states, 1000, seed=seed)
            
            # input("Press Enter to start processing states...")
            
            for i, state in enumerate(states):
                if type(state) is tuple:
                    hosts, tenants, workers = state
                    run_offline_exp(state={}, hosts=hosts, tenants=tenants, workers=workers)
                else:
                    run_offline_exp(state)
                print(f"Done with state {i+1}/{len(states)}")
                # input()

def run_offline_sweep_spike():
    
    global LOGFILE
    
    for topo_sample_strategy in [2]:
    
        for ub in [1.60]:  # np.arange(1.2, 2.0+0.01, 0.10):
            
            lb = 0.00
                        
            LOGFILE = f"logs/offline_sweep_Jan4_lb_{lb:.2f}_ub_{ub:.2f}_topo_sampling_{topo_sample_strategy}.log"
            
            # clear log file
            with open(LOGFILE, "w") as f:
                f.write("")
        
            # Local knobs for faster experiments; modify as needed.
            use_fast = True   # Set to False to run exhaustive (slow) path
            k = 10000         # Number of random states to generate in fast mode
            seed = None       # RNG seed for reproducibility in fast mode

            if use_fast:
                states = generate_cluster_states_fast_wo_total_cluster_load(
                    k=k, lb=lb, ub=ub, topo_sample_strategy=topo_sample_strategy, seed=seed)
            else:
                states = generate_cluster_states()
            
            # sample 1000 states from all the states
            # random.seed(42)
            states = random.sample(states, 1000)
            
            for i, state in enumerate(states):
                if type(state) is tuple:
                    hosts, tenants, workers = state
                    run_offline_exp_spike(state={}, hosts=hosts, tenants=tenants, workers=workers, delta=1.0)
                else:
                    run_offline_exp_spike(state, delta=1.0)

                print(f"Done with state {i+1}/{len(states)}")


def replay_offline_sweep(scale_factor: float = 0.8):
    """
    Replay the offline sweep from the log file.
    """
    
    file_to_replay = f"logs/offline_sweep_Nov26_lb_0.00_ub_1.60_topo_sampling_3.log"
    
    global LOGFILE
    
    LOGFILE = f"{file_to_replay}_replay_{scale_factor:.2f}.log"
    
    # clear log file
    with open(LOGFILE, "w") as f:
        f.write("")
    
    with open(file_to_replay, "r") as f:
        for line in f:
            output = json.loads(line)
            state = output["State"]
            
            # reduce all loads by scale factor
            state["SvcLoads"] = [(float(load) * scale_factor) for load in state["SvcLoads"]]
            
            run_offline_exp(state)

if __name__ == "__main__":
    # write_config()
    # run_offline_sweep()
    
    run_offline_sweep_spike()
    
    # print(arr := sample_topology_3(15, 15, np.random.default_rng(None), l=10.0))
    
    # print("Sum per service:", np.sum(arr, axis=0))
    # print("Sum per node:", np.sum(arr, axis=1))