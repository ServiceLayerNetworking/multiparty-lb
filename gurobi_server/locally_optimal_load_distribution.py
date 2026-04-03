from collections import defaultdict
import numpy as np
import gurobipy as gp
from gurobipy import GRB
import os
from time import time
from flask import Flask, request
from json import dumps
import json
from typing import Tuple, List, Dict
import sys
import logging

import gurobi_server as g

class Host:
    def __init__(self, name: str, cap: float):
        self.name: str = name
        self.cap: str = cap
        self.worker_ids: List[int] = []
        
    def __str__(self):
        return f"{self.name}: cap={self.cap}, n_workers={len(self.worker_ids)}"
        
class Tenant:
    def __init__(self, name: str, load: float):
        self.name: str = name
        self.load: float = load
        
    def __str__(self):
        return f"{self.name}: load={self.load}, fshareload={self.fshareload}"

class Worker:
    def __init__(self, name: str, tenant: str, host: str):
        self.name: str = name
        self.tenant: str = tenant
        self.host: str = host
        self.load: float = 0.0
        self.processing_rate: float = 1.0
        self.processed: float = 0.0
        
    def __str__(self):
        return f"{self.name}: load={self.load} processing_rate={self.processing_rate}"

def get_max_min_processing_times(total_time: float, job_times: Dict[str, float]) -> Dict[str, Tuple[float, float]]:
    
    """
    Algorithm:
    - All jobs start processing at t=0
    - An infinite number of jobs can be processed simultaneously
    - If n jobs are being processed at time t, each job's processing rate is 1/n
    - We want to output the time at which each job finishes processing, and the amount that was processed
    
    Now, here's how to implement this algorithm:
    - Sort the jobs by job times in ascending order
    - Start current time = 0
    - Loop through job times:
        - At 
    """
    """
    curr_jobs = [a: 0.1, b: 0.3, c: 1.5]
    c_t = 0
    e_t = 0
    
    a: 0.1
    c_t += 0.1*len(curr_jobs)
        => c_t == 0.3
    e_t = 0.1
    remove a from curr_jobs
        => c_j == [b: 0.3, c: 1.5]
    
    b: 0.3
    c_t += (b-e_t)*len(curr_jobs)
        => c_t == (0.3-0.1)*2 == 0.7
    e_t = 0.3
    remove b from curr_jobs
        => c_j == [c: 1.5]
        
    b1: 0.3
    c_t += (b1-e_t)*len(curr_jobs)
        => c_t == (0.3-0.1)*2 == 0.7
    e_t = 0.3
    remove b1 from curr_jobs, output e_t and c_t for b1
        => c_j == [c: 1.5]
        
    c: 1.8
    c_t += (c-e_t)*len(curr_jobs)
        => c_t == 0.7+(1.8-0.3)*1 == 2.2
        if c_t > total_time:
            excess_time = c_t - total_time
            => excess_time == 2.2 - 2.0 == 0.2
            e_t = c - excess_time/len(curr_jobs)
            output the e_t for c, and all jobs that are still in curr_jobs, and their completion time is total_time
    e_t = 1.5
    remove c from curr_jobs
        => c_j == []
    
    # what if one job is 0
    # what if two jobs have the same time 
    # what if there are more jobs that can be processed in time
     
    """
    
    sorted_jobs = sorted(job_times.items(), key=lambda item: item[1])
    
    job_stats = {}
    
    curr_time = 0
    per_job_curr_time = 0
    current_jobs = list(sorted_jobs)
    
    # loop through the jobs in ascending order of job times
    for job_name, job_finish_time in sorted_jobs:
        
        prev_curr_time = curr_time
        
        # this is the wallclock time at which this job will finish processing
        curr_time += (job_finish_time - per_job_curr_time) * len(current_jobs)
        
        # if we're not over time:
        if curr_time <= total_time:
            # if we're not over time, this is the amount of the job that was processed
            per_job_curr_time = job_finish_time
        
        # if we're over the total time
        else:
            
            # what time did we have left after the last job finished processing?
            time_left = total_time - prev_curr_time
            
            # this time will be divided among the remaining jobs
            per_job_curr_time += time_left / len(current_jobs)
            
            # current time is the total time
            curr_time = total_time
        
        # add the job to the job stats
        job_stats[job_name] = (per_job_curr_time, curr_time)

        # remove the job from the current jobs
        current_jobs = current_jobs[1:]
        
    return job_stats

print(get_max_min_processing_times(2, {
        "a": 0.0,
        "b": 0.1,
        "c": 0.1,
        "e": 1.72,
        "f": 1.25,
        "g": 1.25,
    }))

# Linear Single Combined Objective
def get_locally_optimal_load_distribution(
    hosts: List[g.Host],
    tenants: List[g.Tenant],
    workers: List[g.Worker]) -> Dict[str, Dict[str, float]]:
    
    # print([str(worker) for worker in workers])
    
    """
    Algorithm:
    - Initialize each worker with a processing rate of 1.0
    - Repeat the following steps until convergence (i.e. no worker's processing rate changes in a step) or a maximum number of iterations is reached:
        - For each tenant, split its load among its workers in proportion to their processing rate
        - At each host, calculate max-min fair share of load for each worker
        - Calculate the processing rate of each worker
    - Output the result
    """
    
    # Initialize each worker with a processing rate of 1.0
    for worker in workers:
        worker.processing_rate = 1.0
            
    max_iterations = 10_000
            
    # Repeat the following steps until convergence (i.e. no worker's processing rate changes in a step):
    for i in range(max_iterations):
        
        print(f"Iteration #{i}")
        
        # For each tenant, split its load among its workers in proportion to their processing rate
        for tenant in tenants:
            tenant_workers = [worker for worker in workers if worker.tenant == tenant.name]
            total_load = sum(worker.processing_rate for worker in tenant_workers)
            for worker in tenant_workers:
                worker.load = tenant.load * worker.processing_rate / total_load
        
        is_worker_processing_rate_changed = False
        
        # At each host, calculate max-min fair share of load for each worker
        for host in hosts:
            host_workers = {worker.name: worker for worker in workers if worker.host == host.name}
            worker_loads = {worker_name: worker.load for worker_name, worker in host_workers.items()}
            
            max_min_fair_shares = get_max_min_processing_times(host.cap, worker_loads)
            
            
            # convert the max_min_fair_shares to processing rates
            for worker_name, worker_stat in max_min_fair_shares.items():
                
                load_processed, time_to_process_load = worker_stat
                if time_to_process_load == 0:
                    processing_rate = 1.0
                else:
                    processing_rate = load_processed / time_to_process_load
                
                if host_workers[worker_name].processing_rate != processing_rate:
                    host_workers[worker_name].processing_rate = processing_rate
                    is_worker_processing_rate_changed = True
        
        # print([str(worker) for worker in workers])
        
        if not is_worker_processing_rate_changed:
            break
        
    # Output the result
    results = {}
    for worker in workers:
        if worker.tenant not in results:
            results[worker.tenant] = {}
            results[worker.tenant][worker.name] = worker.load
        else:
            results[worker.tenant][worker.name] = worker.load
    
    to_return = {
        "status": GRB.OPTIMAL,
        "result": results
    }
    
    print(to_return)
        
    return to_return
    
def get_locally_optimal_load_distribution_fast_processing_rate_based(
    hosts: List[g.Host],
    tenants: List[g.Tenant],
    workers: List[g.Worker],
    epsilon: float = 1e-6) -> Dict[str, Dict[str, float]]:
    
    for worker in workers:
        worker.processing_rate = 1.0
        worker.processed = 0.0

    max_iterations = 10_000

    # Pre-group workers by tenant and host for faster access
    tenant_to_workers = defaultdict(list)
    host_to_workers = defaultdict(dict)
    for worker in workers:
        tenant_to_workers[worker.tenant].append(worker)
        host_to_workers[worker.host][worker.name] = worker

    for _ in range(max_iterations):
        is_worker_processing_rate_changed = False

        # Step 1: Distribute load among tenant's workers proportionally
        for tenant in tenants:
            tenant_workers = tenant_to_workers[tenant.name]
            total_processing = sum(w.processing_rate for w in tenant_workers)
            if total_processing > 0:
                for worker in tenant_workers:
                    worker.load = tenant.load * worker.processing_rate / total_processing
            else:
                equal_load = tenant.load / len(tenant_workers)
                for worker in tenant_workers:
                    worker.load = equal_load

        # Step 2: Max-min fair share processing rate update
        for host in hosts:
            workers_on_host = host_to_workers[host.name]
            worker_loads = {name: worker.load for name, worker in workers_on_host.items()}
            fair_shares = get_max_min_processing_times(host.cap, worker_loads)
            
            for name, (processed, time) in fair_shares.items():
                new_rate = processed / time if time > 0 else 1.0
                worker = workers_on_host[name]
                worker.processed = processed
                if abs(worker.processing_rate - new_rate) > epsilon:
                    worker.processing_rate = new_rate
                    is_worker_processing_rate_changed = True

        if not is_worker_processing_rate_changed:
            break

    # Step 3: Collect results
    results = defaultdict(dict)
    for worker in workers:
        results[worker.tenant][worker.name] = worker.processed

    final_output = {
        "status": GRB.OPTIMAL,
        "result": dict(results)
    }

    # print(final_output)
    return final_output

def get_locally_optimal_load_distribution_fast(
    hosts: List[g.Host],
    tenants: List[g.Tenant],
    workers: List[g.Worker],
    epsilon: float = 1e-12,
    max_iterations: int = 10_000) -> Dict[str, Dict[str, float]]:
    
    for worker in workers:
        worker.processing_rate = 1.0
        worker.processed = 0.0

    # Pre-group workers by tenant and host for faster access
    tenant_to_workers = defaultdict(list)
    host_to_workers = defaultdict(dict)
    for worker in workers:
        tenant_to_workers[worker.tenant].append(worker)
        host_to_workers[worker.host][worker.name] = worker

    for i_iteration in range(max_iterations):
        is_worker_processed_changed = False
        
        print(f"Iteration #{i_iteration}")

        # Step 1: Distribute load among tenant's workers proportionally
        for tenant in tenants:
            tenant_workers = tenant_to_workers[tenant.name]
            total_processing = sum(w.processed for w in tenant_workers)
            if total_processing > 0:
                for worker in tenant_workers:
                    worker.load = tenant.load * (worker.processed / total_processing)
            else:
                equal_load = tenant.load / len(tenant_workers)
                for worker in tenant_workers:
                    worker.load = equal_load

        # Step 2: Max-min fair share processing rate update
        for host in hosts:
            workers_on_host = host_to_workers[host.name]
            worker_loads = {name: worker.load for name, worker in workers_on_host.items()}
            fair_shares = get_max_min_processing_times(host.cap, worker_loads)
            
            for name, (processed, time) in fair_shares.items():
                new_rate = processed / time if time > 0 else 1.0
                worker = workers_on_host[name]
                new_processed = processed
                if abs(worker.processed - new_processed) > epsilon:
                    is_worker_processed_changed = True
                worker.processed = new_processed

        if not is_worker_processed_changed:
            break

    # Step 3: Collect results
    results = defaultdict(dict)
    for worker in workers:
        results[worker.tenant][worker.name] = worker.processed

    final_output = {
        "status": GRB.OPTIMAL,
        "result": dict(results)
    }

    # print(final_output)
    return final_output


# get result from json input (from cc)
def run_from_json(hosts, tenants, workers):
    hosts = [Host(h["name"], h["cap"]) for h in hosts]
    tenants = [Tenant(t["name"], t["load"]) for t in tenants]
    workers = [Worker(w["name"], w["tenant"], w["host"]) for w in workers]
    
    # to_return = get_locally_optimal_load_distribution(hosts, tenants, workers)
    to_return = get_locally_optimal_load_distribution_fast(hosts, tenants, workers)

    return to_return

if __name__ == '__main__':
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "-f":
            
            filename = sys.argv[2]
            
            with open(filename, "r") as f:
                input_json = f.read()
            
            start_time = time()
            input = json.loads(input_json)
            print("Input:", input)
            
            hosts, tenants, workers = input[0], input[1], input[2]
            output = run_from_json(hosts, tenants, workers)
            
            time_taken = time() - start_time
            print(f"{time_taken*1000:.2f} ms")
            
            output_json = dumps(output)
            
            with open(filename + "_local_opt_output", "w") as f:
                f.write(output_json)
            
        else:
            print("Invalid argument, use -f to run sample json")
    else:
        print("No argument provided, use -f to run sample json")
        