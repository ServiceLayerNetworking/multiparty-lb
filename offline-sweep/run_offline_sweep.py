from typing import List, Dict, Tuple
from itertools import product, combinations, chain, combinations_with_replacement
from math import comb
import json
import sys
import os
import numpy as np

# Get the absolute path of the target directory
parent_dir = os.path.abspath("../gurobi_server")

# Add it to sys.path
sys.path.append(parent_dir)

import locally_optimal_load_distribution as gs_l
import gurobi_server as gs_g

NUM_NODES = 3
NUM_SERVICES = 3
NUM_PODS_PER_NODE = 5
NODE_LOAD_CAP = 100
LOAD_ATOMIC_UNIT = 30
cluster_cap = NODE_LOAD_CAP * NUM_NODES
CLUSTER_LOADS = list(range(int(cluster_cap*0.6), int(cluster_cap*1.2)+1, LOAD_ATOMIC_UNIT))
LB_SVC_LOAD = 0
UB_SVC_LOAD = 1.5

# autoscaling threshhold
# latency from real data
# app latencies
# threshhold values and the 
# plots the threshhold values 
LOGFILE = "logs/offline_sweep_Apr3_2237.log"

def write_config():
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

def run_offline_exp(state: Dict[str, any]):
    
    # parse the state to get Hosts, Tenants, Workers
    hosts, tenants, workers = parse_cluster_state_for_gs(state)
    
    global_result = gs_g.run_from_json(hosts, tenants, workers)
    local_result = gs_l.run_from_json(hosts, tenants, workers)
    
    if "NodesToSvc" in state:
        state["NodesToSvc"] = state["NodesToSvc"].tolist()
    
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

def run_offline_sweep():
    states = generate_cluster_states()
    
    for i, state in enumerate(states):
        if i in [143929, 159856, 162078, 163838, 170111, 174690, 175995, 177452]:
            run_offline_exp(state)
            print(f"Done with state {i+1}/{len(states)}")
            input()

if __name__ == "__main__":
    
    write_config()
    run_offline_sweep()