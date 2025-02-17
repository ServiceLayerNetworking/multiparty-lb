from typing import List, Dict, Tuple
from itertools import product, combinations, chain, combinations_with_replacement
from math import comb
import json
import sys
import os

# Get the absolute path of the target directory
parent_dir = os.path.abspath("../gurobi_server")

# Add it to sys.path
sys.path.append(parent_dir)

import locally_optimal_load_distribution as gs_l
import gurobi_server as gs_g

LOGFILE = "logs/offline_sweep.log"

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
    atomic_unit = 30
    num_units = total_load // atomic_unit
    
    distributions = list(map(lambda distr: list(map(lambda svc_distr: svc_distr*atomic_unit, distr)), 
                             generate_distributions(num_units, num_services)))
    
    assert count_ways(num_units, num_services) == len(distributions)
    
    return distributions

def generate_cluster_states():
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
    for svc_id, nodes in state["SvcToNodes"].items():
        for node_id in nodes:
            workers.append({
                "name": f"svc{svc_id}-node{node_id}",
                "host": f"node{node_id}",
                "tenant": f"svc{svc_id}"
            })
    
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
        run_offline_exp(state)
        print(f"Done with state {i+1}/{len(states)}")

if __name__ == "__main__":
    # states = generate_cluster_states()
    # # print(json.dumps(states, indent=4))
    # print(f"Total number of states: {len(states)}")
    
    # print(states[150])
    
    # print(parse_cluster_state_for_gs(states[150]))
    
    run_offline_sweep()