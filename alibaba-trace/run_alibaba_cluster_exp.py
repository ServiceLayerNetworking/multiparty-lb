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


def get_state(ms_df_: pd.DataFrame, mean_ms_util: int, variation_from_mean: int = 50) -> tuple[list[dict], list[dict], list[dict]]:
    
    unique_instances = ms_df_.drop_duplicates(subset="msinstanceid").copy()
    node_msinstance_count = unique_instances.groupby("nodeid").count()["msinstanceid"].to_dict()
    
    def get_node_cap(node_id: str) -> int:
        return node_msinstance_count[node_id] * 10

    def get_ms_load(msname: str, fshare: float) -> int:
        # return (np.random.exponential(scale=mean_ms_util) / 100.0) * fshare
        return (random.randint(
            max(mean_ms_util - variation_from_mean, 0),
            mean_ms_util+variation_from_mean) / 100.0) * fshare

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

    for tenant_name, fshare in fshare_per_tenant.items():
        tenants[tenant_name]["fshareload"] = fshare
        tenants[tenant_name]["load"] = get_ms_load(tenant_name, fshare)

    print("Done fshareload")

    return hosts, list(tenants.values()), workers

def run_with_timeout(ms_df_0, mean_ms_util, variation_from_mean):
    hosts, tenants, workers = get_state(ms_df_0, mean_ms_util, variation_from_mean)
    return hosts, tenants, workers, gs_g.run_from_json(hosts, tenants, workers)

def run_for_mean_convulated(ms_df_0:pd.DataFrame, mean_ms_util: int, variation_from_mean: int = 50):
    timeout_seconds = 300000  # 5 minutes

    while True:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_with_timeout, ms_df_0, mean_ms_util, variation_from_mean)
            try:
                hosts, tenants, workers, global_result = future.result(timeout=timeout_seconds)
                break  # success, exit loop
            except concurrent.futures.TimeoutError:
                print("Timed out. Retrying...")
                
    local_result = gs_l.run_from_json(hosts, tenants, workers)
    
    alibaba_topo = ms_df_0.drop_duplicates(subset="msinstanceid").copy()
    
    global_result_ms_instance_utils = {msinstance: util for ms, msinstanceutils in global_result["result"].items() for msinstance, util in msinstanceutils.items()}
    alibaba_topo['global_util'] = alibaba_topo['msinstanceid'].apply(lambda msinstance: global_result_ms_instance_utils[msinstance])
    
    local_result_ms_instance_utils = {msinstance: util for ms, msinstanceutils in local_result["result"].items() for msinstance, util in msinstanceutils.items()}
    alibaba_topo['local_util'] = alibaba_topo['msinstanceid'].apply(lambda msinstance: local_result_ms_instance_utils[msinstance])
    
    unique_instances = ms_df_0.drop_duplicates(subset="msinstanceid").copy()
    node_msinstance_counts = unique_instances.groupby("nodeid").count()["msinstanceid"].to_dict()
    node_caps = {node: node_msinstance_count * 10.0 for node, node_msinstance_count in node_msinstance_counts.items()}

    alibaba_node_df = alibaba_topo.groupby('nodeid').agg({'global_util': 'sum', 'local_util': 'sum'}).reset_index()
    alibaba_node_df["cap"] = alibaba_node_df["nodeid"].apply(lambda nodeid: node_caps[nodeid])
    alibaba_node_df
    gu = alibaba_node_df["global_util"].sum() # / (len(alibaba_node_df["global_util"]) * 100)
    lu = alibaba_node_df["local_util"].sum() # / (len(alibaba_node_df["global_util"]) * 100)
    cluster_imprv = (gu - lu) / lu * 100
    
    alibaba_ms_df = alibaba_topo.groupby('msname').agg({'global_util': 'sum', 'local_util': 'sum'}).reset_index()
    
    alibaba_ms_df["improvement"] = (alibaba_ms_df["global_util"] - alibaba_ms_df["local_util"]) / alibaba_ms_df["local_util"] * 100
    tenant_loads = {t["name"]: t["load"] for t in tenants}
    alibaba_ms_df["demand"] = alibaba_ms_df["msname"].apply(lambda n: tenant_loads[n])
    
    global_demand_meet_percentage = (len(alibaba_ms_df[(alibaba_ms_df["demand"] - alibaba_ms_df["global_util"]) < 0.01]) / len(alibaba_ms_df) * 100)
    local_demand_meet_percentage = (len(alibaba_ms_df[(alibaba_ms_df["demand"] - alibaba_ms_df["local_util"]) < 0.01]) / len(alibaba_ms_df) * 100)
    
    return cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage

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
                    
def run_for_mean(ms_df_0:pd.DataFrame, mean_ms_util: int, variation_from_mean: int = 50):
    timeout_seconds = 300000  # 5 minutes

    while True:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_with_timeout, ms_df_0, mean_ms_util, variation_from_mean)
            try:
                hosts, tenants, workers, global_result = future.result(timeout=timeout_seconds)
                break  # success, exit loop
            except concurrent.futures.TimeoutError:
                print("Timed out. Retrying...")
                
    local_result = gs_l.run_from_json(hosts, tenants, workers)
    # global_result = local_result
    
    local_cluster_util, local_n_tenants_demand_met = get_results_stats(tenants, local_result)
    global_cluster_util, global_n_tenants_demand_met = get_results_stats(tenants, global_result)
    
    cluster_imprv = (global_cluster_util - local_cluster_util) / local_cluster_util * 100 if local_cluster_util > 0 else 0
    global_demand_meet_percentage = (global_n_tenants_demand_met / len(tenants)) * 100
    local_demand_meet_percentage = (local_n_tenants_demand_met / len(tenants)) * 100
    
    return cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage

def main():
    
    ms_df_0 = pd.read_csv('ms_df_timestamp_0.csv')
    
    data = []
    
    means = [50]
    print(means)
    # input()
    
    for mean_ms_util in means:
        cluster_imprv, global_demand_meet_percentage, local_demand_meet_percentage = run_for_mean(ms_df_0, mean_ms_util, variation_from_mean=50)
        print(f"Mean MS Util: {mean_ms_util}, Cluster Improvement: {cluster_imprv:.2f}%, Global Demand Meet Percentage: {global_demand_meet_percentage:.2f}%, Local Demand Meet Percentage: {local_demand_meet_percentage:.2f}%")
        
        data.append({
            "mean_ms_util": mean_ms_util,
            "variation_from_mean": 50,
            "cluster_imprv": cluster_imprv,
            "global_demand_meet_percentage": global_demand_meet_percentage,
            "local_demand_meet_percentage": local_demand_meet_percentage
        })
    
    df = pd.DataFrame(data)
    df.to_csv("alibaba_cluster_exp_results1.csv", index=False)
    
main()
