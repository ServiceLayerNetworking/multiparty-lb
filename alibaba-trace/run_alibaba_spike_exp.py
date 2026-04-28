from itertools import cycle
import pandas as pd
import json
import re
import math
import os
import numpy as np
import random

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as ticker
import seaborn as sns
import itertools

import concurrent.futures

import sys

# Get the absolute path of the target directory
parent_dir = os.path.abspath("../gurobi_server")

# Add it to sys.path
sys.path.append(parent_dir)

import locally_optimal_load_distribution as gs_l
import gurobi_server as gs_g


def get_state(ms_df_: pd.DataFrame, pct_of_svc_spiking: int, default_load_pct: float = 80.0) -> tuple[list[dict], list[dict], list[dict]]:

    unique_instances = ms_df_.drop_duplicates(subset="msinstanceid").copy()
    node_msinstance_count = unique_instances.groupby("nodeid").count()["msinstanceid"].to_dict()

    def get_node_cap(node_id: str) -> int:
        return node_msinstance_count[node_id] * 10

    # Build host info
    node_caps = {node_id: get_node_cap(node_id) for node_id in ms_df_.nodeid.unique()}
    hosts = [{"name": node_id, "cap": cap} for node_id, cap in node_caps.items()]
    print(f"Done host {len(hosts)}/{len(hosts)}")

    # Build tenant info
    msnames = ms_df_.msname.unique()
    tenants = {
        msname: {"name": msname, "load": 0, "fshareload": 0}
        for msname in msnames
    }
    print(f"Done tenant {len(tenants)}/{len(tenants)}")

    # Get one row per msinstanceid
    workers = unique_instances[["msinstanceid", "nodeid", "msname"]].rename(
        columns={"msinstanceid": "name", "nodeid": "host", "msname": "tenant"}
    ).to_dict("records")
    print(f"Done generating {len(workers)} workers")

    # Count number of workers per host
    host_counts = unique_instances["nodeid"].value_counts().to_dict()

    # Assign fshareload to each worker
    unique_instances["worker_share"] = unique_instances["nodeid"].map(
        lambda nid: node_caps[nid] / host_counts[nid]
    )

    # Group by tenant and sum worker shares
    fshare_per_tenant = unique_instances.groupby("msname")["worker_share"].sum()

    # First pass: assign baseline load of 80% of fair share to all tenants
    for tenant_name, fshare in fshare_per_tenant.items():
        tenants[tenant_name]["fshareload"] = fshare
        tenants[tenant_name]["load"] = (default_load_pct / 100.0) * fshare

    # Second pass: randomly select num_spiking tenants and set their load to 1000% of fair share
    all_tenant_names = list(tenants.keys())
    num_spiking = int(len(all_tenant_names) * pct_of_svc_spiking / 100.0)
    num_spiking_actual = min(num_spiking, len(all_tenant_names))
    spiking_tenants = random.sample(all_tenant_names, num_spiking_actual)
    for tenant_name in spiking_tenants:
        tenants[tenant_name]["load"] = 1000.0 * tenants[tenant_name]["fshareload"]

    print(f"Done fshareload. Spiking tenants: {num_spiking_actual}/{len(all_tenant_names)}")

    return hosts, list(tenants.values()), workers, node_caps


def run_with_timeout(ms_df_0, pct_of_svc_spiking, default_load_pct):
    hosts, tenants, workers, node_caps = get_state(ms_df_0, pct_of_svc_spiking, default_load_pct=default_load_pct)
    # return hosts, tenants, workers, node_caps, gs_g.run_from_json(hosts, tenants, workers)
    return hosts, tenants, workers, node_caps, None #gs_g.run_from_json(hosts, tenants, workers)


def get_results_stats(tenants, results):
    tenants_results = results["result"]
    cluster_util = 0.0
    n_tenants_demand_met = 0
    tenants_row_data = []
    for tenant in tenants:
        tenant_name = tenant["name"]
        tenant_result = tenants_results[tenant_name]
        tenant_load = tenant["load"]
        tenant_util = sum(tenant_result.values())
        tenants_row_data.append((tenant_name, tenant_load, tenant_util))
        cluster_util += tenant_util
        if abs(tenant_load - tenant_util) < 0.01:
            n_tenants_demand_met += 1

    return cluster_util, n_tenants_demand_met, tenants_row_data


def run_for_spike_count(ms_df_0: pd.DataFrame, pct_of_svc_spiking: int, default_load_pct: float = 80.0):
    timeout_seconds = 300000  # 5 minutes

    while True:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_with_timeout, ms_df_0, pct_of_svc_spiking, default_load_pct)
            try:
                hosts, tenants, workers, node_caps, global_result = future.result(timeout=timeout_seconds)
                break  # success, exit loop
            except concurrent.futures.TimeoutError:
                print("Timed out. Retrying...")

    cluster_cap = sum(node_caps.values())

    local_result = gs_l.run_from_json(hosts, tenants, workers)
    local_cluster_util, local_n_tenants_demand_met, local_tenants_row_data = get_results_stats(tenants, local_result)
    local_demand_meet_percentage = (local_n_tenants_demand_met / len(tenants)) * 100
    print(f"Local - Cluster Util: {local_cluster_util:.2f}, Tenants Demand Met: {local_n_tenants_demand_met}/{len(tenants)} ({local_demand_meet_percentage:.2f}%)")
    
    global_result = local_result if global_result is None else global_result
    
    global_cluster_util, global_n_tenants_demand_met, global_tenants_row_data = get_results_stats(tenants, global_result)
    global_demand_meet_percentage = (global_n_tenants_demand_met / len(tenants)) * 100
    print(f"Global - Cluster Util: {global_cluster_util:.2f}, Tenants Demand Met: {global_n_tenants_demand_met}/{len(tenants)} ({global_demand_meet_percentage:.2f}%)")

    cluster_imprv = (global_cluster_util - local_cluster_util) / local_cluster_util * 100 if local_cluster_util > 0 else 0

    return cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage, global_cluster_util, local_cluster_util, cluster_cap, global_tenants_row_data, local_tenants_row_data


def main():

    ms_df_0 = pd.read_csv('ms_df_timestamp_0.csv')

    data = []
    output_file_name = "alibaba_cluster_exp_spike_results_comprehensive_old_obj_new_local"
    output_file = f"{output_file_name}.csv"
    tenant_output_file = f"{output_file_name}_tenants.csv"

    # spike_counts = [0, 0.01, 0.1, 0.2, 0.5]
    # spike_counts = [0.1, 0.5, 0.75, 1, 2, 3, 10, 20, 50, 100]
    # spike_counts = [0.1, 0.5, 0.75, 1, 2, 3, 10, 20, 50, 100]
    spike_counts = [3.0]
    print(spike_counts)

    default_load_pct = 50.0

    for n_spike, pct_of_svc_spiking in enumerate(spike_counts):
        print(f"Running for pct_of_svc_spiking={pct_of_svc_spiking}...")
        cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage, global_cluster_util, local_cluster_util, cluster_cap, global_tenants_row_data, local_tenants_row_data = run_for_spike_count(ms_df_0, pct_of_svc_spiking, default_load_pct)
        
        print(f"Spiking Services: {pct_of_svc_spiking}, Cluster Improvement: {cluster_imprv:.2f}%, Global Demand Meet: {global_demand_meet_percentage:.2f}%, Local Demand Meet: {local_demand_meet_percentage:.2f}%")

        row = {
            "default_load_pct": default_load_pct,
            "pct_of_svc_spiking": pct_of_svc_spiking,
            "cluster_imprv": cluster_imprv,
            "global_demand_meet_percentage": global_demand_meet_percentage,
            "local_demand_meet_percentage": local_demand_meet_percentage,
            "global_cluster_util": global_cluster_util,
            "local_cluster_util": local_cluster_util,
            "cluster_cap": cluster_cap
        }
        data.append(row)

        write_header = not os.path.exists(output_file)
        pd.DataFrame([row]).to_csv(output_file, mode='a', header=write_header, index=False)

        # Also write tenant-level data
        df_global = pd.DataFrame(global_tenants_row_data, columns=["tenant_name", "tenant_load", "tenant_util"])
        df_global["default_load_pct"] = default_load_pct
        df_global["pct_of_svc_spiking"] = pct_of_svc_spiking
        df_global["lb_type"] = "global"

        df_local = pd.DataFrame(local_tenants_row_data, columns=["tenant_name", "tenant_load", "tenant_util"])
        df_local["default_load_pct"] = default_load_pct
        df_local["pct_of_svc_spiking"] = pct_of_svc_spiking
        df_local["lb_type"] = "local"
        
        tenant_data = pd.concat([df_global, df_local], ignore_index=True)
        tenant_data.to_csv(tenant_output_file, mode='a', header=not os.path.exists(tenant_output_file), index=False)

        os.system(f"curl -d '{n_spike}/ {len(spike_counts)} Done | Spike value: {pct_of_svc_spiking}%' ntfy.sh/mplb")
        
main()