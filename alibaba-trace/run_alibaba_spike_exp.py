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


def get_state(ms_df_: pd.DataFrame, pct_of_svc_spiking: int) -> tuple[list[dict], list[dict], list[dict]]:

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
        tenants[tenant_name]["load"] = 0.80 * fshare

    # Second pass: randomly select num_spiking tenants and set their load to 1000% of fair share
    all_tenant_names = list(tenants.keys())
    num_spiking = int(len(all_tenant_names) * pct_of_svc_spiking / 100.0)
    num_spiking_actual = min(num_spiking, len(all_tenant_names))
    spiking_tenants = random.sample(all_tenant_names, num_spiking_actual)
    for tenant_name in spiking_tenants:
        tenants[tenant_name]["load"] = 1000.0 * tenants[tenant_name]["fshareload"]

    print(f"Done fshareload. Spiking tenants: {num_spiking_actual}/{len(all_tenant_names)}")

    return hosts, list(tenants.values()), workers


def run_with_timeout(ms_df_0, pct_of_svc_spiking):
    hosts, tenants, workers = get_state(ms_df_0, pct_of_svc_spiking)
    return hosts, tenants, workers, gs_g.run_from_json(hosts, tenants, workers)


def get_results_stats(tenants, results):
    tenants_results = results["result"]
    cluster_util = 0.0
    n_tenants_demand_met = 0
    for tenant in tenants:
        tenant_name = tenant["name"]
        tenant_result = tenants_results[tenant_name]
        tenant_load = tenant["load"]
        tenant_util = sum(tenant_result.values())
        cluster_util += tenant_util
        if abs(tenant_load - tenant_util) < 0.01:
            n_tenants_demand_met += 1

    return cluster_util, n_tenants_demand_met


def run_for_spike_count(ms_df_0: pd.DataFrame, pct_of_svc_spiking: int):
    timeout_seconds = 300000  # 5 minutes

    while True:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_with_timeout, ms_df_0, pct_of_svc_spiking)
            try:
                hosts, tenants, workers, global_result = future.result(timeout=timeout_seconds)
                break  # success, exit loop
            except concurrent.futures.TimeoutError:
                print("Timed out. Retrying...")

    global_cluster_util, global_n_tenants_demand_met = get_results_stats(tenants, global_result)
    global_demand_meet_percentage = (global_n_tenants_demand_met / len(tenants)) * 100
    print(f"Global - Cluster Util: {global_cluster_util:.2f}, Tenants Demand Met: {global_n_tenants_demand_met}/{len(tenants)} ({global_demand_meet_percentage:.2f}%)")

    local_result = gs_l.run_from_json(hosts, tenants, workers)
    local_cluster_util, local_n_tenants_demand_met = get_results_stats(tenants, local_result)
    local_demand_meet_percentage = (local_n_tenants_demand_met / len(tenants)) * 100
    print(f"Local - Cluster Util: {local_cluster_util:.2f}, Tenants Demand Met: {local_n_tenants_demand_met}/{len(tenants)} ({local_demand_meet_percentage:.2f}%)")

    cluster_imprv = (global_cluster_util - local_cluster_util) / local_cluster_util * 100 if local_cluster_util > 0 else 0

    return cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage


def main():

    ms_df_0 = pd.read_csv('ms_df_timestamp_0.csv')

    data = []
    output_file = "alibaba_cluster_exp_spike_results.csv"

    # spike_counts = [0, 0.01, 0.1, 0.2, 0.5]
    spike_counts = [2, 3, 4]
    print(spike_counts)

    for pct_of_svc_spiking in spike_counts:
        print(f"Running for pct_of_svc_spiking={pct_of_svc_spiking}...")
        cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage = run_for_spike_count(ms_df_0, pct_of_svc_spiking)
        print(f"Spiking Services: {pct_of_svc_spiking}, Cluster Improvement: {cluster_imprv:.2f}%, Global Demand Meet: {global_demand_meet_percentage:.2f}%, Local Demand Meet: {local_demand_meet_percentage:.2f}%")

        row = {
            "pct_of_svc_spiking": pct_of_svc_spiking,
            "cluster_imprv": cluster_imprv,
            "global_demand_meet_percentage": global_demand_meet_percentage,
            "local_demand_meet_percentage": local_demand_meet_percentage
        }
        data.append(row)

        write_header = not os.path.exists(output_file)
        pd.DataFrame([row]).to_csv(output_file, mode='a', header=write_header, index=False)


main()
