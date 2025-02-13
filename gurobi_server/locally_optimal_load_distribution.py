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
        
    def __str__(self):
        return f"{self.name}: tenant={self.tenant}, host={self.host}"

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
    
    elapsed_time = 0
    per_job_curr_time = 0
    current_jobs = list(sorted_jobs)
    
    for job_name, job_finish_time in sorted_jobs:
        
        print(job_name, job_finish_time)
        
        print(elapsed_time, per_job_curr_time, len(current_jobs))
        
        prev_elapsed_time = elapsed_time
        
        # this is the time at which the job finishes processing
        elapsed_time += (job_finish_time - per_job_curr_time) * len(current_jobs)
        
        print(elapsed_time)
        
        # check if we're over the total time
        if elapsed_time > total_time:
            
            print("we came here")
            
            time_left = total_time - prev_elapsed_time
            # this time will be divided among the remaining jobs
            per_job_curr_time += time_left / len(current_jobs)
            # add all remaining jobs to the job stats
            for job_name, job_finish_time in current_jobs:
                job_stats[job_name] = (per_job_curr_time, total_time)
            break
        
        else:
        
            # if we're not over time, this is the amount of the job that was processed
            per_job_curr_time = job_finish_time
            
            # add the job to the job stats
            job_stats[job_name] = (per_job_curr_time, elapsed_time)
    
            current_jobs = current_jobs[1:]
        
    return job_stats

print(get_max_min_processing_times(2, {
        "a": 0.0,
        "b": 0.1,
        "c": 0.1,
        "d": 0.3,
        "e": 0.76,
        "f": 0.75,
    }))

# Linear Single Combined Objective
def get_locally_optimal_load_distribution(
    hosts: List[g.Host],
    tenants: List[g.Tenant],
    workers: List[g.Worker]) -> Dict[str, Dict[str, float]]:
    
    """
    Algorithm:
    - Initialize each worker with a processing rate of 1.0
    - Repeat the following steps until convergence (i.e. no worker's processing rate changes in a step):
        - For each tenant, split its load among its workers in proportion to their processing rate
        - At each host, calculate max-min fair share of load for each worker
        - Calculate the processing rate of each worker
    - Output the result
    """
    
    # Initialize each worker with a processing rate of 1.0
    for worker in workers:
        worker.processing_rate = 1.0
        
    # Repeat the following steps until convergence (i.e. no worker's processing rate changes in a step):
    while True:
        
        # For each tenant, split its load among its workers in proportion to their processing rate
        for tenant in tenants:
            tenant_workers = [worker for worker in workers if worker.tenant == tenant.name]
            total_load = sum(worker.processing_rate for worker in tenant_workers)
            for worker in tenant_workers:
                worker.load = tenant.load * worker.processing_rate / total_load
        
        # At each host, calculate max-min fair share of load for each worker
        for host in hosts:
            host_workers = [worker for worker in workers if worker.host == host.name]
            worker_loads = [(worker.name, worker.load) for worker in host_workers]
            
            max_min_fair_shares = get_max_min_fair_shares(host.cap, worker_loads)
            
            
            
        
    
    
    
    
    
    
    
    
    
    
    
    results = {}
    for worker in workers:
        if worker.tenant not in results:
            results[worker.tenant] = {}
            results[worker.tenant][worker.name] = 0.0
        else:
            results[worker.tenant][worker.name] = 0.0
    to_return = {
        "status": GRB.OPTIMAL,
        "result": results
    }
    
    print(to_return)
        
    return to_return
    

# get result from json input (from cc)
def run_from_json(hosts, tenants, workers):
    hosts = [Host(h["name"], h["cap"]) for h in hosts]
    tenants = [Tenant(t["name"], t["load"]) for t in tenants]
    workers = [Worker(w["name"], w["tenant"], w["host"]) for w in workers]
    
    to_return = get_locally_optimal_load_distribution(hosts, tenants, workers)

    return to_return    

if __name__ == '__main__':
    
    pass
    
    # if len(sys.argv) > 1:
    #     if sys.argv[1] == "-f":
            
    #         filename = sys.argv[2]
            
    #         with open(filename, "r") as f:
    #             input_json = f.read()
            
    #         start_time = time()
    #         input = json.loads(input_json)
    #         print("Input:", input)
            
    #         hosts, tenants, workers = input[0], input[1], input[2]
    #         output = run_from_json(hosts, tenants, workers)
            
    #         time_taken = time() - start_time
    #         print(f"{time_taken*1000:.2f} ms")
            
    #         output_json = dumps(output)
            
    #         with open(filename + "_output", "w") as f:
    #             f.write(output_json)
              
    #     else:
    #         print("Invalid argument, use -f to run sample json")
    # else:
    #     print("No argument provided, use -f to run sample json")