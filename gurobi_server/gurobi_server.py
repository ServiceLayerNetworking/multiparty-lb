import numpy as np
import gurobipy as gp
from gurobipy import GRB
import os
from time import time
from flask import Flask, request
from json import dumps
import json
from typing import Tuple, List, Dict

Tenant_Min = Dict[str, gp.Var]
Tenant_Consumed = Dict[str, gp.Var]
Tenant_Load = Dict[str, gp.Var]

previous_w: Dict[str,float] = {}

N_WORKERS_EXPONENTIAL_DISTR_LAMBDA = 17
WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA = 0.7
HOST_CAPACITY = 1.0

class Host:
    def __init__(self, name: str, cap: float):
        self.name: str = name
        self.cap: str = cap
        self.worker_ids: List[int] = []
        
    def __str__(self):
        return f"{self.name}: cap={self.cap}, n_workers={len(self.worker_ids)}"
        
class Tenant:
    def __init__(self, name: str, load: float, fshare: float = 0.0):
        self.name: str = name
        self.load: float = load
        self.fshareload: float = fshare
        
    def __str__(self):
        return f"{self.name}: load={self.load}, fshareload={self.fshareload}"

class Worker:
    def __init__(self, name: str, tenant: str, host: str, tenant_id: int = -1):
        self.name: str = name
        self.tenant: str = tenant
        self.tenant_id: int = tenant_id
        self.host: str = host
        
    def __str__(self):
        return f"{self.name}: tenant={self.tenant}, host={self.host}"

def run_generic_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> str:
    
    global previous_w
    
    # =========================== Begin Optimization ===========================
    
    # MIP  model formulation
    m = gp.Model("lb")
    
    #  ============================= Set Variables =============================
    
    # set host capacity for each host
    cap = {}
    for h in _hosts:
        cap[h.name] = m.addVar(lb=h.cap, ub=h.cap, vtype=GRB.CONTINUOUS,
                        name=f"cap_{h.name}")
    
    # # set variables for the tenant loads
    # t = {}
    # for tenant in _tenants:
    #     t[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, 
    #                               vtype=GRB.CONTINUOUS, name=f"t_{tenant.name}")
    
    # set variables for the workers
    w = {}   
    for worker in _workers:
        w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                           name=f"w_{worker.name}")
    
    print(w)

    t_min = {}
    for tenant in _tenants:
        t_min_value = min(tenant.fshareload, tenant.load)
        t_min[tenant.name] = m.addVar(lb=t_min_value, ub=t_min_value,
                                      vtype=GRB.CONTINUOUS,
                                 name=f"t_min_{tenant.name}")
        
    t_consumed = {}
    for tenant in _tenants:
        print(f"{tenant.name}: (lb: {min(tenant.fshareload, tenant.load)}, ub: {tenant.load})")
        # t_consumed[tenant.name] = m.addVar(lb=0.0,
        #                                    vtype=GRB.CONTINUOUS,
        #                          name=f"t_consumed_{tenant.name}")
        # We could also add the constraints here instead of adding them later, maybe that saves time in optimization
        t_consumed[tenant.name] = m.addVar(lb=min(tenant.fshareload, tenant.load), 
                                           ub=tenant.load,
                                           vtype=GRB.CONTINUOUS,
                                 name=f"t_consumed_{tenant.name}")
    
    t_excess_consumed = {}
    for tenant in _tenants:
        t_excess_consumed[tenant.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"t_excess_consumed_{tenant.name}")
    
    t_log_excess_consumed = {}
    for tenant in _tenants:
        t_log_excess_consumed[tenant.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                                      lb=-GRB.INFINITY,
                                                      ub=GRB.INFINITY,
                                 name=f"t_log_excess_consumed_{tenant.name}")
    
    one = m.addVar(lb=1.0, ub=1.0, vtype=GRB.CONTINUOUS, name="one")
    
    # ======================= Set Utilization Objective ========================
    
    sum_fshareloads = sum(tenant.fshareload for tenant in _tenants)
    
    weighted_sum_of_t_excess_consumption = gp.quicksum(
        ((tenant.fshareload / sum_fshareloads) * t_log_excess_consumed[tenant.name]
         for tenant in _tenants))
    
    # sum_workers = gp.quicksum((w[worker.name] for worker in _workers))
         
    m.setObjective(weighted_sum_of_t_excess_consumption, GRB.MAXIMIZE)
    
    # ============================ Set Constraints =============================
    
    # for each tenant, set t_log_excess_consumed = log(t_consumed)
    for tenant in _tenants:
        m.addGenConstrLog(t_excess_consumed[tenant.name],
                          t_log_excess_consumed[tenant.name])
    
    # for each tenant, set t_excess_consumed = t_consumed - t_min
    for tenant in _tenants:
        m.addConstr(
            t_excess_consumed[tenant.name] == 
            t_consumed[tenant.name] - t_min[tenant.name],
            name=f"t_excess_consumed_{tenant.name}")
    
    # at each h, sum(w ∈ h) <= cap
    for host in _hosts:
        m.addConstr(gp.quicksum(
            (w[worker.name] for worker in _workers if worker.host == host.name)) 
                    <= cap[host.name],
                    name=f"h_{host.name}")
        
    # for each tenant t, set t_consumed = sum(w ∈ t)
    for tenant in _tenants:
        m.addConstr(
            t_consumed[tenant.name] == gp.quicksum(
                (w[worker.name]
                for worker in _workers if worker.tenant == tenant.name)),
            name=f"t_consumed_{tenant.name}")
        
    # # at each t, t_consumed <= t
    # for tenant in _tenants:
    #     m.addConstr(
    #         t_consumed[tenant.name] <= tenant.load,
    #         name=f"t_upper_{tenant.name}")
    
    # # for each tenant, t_consumed >= t_min
    # for tenant in _tenants:
    #     m.addConstr(
    #         t_consumed[tenant.name] >= min(tenant.fshareload, tenant.load),
    #         name=f"t_lower_{tenant.name}")
    
    # ============================== Optimize! =================================
    
    m.optimize()
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
    
        # ==================== Variance Objective Optimization =====================
        
        t_consumed_min = {}
        for tenant in _tenants:
            t_consumed_min[tenant.name] = m.addVar(
                lb=vars[f"t_consumed_{tenant.name}"], 
                ub=vars[f"t_consumed_{tenant.name}"], 
                vtype=GRB.CONTINUOUS,
                name=f"t_consumed_min_{tenant.name}")
            
        # for each tenant, t_consumed_min <= t_consumed
        for tenant in _tenants:
            m.addConstr(
                t_consumed_min[tenant.name] <= t_consumed[tenant.name],
                name=f"t_consumed_min_{tenant.name}")
        
        # set spare caps
        sp = {}
        for host in _hosts:
            sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
            
        # for each host, sp = (cap - sum(w))
        for host in _hosts:
            m.addConstr(
                sp[host.name] == (cap[host.name] - gp.quicksum(
                    (w[worker.name] 
                    for worker in _workers if worker.host == host.name))),
                name=f"sp_{host.name}")
            
        # Compute the mean of spare caps
        mean = (1 / len(sp)) * gp.quicksum((sp[host.name] for host in _hosts))

        # Add the variance objective: minimize (1/n) * sum((x_i - mean)^2)
        variance = (1 / len(sp)) * gp.quicksum(
            (sp[host.name] - mean) * (sp[host.name] - mean) for host in _hosts)
            
        m.setObjective(variance, GRB.MINIMIZE)
        
        m.optimize()
        
    
        if m.Status == GRB.OPTIMAL:
            
            # =========================== Optimization minimize distanc between weights ============================
            
            # do this only if you have all the previous weights
            was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
            
            if was_previous_the_same_topology:
                
                print("Same topology;", "doing the distance optimization")
            
                # set that the variance objective is no more as much as what it was in the last optimization
                max_var = m.ObjVal
                m.addConstr(variance <= max_var)
                
                n = len(_workers)
                abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
                
                # set the new objective to minimize the distance between the weights
                for i, worker in enumerate(_workers):
                    m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name])
                    m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name])
                
                m.setObjective(gp.quicksum(abs_diff[i] for i in range(n)), GRB.MINIMIZE)
                
                m.optimize()
                
                print("Same topology;", "did the distance optimization")
                
            else:
                
                print("Different topology;", "adding distance objective with 0 weight") 
                
                # set that the variance objective is no more as much as what it was in the last optimization
                max_var = m.ObjVal
                m.addConstr(variance <= max_var)
                
                n = len(_workers)
                abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
                
                # set the new objective to minimize the distance between the weights
                for i, worker in enumerate(_workers):
                    m.addConstr(abs_diff[i] >= w[worker.name] - 0.0)
                    m.addConstr(abs_diff[i] >= 0.0 - w[worker.name])
                
                m.setObjective(gp.quicksum(abs_diff[i] for i in range(n)), GRB.MINIMIZE)
                
                m.optimize()
                
                print("Different topology;", "did the distance optimization")
    
    # =========================== Done Optimization ============================
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
        
    if m.Status == GRB.OPTIMAL:        
        
        vars = {v.varName: v.x for v in m.getVars()}
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = vars[f"w_{worker.name}"]
            else:
                results[worker.tenant][worker.name] = vars[f"w_{worker.name}"]
        to_return = {
            "status": m.Status,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w_{worker.name}"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": m.Status,
            "result": results
        }
        
        print(to_return)
        
        return to_return

# run generic model from json input (from cc)
def run_from_json(hosts, tenants, workers):
    hosts = [Host(h["name"], h["cap"]) for h in hosts]
    tenants = [Tenant(t["name"], t["load"], t["fshareload"]) for t in tenants]
    workers = [Worker(w["name"], w["tenant"], w["host"]) for w in workers]
    
    # global previous_w
    # previous_w = {'app1-node1': 105.6, 'app1-node2': 95.4, 'app2-node1': 95.4, 'app2-node2': 105.6}
    
    # to_return = run_generic_linear_single_objective_model_nov15_abs_diff(hosts, tenants, workers)[0]
    
    # # print(previous_w)
    
    # return to_return
    return run_generic_model(hosts, tenants, workers)
    
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def gurobi_server():
    
    print("======================reached here")
    
    if request.method == "GET":
        raise Exception("GET method not allowed")
        
    elif request.method == "POST":
        
        start_time = time()
        print("reached here")
        request_data = request.get_json(force=False)
        print("Received:", request_data)
        hosts, tenants, workers = request_data[0], request_data[1], request_data[2]
        
        variables = run_from_json(hosts, tenants, workers)
        
        time_taken = time() - start_time
        print(f"{time_taken*1000:.2f} ms")
        
        return dumps(variables)  

@app.route('/reset', methods=['GET'])
def reset_weights():
    
    global previous_w
    previous_w = {}
    
    return "Weights reset!"

import sys

import logging
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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
            
            with open(filename + "_output", "w") as f:
                f.write(output_json)
              
        else:
            print("Invalid argument, use -f to run sample json")
            
    else:
        print("======================reached here")
        app.run(host="localhost", port=5000, debug=True)