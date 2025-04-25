import numpy as np
import gurobipy as gp
from gurobipy import GRB
import os
from time import time
import time
from flask import Flask, request
from json import dumps
import json
from typing import Tuple, List, Dict
import numpy as np
import pandas as pd
import sys

Tenant_Min = Dict[str, gp.Var]
Tenant_Consumed = Dict[str, gp.Var]
Tenant_Load = Dict[str, gp.Var]

previous_w: Dict[str,float] = {}
 
N_WORKERS_EXPONENTIAL_DISTR_LAMBDA = 17
WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA = 0.075 #0.7
HOST_CAPACITY = 1.0
OBJ1_WEIGHT = 0.9
OBJ2_WEIGHT = 0.1
OBJ3_EPSILON = 0.001

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
        self.tenant_id = -1
        
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

def get_topology(
    n_hosts: int, 
    ensure_one_worker_per_tenant_per_host: bool = False) -> Tuple[
        List[Host], List[Tenant], List[Worker], List[int]]:
    
    print(f"number of hosts: {n_hosts}")
    
    n_tenants = max([1, int(n_hosts * 0.65)])
    print(f"number of tenants: {n_tenants}")    
    
    n_workers_per_ms = list(map(int, np.random.exponential(
        N_WORKERS_EXPONENTIAL_DISTR_LAMBDA, size=n_tenants)))
    print(f"number of workers: {np.sum(n_workers_per_ms)}")
    
    # ensure that there is at least one worker per tenant
    n_workers_per_ms = [max(1, n) for n in n_workers_per_ms]
    
    hosts = [Host(f"host{i}", HOST_CAPACITY) for i in range(n_hosts)]
    
    host_workers = {}
    
    tenants = []
    workers = []
    worker_id = 0
    for i in range(n_tenants):
        
        tenant_load = np.sum(np.random.exponential(
            WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA, size=n_workers_per_ms[i]))
        
        tenant = Tenant(f"tenant{i}", tenant_load)
        tenants.append(tenant)
        
        for j in range(n_workers_per_ms[i]):
            
            host_idx = np.random.randint(0, n_hosts)
            host_name = f"host{host_idx}"
            
            worker = Worker(f"tenant{i}_{j}", tenant.name, host_name, i)
            workers.append(worker)
            
            hosts[host_idx].worker_ids.append(worker_id)
        
            worker_id += 1
    
    for host in hosts:
        
        fshare_of_each_worker = HOST_CAPACITY / len(host.worker_ids) if len(host.worker_ids) > 0 else 0.0
        
        for worker_id in host.worker_ids:
            worker = workers[worker_id]
            tenant = tenants[worker.tenant_id]
            tenant.fshareload += fshare_of_each_worker
    
    # print("Hosts:")
    # for host in hosts:
    #     print(host)
    
    # print("Tenants:")
    # for tenant in tenants:
    #     print(tenant)
        
    # print("Workers:")
    # for worker in workers:
    #     print(worker)
    
    return hosts, tenants, workers, n_workers_per_ms

def change_tenant_loads(tenants: List[Tenant],
                        percentage_of_tenants_to_change: float, 
                        percentage_change_per_tenant: float) -> List[Tenant]:
    
    n_tenants_to_change = int(len(tenants) * percentage_of_tenants_to_change/100.0)
    
    print(f"Changing {n_tenants_to_change} tenants")
    
    tenants_to_change = np.random.choice(tenants, n_tenants_to_change, replace=False)
    
    for tenant in tenants_to_change:
        change = tenant.load * percentage_change_per_tenant/100.0
        # randomly either decrease or increase the change
        change = change if np.random.rand() > 0.5 else -change
        tenant.load += change
        
    return tenants

# Does both of the following:
# Linear-rerun: rerun the linear optimization by just changing the tenant loads
# Linear2-rerun: rerun the linear2 optimization by just changing the tenant loads       
def rerun_generic_linear_model(
    m: gp.Model,
    t_min: Tenant_Min,
    t_consumed: Tenant_Consumed,
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
    global previous_w
    
    # confirm if the topology is the same, if not, rerun the optimization from scratch
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    if not was_previous_the_same_topology:
        # raise Exception("The topology has changed, please rerun the optimization from scratch")
        
        return run_generic_linear_model(_hosts, _tenants, _workers)

    #  ============================= Modify Variables =============================
    
    for tenant in _tenants:
        t_min_value = min(tenant.fshareload, tenant.load)
        t_min[tenant.name].LB = t_min_value
        t_min[tenant.name].UB = t_min_value
        
    for tenant in _tenants:
        print(f"{tenant.name}: (lb: {min(tenant.fshareload, tenant.load)}, ub: {tenant.load})")
        t_consumed[tenant.name].LB = min(tenant.fshareload, tenant.load)
        t_consumed[tenant.name].UB = tenant.load
        
    # ============================ Update Model =============================
    
    m.update()
    
    # ============================== Optimize! =================================
    
    m.optimize()
    
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
        
        return to_return, m, t_min, t_consumed

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
        
        return to_return, m, t_min, t_consumed

# Linear: 2nd obj is minimizing the abs differences of host utilizations at each node. All three objectives are optimized for at once, in one optimization.
def run_generic_linear_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
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
         
    m.setObjectiveN(-weighted_sum_of_t_excess_consumption, index=0, priority=2)
    
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
        
    # ========================== Variance Objective ============================
    
    host_utilizations = []
    for host in _hosts:
        host_utilizations.append(gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name)))
    
    n = len(host_utilizations)
    
    # Auxiliary variables for absolute differences
    differences = {}
    for i in range(n):
        for j in range(i + 1, n):  # Only consider each pair once (i < j)
            differences[i, j] = m.addVar(vtype=GRB.CONTINUOUS, name=f"d_{i}_{j}")

    # Constraints to link auxiliary host_utilizations with the absolute difference of pairs
    for i in range(n):
        for j in range(i + 1, n):
            m.addConstr(differences[i, j] >= host_utilizations[i] - host_utilizations[j], f"DiffPos_{i}_{j}")
            m.addConstr(differences[i, j] >= host_utilizations[j] - host_utilizations[i], f"DiffNeg_{i}_{j}")
    
    # Objective: Minimize the sum of all absolute differences
    m.setObjectiveN(gp.quicksum(differences[i, j] for i in range(n) for j in range(i + 1, n)), index=1, priority=1)

    # ========== Minimize distance between current and prev weights ============
    
    # do this only if you have all the previous weights
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    
    if was_previous_the_same_topology:
        
        print("Same topology;", "doing the distance optimization")
        
        n = len(_workers)
        abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
        
        # set the new objective to minimize the distance between the weights
        for i, worker in enumerate(_workers):
            m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name])
            m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name])
        
        m.setObjectiveN(gp.quicksum(abs_diff[i] for i in range(n)), index=2, priority=0)
        
    else:
        
        print("Different topology;", "adding distance objective with 0 weight") 
        
        n = len(_workers)
        abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
        
        # set the new objective to minimize the distance between the weights
        for i, worker in enumerate(_workers):
            m.addConstr(abs_diff[i] >= w[worker.name] - 0.0)
            m.addConstr(abs_diff[i] >= 0.0 - w[worker.name])
        
        m.setObjectiveN(gp.quicksum(abs_diff[i] for i in range(n)), index=2, priority=0)
    
    # ============================== Optimize! =================================
    
    m.optimize()
    
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
        
        return to_return, m, t_min, t_consumed

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
        
        return to_return, m, t_min, t_consumed

# Linear2: Do Linear but minimize abs diff of spare capacities instead of host utilizations
def run_generic_linear_model2(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
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
    
    # ======================= Set Utilization Objective ========================
    
    sum_fshareloads = sum(tenant.fshareload for tenant in _tenants)
    
    weighted_sum_of_t_excess_consumption = gp.quicksum(
        ((tenant.fshareload / sum_fshareloads) * t_log_excess_consumed[tenant.name]
         for tenant in _tenants))
    
    # sum_workers = gp.quicksum((w[worker.name] for worker in _workers))
         
    m.setObjectiveN(-weighted_sum_of_t_excess_consumption, index=0, priority=2)
    
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
        
    # ========================== Variance Objective ============================
        
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
    
    n = len(_hosts)
    
    # Auxiliary variables for absolute differences
    differences = {}
    for i in range(n):
        for j in range(i + 1, n):  # Only consider each pair once (i < j)
            differences[i, j] = m.addVar(vtype=GRB.CONTINUOUS, name=f"d_{i}_{j}")

    # Constraints to link auxiliary sp with the absolute difference of pairs
    for i in range(n):
        for j in range(i + 1, n):
            m.addConstr(differences[i, j] >= sp[_hosts[i].name] - sp[_hosts[j].name], f"DiffPos_{i}_{j}")
            m.addConstr(differences[i, j] >= sp[_hosts[j].name] - sp[_hosts[i].name], f"DiffNeg_{i}_{j}")
    
    # Objective: Minimize the sum of all absolute differences
    m.setObjectiveN(gp.quicksum(differences[i, j] for i in range(n) for j in range(i + 1, n)), index=1, priority=1)

    # ========== Minimize distance between current and prev weights ============
    
    # do this only if you have all the previous weights
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    
    if was_previous_the_same_topology:
        
        print("Same topology;", "doing the distance optimization")
        
        n = len(_workers)
        abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
        
        # set the new objective to minimize the distance between the weights
        for i, worker in enumerate(_workers):
            m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name])
            m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name])
        
        m.setObjectiveN(gp.quicksum(abs_diff[i] for i in range(n)), index=2, priority=0)
        
    else:
        
        print("Different topology;", "adding distance objective with 0 weight") 
        
        n = len(_workers)
        abs_diff = m.addVars(n, vtype=GRB.CONTINUOUS, name="abs_diff")
        
        # set the new objective to minimize the distance between the weights
        for i, worker in enumerate(_workers):
            m.addConstr(abs_diff[i] >= w[worker.name] - 0.0)
            m.addConstr(abs_diff[i] >= 0.0 - w[worker.name])
        
        m.setObjectiveN(gp.quicksum(abs_diff[i] for i in range(n)), index=2, priority=0)
    
    # ============================== Optimize! =================================
    
    m.optimize()
    
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
        
        return to_return, m, t_min, t_consumed

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
        
        return to_return, m, t_min, t_consumed

# Linear-Multiple: 2nd obj is minimizing the abs differences of spare capacities at each node. Optimizations are done sequentially for each objective.
def run_generic_linear_multioptimization_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
    global previous_w
    
    statuses = []
    
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
    
    # ======================= Set Utilization Objective ========================
    
    sum_fshareloads = sum(tenant.fshareload for tenant in _tenants)
    
    weighted_sum_of_t_excess_consumption = m.addVar(vtype=GRB.CONTINUOUS,
                                                      lb=-GRB.INFINITY,
                                                      ub=GRB.INFINITY,
                                 name=f"weighted_sum_of_t_excess_consumption")
    
    m.addConstr(weighted_sum_of_t_excess_consumption == gp.quicksum(
        ((tenant.fshareload / sum_fshareloads) * t_log_excess_consumed[tenant.name]
         for tenant in _tenants)), name="weighted_sum_of_t_excess_consumption")
    
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
    
    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
    
        # ==================== Variance Objective Optimization =====================
        
        min_weighted_sum_of_t_excess_consumption = m.ObjVal
        m.addConstr(
            weighted_sum_of_t_excess_consumption >= min_weighted_sum_of_t_excess_consumption, 
            name="obj1_constraint")
        
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
        
        n = len(sp)
        
        # Auxiliary variables for absolute differences
        differences = {}
        for i in range(n):
            for j in range(i + 1, n):  # Only consider each pair once (i < j)
                differences[i, j] = m.addVar(vtype=GRB.CONTINUOUS, name=f"d_{i}_{j}")

        # Constraints to link auxiliary host_utilizations with the absolute difference of pairs
        for i in range(n):
            for j in range(i + 1, n):
                m.addConstr(differences[i, j] >= sp[_hosts[i].name] - sp[_hosts[j].name], f"DiffPos_{i}_{j}")
                m.addConstr(differences[i, j] >= sp[_hosts[j].name] - sp[_hosts[i].name], f"DiffNeg_{i}_{j}")
        
        sp_abs_diff = m.addVar(vtype=GRB.CONTINUOUS, name="sp_abs_diff")
        
        m.addConstr(sp_abs_diff == gp.quicksum(differences[i, j] for i in range(n) for j in range(i + 1, n)))
        
        # Objective: Minimize the sum of all absolute differences
        m.setObjective(sp_abs_diff, GRB.MINIMIZE)
        
        m.optimize()
        
        statuses.append(m.Status)
    
        if m.Status == GRB.OPTIMAL:
            
            # =========================== Optimization minimize distanc between weights ============================
            
            # do this only if you have all the previous weights
            was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
        
            # set that the variance objective is no more as much as what it was in the last optimization
            max_sp_abs_diff = m.ObjVal
            m.addConstr(sp_abs_diff <= max_sp_abs_diff, name="obj2_constraint")
            
            abs_diff = []
            for i in range(len(_workers)):
                print(f"abs_diff_{i}")
                abs_diff += [m.addVar(vtype=GRB.CONTINUOUS, name=f"abs_diff_{i}")]
            
            # set the new objective to minimize the distance between the weights
            if was_previous_the_same_topology:
                for i, worker in enumerate(_workers):
                    m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name], name=f"abs_diff_{i}_1")
                    m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name], name=f"abs_diff_{i}_2")
            else:
                for i, worker in enumerate(_workers):
                    m.addConstr(abs_diff[i] >= w[worker.name] - 0.0, name=f"abs_diff_{i}_1")
                    m.addConstr(abs_diff[i] >= 0.0 - w[worker.name], name=f"abs_diff_{i}_2")

            m.setObjective(gp.quicksum(abs_diff[i] for i in range(len(_workers))), GRB.MINIMIZE)
            
            m.optimize()
            
            statuses.append(m.Status)
    
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
            "status": statuses,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w_{worker.name}"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

# Linear Single Combined Objective
def run_generic_linear_single_objective_model_nov15(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Load]:
    
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
        
    # set variables for the workers
    w = {}
    log_w = {}
    for worker in _workers:
        w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                           name=f"w_{worker.name}")
        log_w[worker.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                      lb=-GRB.INFINITY,
                                      ub=GRB.INFINITY,
                                      name=f"log_w_{worker.name}")
    
    # state for tenant (to be used for rerunning optimization)
    t_load = {}
    t_min = {}
    for tenant in _tenants:
        t_load[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, vtype=GRB.CONTINUOUS,
                                       name=f"t_{tenant.name}")
        t_min_value = min(tenant.fshareload, tenant.load)
        t_min[tenant.name] = m.addVar(lb=t_min_value, ub=t_min_value, vtype=GRB.CONTINUOUS,
                                     name=f"t_min_{tenant.name}")
    
    # set spare resources used by a tenant
    sr = {}
    log_sr = {}
    for tenant in _tenants:
        sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
                                   ub=GRB.INFINITY,
                                   vtype=GRB.CONTINUOUS,
                                   name=f"sr_{tenant.name}")
        log_sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
                                        ub=GRB.INFINITY,
                                        vtype=GRB.CONTINUOUS,
                                        name=f"log_sr_{tenant.name}")
    
    # set spare capacities at hosts
    sp = {}
    log_sp = {}
    for host in _hosts:
        sp[host.name] = m.addVar(lb=0.0,
                                 ub=host.cap,
                                 vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
        log_sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                     lb=-GRB.INFINITY,
                                     ub=GRB.INFINITY,
                                     name=f"log_sp_{host.name}")
    
    # ======================= Set Optimization Objective =======================
        
    # Objective 1: max sum(U(sr_t+, w_t), ∀t)
    #                  where
    #                  U(sr_t+, w_t) = w_t * log(sr_t+)
    #                  w_t = fs_t
    # ∴ obj1 = sum(fs_t * log(sr_t+), ∀t); maximize this
    obj1 = gp.quicksum((tenant.fshareload * log_sr[tenant.name] for tenant in _tenants))
    # m.setObjectiveN(-obj1, index=0, priority=2)
    
    # Objective 2: max sum(U(sp_h), ∀h)
    #                  where
    #                  U(sp_h) = log(sp_h)
    # ∴ obj2 = sum(log(sp_h), ∀h); maximize this
    obj2 = gp.quicksum([log_sp[host.name] for host in _hosts])
    # m.setObjectiveN(-obj2, index=1, priority=1)
    
    # Objective 3: max sum(U(w), ∀w)
    #                  where
    #                  U(w) = log(w)
    # ∴ obj3 = sum(log(w), ∀w); maximize this
    obj3 = gp.quicksum([log_w[worker.name] for worker in _workers])
    # m.setObjectiveN(-obj3, index=2, priority=0)
    
    obj1_w = np.sum([host.cap for host in _hosts])
    obj2_w = 0.1
    obj3_w = 0.001
    obj = obj1_w * obj1 + obj2_w * obj2 + obj3_w * obj3
    m.setObjective(obj, GRB.MAXIMIZE)
        
    # m.setParam('FuncPieces', 0)  # Increase number of pieces in linearization
    
    # ============================ Set Constraints =============================
    
    # Constraint 1: for all host h, sum(w ∈ t) <= cap(h)
    m.addConstrs(
        (gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name)) <= cap[host.name]
         for host in _hosts),
        name="h_cap"
    )
    
    # Constraint 2: for all tenants w, sum(w ∈ t) < t_load
    m.addConstrs(
        (gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) <= t_load[tenant.name]
         for tenant in _tenants), 
        name="t_ub"
    )
    
    # Constraint 3: for all tenants w, sum(w ∈ t) > min(tenant.fshareload, tenant.load)
    for tenant in _tenants:
        m.addConstr(
            gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) >= t_min[tenant.name],
            name=f"t_lb_{tenant.name}"
        )
    
    # ------ Secondary constraints ------
    
    # Constraint 4: for all tenants, sr_t = sum(w ∈ t) - min(tenant.fshareload, tenant.load),
    #                                log_sr_t = log(sr_t)
    m.addConstrs(
        ((sr[tenant.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) - t_min[tenant.name]) for tenant in _tenants),
        name="sr"
    )
    for tenant in _tenants:
        m.addGenConstrLog(sr[tenant.name], log_sr[tenant.name], name="log_sr")
    
    # Constraint 5: for all hosts, sp_h = cap(h) - sum(w ∈ h),
    #                              log_sp_h = log(sp_h)
    m.addConstrs(
        ((sp[host.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name))) for host in _hosts),
        name="sp"
    )
    for host in _hosts:
        m.addGenConstrLog(sp[host.name], log_sp[host.name], name=f"log_sp_{host.name}")
        
    # Constraint 6: for all workers, log_w = log(w)
    for worker in _workers:
        m.addGenConstrLog(w[worker.name], log_w[worker.name], name=f"log_w_{worker.name}")
    
    # ============================== Optimize! =================================
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    # # Sequential Optimization
    
    # FUNC_PIECES = 0
    
    # # Optimize for obj1
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj1, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sr for each tenant
    # m.addConstrs(
    #     (sr[tenant.name] >= sr[tenant.name].X for tenant in _tenants),
    #     name="sr_lb_obj2"
    # )
    # m.update()
    
    # # Optimize for obj2
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj2, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sp for each host
    # m.addConstrs(
    #     (sp[host.name] >= sp[host.name].X for host in _hosts),
    #     name="sp_lb_obj3"
    # )
    # m.update()
    
    # # Optimize for obj3
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj3, GRB.MAXIMIZE)
    # m.optimize()
    
    # =========================== Done Optimization ============================
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
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
        
        return to_return, m, t_min, t_load

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
        
        return to_return, m, t_min, t_load

# Linear Single Combined Objective
def _run_generic_linear_single_objective_model_nov15_abs_diff(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Load]:
    
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
        
    # set variables for the workers
    w = {}
    # log_w = {}
    for worker in _workers:
        w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                           name=f"w_{worker.name}")
        # log_w[worker.name] = m.addVar(vtype=GRB.CONTINUOUS,
        #                               lb=-GRB.INFINITY,
        #                               ub=GRB.INFINITY,
        #                               name=f"log_w_{worker.name}")
    
    # state for tenant (to be used for rerunning optimization)
    t_load = {}
    t_min = {}
    for tenant in _tenants:
        t_load[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, vtype=GRB.CONTINUOUS,
                                       name=f"t_{tenant.name}")
        t_min_value = min(tenant.fshareload, tenant.load)
        t_min[tenant.name] = m.addVar(lb=t_min_value, ub=t_min_value, vtype=GRB.CONTINUOUS,
                                     name=f"t_min_{tenant.name}")
    
    # set spare resources used by a tenant
    sr = {}
    log_sr = {}
    for tenant in _tenants:
        # sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
        #                            ub=GRB.INFINITY,
        #                            vtype=GRB.CONTINUOUS,
        #                            name=f"sr_{tenant.name}")
        log_sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
                                        ub=GRB.INFINITY,
                                        vtype=GRB.CONTINUOUS,
                                        name=f"log_sr_{tenant.name}")
    
    # set spare capacities at hosts
    sp = {}
    log_sp = {}
    for host in _hosts:
        sp[host.name] = m.addVar(lb=0.0,
                                 ub=host.cap,
                                 vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
        log_sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                     lb=-GRB.INFINITY,
                                     ub=GRB.INFINITY,
                                     name=f"log_sp_{host.name}")
    
    # ======================= Set Optimization Objective =======================
        
    # Objective 1: max sum(U(sr_t+, w_t), ∀t)
    #                  where
    #                  U(sr_t+, w_t) = w_t * log(sr_t+)
    #                  w_t = fs_t
    # ∴ obj1 = sum(fs_t * log(sr_t+), ∀t); maximize this
    obj1 = gp.quicksum((tenant.fshareload * log_sr[tenant.name] for tenant in _tenants))
    # m.setObjectiveN(-obj1, index=0, priority=2)
    
    # Objective 2: max sum(U(sp_h), ∀h)
    #                  where
    #                  U(sp_h) = log(sp_h)
    # ∴ obj2 = sum(log(sp_h), ∀h); maximize this
    obj2 = gp.quicksum([log_sp[host.name] for host in _hosts])
    # m.setObjectiveN(-obj2, index=1, priority=1)
    
    # Objective 3: max sum(U(w), ∀w)
    #                  where
    #                  U(w) = log(w)
    # ∴ obj3 = sum(log(w), ∀w); maximize this
    # obj3 = gp.quicksum([log_w[worker.name] for worker in _workers])
    # m.setObjectiveN(-obj3, index=2, priority=0)
    
    # =========================== Optimization minimize distanc between weights ============================
            
    # # do this only if you have all the previous weights
    # was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    
    # abs_diff = []
    # for i in range(len(_workers)):
    #     print(f"abs_diff_{i}")
    #     abs_diff += [m.addVar(vtype=GRB.CONTINUOUS, name=f"abs_diff_{i}")]
    
    # # set the new objective to minimize the distance between the weights
    # if was_previous_the_same_topology:
    #     for i, worker in enumerate(_workers):
    #         m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name], name=f"abs_diff_{i}_1")
    #         m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name], name=f"abs_diff_{i}_2")
    # else:
    #     for i, worker in enumerate(_workers):
    #         m.addConstr(abs_diff[i] >= w[worker.name] - 0.0, name=f"abs_diff_{i}_1")
    #         m.addConstr(abs_diff[i] >= 0.0 - w[worker.name], name=f"abs_diff_{i}_2")

    # obj3 = gp.quicksum(abs_diff[i] for i in range(len(_workers)))
    
    # m.optimize()
    
    obj1_w = np.sum([host.cap for host in _hosts])
    obj2_w = 0.1
    obj3_w = 0.001
    obj = obj1_w * obj1 + obj2_w * obj2 # - obj3_w * obj3
    m.setObjective(obj, GRB.MAXIMIZE)
        
    # m.setParam('FuncPieces', 0)  # Increase number of pieces in linearization
    
    # ============================ Set Constraints =============================
    
    # Constraint 1: for all host h, sum(w ∈ t) <= cap(h)
    m.addConstrs(
        (gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name)) <= cap[host.name]
         for host in _hosts),
        name="h_cap"
    )
    
    # Constraint 2: for all tenants w, sum(w ∈ t) < t_load
    m.addConstrs(
        (gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) <= t_load[tenant.name]
         for tenant in _tenants), 
        name="t_ub"
    )
    
    # Constraint 3: for all tenants w, sum(w ∈ t) > min(tenant.fshareload, tenant.load)
    for tenant in _tenants:
        m.addConstr(
            gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) >= t_min[tenant.name],
            name=f"t_lb_{tenant.name}"
        )
    
    # ------ Secondary constraints ------
    
    # Constraint 4: for all tenants, sr_t = sum(w ∈ t) - min(tenant.fshareload, tenant.load),
    #                                log_sr_t = log(sr_t)
    # m.addConstrs(
    #     ((sr[tenant.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) - t_min[tenant.name]) for tenant in _tenants),
    #     name="sr"
    # )
    for tenant in _tenants:
        m.addGenConstrLog(t_load[tenant.name], log_sr[tenant.name], name="log_sr")
    
    # Constraint 5: for all hosts, sp_h = cap(h) - sum(w ∈ h),
    #                              log_sp_h = log(sp_h)
    m.addConstrs(
        ((sp[host.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name))) for host in _hosts),
        name="sp"
    )
    for host in _hosts:
        m.addGenConstrLog(sp[host.name], log_sp[host.name], name=f"log_sp_{host.name}")
        
    # # Constraint 6: for all workers, log_w = log(w)
    # for worker in _workers:
    #     m.addGenConstrLog(w[worker.name], log_w[worker.name], name=f"log_w_{worker.name}")
    
    # ============================== Optimize! =================================
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    # # Sequential Optimization
    
    # FUNC_PIECES = 0
    
    # # Optimize for obj1
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj1, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sr for each tenant
    # m.addConstrs(
    #     (sr[tenant.name] >= sr[tenant.name].X for tenant in _tenants),
    #     name="sr_lb_obj2"
    # )
    # m.update()
    
    # # Optimize for obj2
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj2, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sp for each host
    # m.addConstrs(
    #     (sp[host.name] >= sp[host.name].X for host in _hosts),
    #     name="sp_lb_obj3"
    # )
    # m.update()
    
    # # Optimize for obj3
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj3, GRB.MAXIMIZE)
    # m.optimize()
    
    # =========================== Done Optimization ============================
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
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
        
        return to_return, m, t_min, t_load

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
        
        return to_return, m, t_min, t_load

def run_generic_linear_single_objective_model_nov15_abs_diff(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Load]:
    
    global previous_w
    
    # =========================== Begin Optimization ===========================
    
    # MIP  model formulation
    m = gp.Model("lb")
    
    # ============================= Set Variables =============================

    # Initialize model
    m = gp.Model("optimized_model")

    # Precompute bounds and indices
    cap_bounds = {h.name: h.cap for h in _hosts}
    t_load_bounds = {t.name: t.load for t in _tenants}

    # Batch variable setup for hosts
    cap = m.addVars(cap_bounds.keys(), lb=cap_bounds, ub=cap_bounds, vtype=GRB.CONTINUOUS, name="cap")

    # Batch variable setup for workers
    worker_names = [worker.name for worker in _workers]
    w = m.addVars(worker_names, lb=0.0, vtype=GRB.CONTINUOUS, name="w")
    # log_w = m.addVars(worker_names, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="log_w")

    # Batch variable setup for tenants
    t_load = m.addVars(t_load_bounds.keys(), lb=t_load_bounds, ub=t_load_bounds, vtype=GRB.CONTINUOUS, name="t_load")

    t_min_values = {t.name: min(t.fshareload, t.load) for t in _tenants}
    t_min = m.addVars(t_min_values.keys(), lb=t_min_values, ub=t_min_values,
                    vtype=GRB.CONTINUOUS, name="t_min")

    # Tenant spare resources variables
    tenant_names = [t.name for t in _tenants]
    sr = m.addVars(tenant_names, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="sr")
    log_sr = m.addVars(tenant_names, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="log_sr")

    # Host spare capacity variables
    host_names = [h.name for h in _hosts]
    sp = m.addVars(host_names, lb=0.0, ub={h.name: h.cap for h in _hosts}, vtype=GRB.CONTINUOUS, name="sp")
    log_sp = m.addVars(host_names, lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="log_sp")

    # ============================= Objective Setup =============================

    obj1 = gp.quicksum(t.fshareload * log_sr[t.name] for t in _tenants)
    obj2 = gp.quicksum(log_sp[h.name] for h in _hosts)
    # obj3 = gp.quicksum(log_w[w.name] for w in _workers)

    obj1_w = sum(h.cap for h in _hosts)
    obj2_w = 0.1
    # obj3_w = 0.001

    m.setObjective(obj1_w * obj1 + obj2_w * obj2, GRB.MAXIMIZE)

    # =========================== Efficient Precomputations ===========================

    host_workers = defaultdict(list)
    tenant_workers = defaultdict(list)

    for worker in _workers:
        host_workers[worker.host].append(worker.name)
        tenant_workers[worker.tenant].append(worker.name)

    # ============================ Constraints Setup ============================

    # Host capacity constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in host_workers[h]) <= cap[h]
        for h in host_names), name="h_cap"
    )

    # Tenant upper bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[t]) <= t_load[t]
        for t in tenant_names), name="t_ub"
    )

    # Tenant lower bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[t]) >= t_min[t]
        for t in tenant_names), name="t_lb"
    )

    # Tenant spare resources (sr_t)
    m.addConstrs(
        (sr[t] == gp.quicksum(w[worker_name] for worker_name in tenant_workers[t]) - t_min[t]
        for t in tenant_names), name="sr"
    )

    # Host spare capacity (sp_h)
    m.addConstrs(
        (sp[h] == cap[h] - gp.quicksum(w[worker_name] for worker_name in host_workers[h])
        for h in host_names), name="sp"
    )

    # ============================ Logarithmic Constraints ============================

    # Batch logarithmic constraints for tenants (log_sr)
    for t in tenant_names:
        m.addGenConstrLog(sr[t], log_sr[t], name=f"log_sr_{t}")

    # Batch logarithmic constraints for hosts (log_sp)
    for h in host_names:
        m.addGenConstrLog(sp[h], log_sp[h], name=f"log_sp_{h}")

    # # Batch logarithmic constraints for workers (log_w)
    # for worker_name in worker_names:
    #     m.addGenConstrLog(w[worker_name], log_w[worker_name], name=f"log_w_{worker_name}")
    
    # ============================== Optimize! =================================
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    # # Sequential Optimization
    
    # FUNC_PIECES = 0
    
    # # Optimize for obj1
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj1, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sr for each tenant
    # m.addConstrs(
    #     (sr[tenant.name] >= sr[tenant.name].X for tenant in _tenants),
    #     name="sr_lb_obj2"
    # )
    # m.update()
    
    # # Optimize for obj2
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj2, GRB.MAXIMIZE)
    # m.optimize()
    
    # # Set constriants on sp for each host
    # m.addConstrs(
    #     (sp[host.name] >= sp[host.name].X for host in _hosts),
    #     name="sp_lb_obj3"
    # )
    # m.update()
    
    # # Optimize for obj3
    # m.setParam('FuncPieces', FUNC_PIECES)
    # m.setObjective(obj3, GRB.MAXIMIZE)
    # m.optimize()
    
    # =========================== Done Optimization ============================
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
        
    if m.Status == GRB.OPTIMAL:        
        
        vars = {v.varName: v.x for v in m.getVars()}
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
            else:
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
        to_return = {
            "status": m.Status,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w[{worker.name}]"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return, m, t_min, t_load

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
        
        return to_return, m, t_min, t_load


# Linear Single Objective: Just do the first objective (maximize the sum of utilizations of tenants proportionally fairly according to their fshareloads)
def run_generic_linear_single_objective_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
    global previous_w
    
    statuses = []
    
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
    log_w = {}
    for worker in _workers:
        w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                           name=f"w_{worker.name}")
        log_w[worker.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                      lb=-GRB.INFINITY,
                                      ub=GRB.INFINITY,
                                      name=f"log_w_{worker.name}")
    
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
        t_consumed[tenant.name] = m.addVar(lb=min(tenant.fshareload, tenant.load), 
                                           ub=tenant.load,
                                           vtype=GRB.CONTINUOUS,
                                 name=f"t_consumed_{tenant.name}")
    
    t_excess_consumed = {}
    t_log_excess_consumed = {}
    for tenant in _tenants:
        t_excess_consumed[tenant.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"t_excess_consumed_{tenant.name}")
        t_log_excess_consumed[tenant.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                                      lb=-GRB.INFINITY,
                                                      ub=GRB.INFINITY,
                                 name=f"t_log_excess_consumed_{tenant.name}")
        
    # set spare caps
    sp = {}
    log_sp = {}
    for host in _hosts:
        sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
        log_sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                     lb=-GRB.INFINITY,
                                     ub=GRB.INFINITY,
                                     name=f"log_sp_{host.name}")
    
    weighted_sum_of_t_excess_consumption = m.addVar(vtype=GRB.CONTINUOUS,
                                                      lb=-GRB.INFINITY,
                                                      ub=GRB.INFINITY,
                                 name=f"weighted_sum_of_t_excess_consumption")
    
    pfair_sum_of_h_sp = m.addVar(vtype=GRB.CONTINUOUS,
                                 lb=-GRB.INFINITY,
                                 ub=GRB.INFINITY,
                                 name=f"pfair_sum_of_h_sp")
    
    sum_of_pfair_sums_of_t_w_utils = m.addVar(vtype=GRB.CONTINUOUS,
                                    lb=-GRB.INFINITY,
                                    ub=GRB.INFINITY,
                                    name=f"pfair_sum_of_h_sp")
    
    # ======================= Set Optimization Objective =======================
    
    sum_fshareloads = sum(tenant.fshareload for tenant in _tenants)
    
    # set the 1st objective
    m.addConstr(weighted_sum_of_t_excess_consumption == gp.quicksum(
        ((tenant.fshareload / sum_fshareloads) * t_log_excess_consumed[tenant.name]
         for tenant in _tenants)), name="weighted_sum_of_t_excess_consumption")
    
    # set the 2nd objective
    m.addConstr(pfair_sum_of_h_sp == gp.quicksum(
        log_sp[host.name] for host in _hosts))

    # set the 3rd objective
    
    pfair_sums_of_t_w_utils = []
    for tenant in _tenants:
        pfair_sum_of_t_w_utils = gp.quicksum(
            (log_w[worker.name] for worker in _workers if worker.tenant == tenant.name))
        pfair_sums_of_t_w_utils += [pfair_sum_of_t_w_utils]
        
    m.addConstr(sum_of_pfair_sums_of_t_w_utils == 
                gp.quicksum(pfair_sums_of_t_w_utils))

    OBJ1_WEIGHT = np.sum([host.cap for host in _hosts])
    OBJ2_WEIGHT = 1
    OBJ3_EPSILON = 0.001
    
    # combined objective
    obj = OBJ1_WEIGHT * weighted_sum_of_t_excess_consumption + \
            OBJ2_WEIGHT * pfair_sum_of_h_sp + \
            OBJ3_EPSILON * sum_of_pfair_sums_of_t_w_utils
         
    m.setObjective(obj, GRB.MAXIMIZE)
    
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
        
    # for each host, sp = (cap - sum(w))
    for host in _hosts:
        m.addConstr(
            sp[host.name] == (cap[host.name] - gp.quicksum(
                (w[worker.name] 
                for worker in _workers if worker.host == host.name))),
            name=f"sp_{host.name}")
        
    # for each host, log_sp = log(sp)
    for host in _hosts:
        m.addGenConstrLog(sp[host.name], log_sp[host.name])
    
    for worker in _workers:
        m.addGenConstrLog(w[worker.name], log_w[worker.name])
    
    # ============================== Optimize! =================================
    
    m.optimize()
    
    # =========================== Done Optimization ============================
    
    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
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
            "status": statuses,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w_{worker.name}"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed


# Linear-Multiple: 2nd obj is minimizing the abs differences of spare capacities at each node. Optimizations are done sequentially for each objective.
def rerun_generic_linear_multioptimization_model(
    m: gp.Model,
    t_min: Tenant_Min,
    t_consumed: Tenant_Consumed,
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
    global previous_w
    
    statuses = []
    
    # confirm if the topology is the same, if not, rerun the optimization from scratch
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    if not was_previous_the_same_topology:
        raise Exception("The topology has changed, please rerun the optimization from scratch")
        
        return run_generic_linear_model(_hosts, _tenants, _workers)
    
    #  ============================= Modify Variables =============================
    
    for tenant in _tenants:
        t_min_value = min(tenant.fshareload, tenant.load)
        if t_min[tenant.name].LB != t_min_value:
            t_min[tenant.name].LB = t_min_value
            t_min[tenant.name].UB = t_min_value
        
    for tenant in _tenants:
        if t_consumed[tenant.name].LB != min(tenant.fshareload, tenant.load) or t_consumed[tenant.name].UB != tenant.load:
            print(f"{tenant.name}: (lb: {min(tenant.fshareload, tenant.load)}, ub: {tenant.load})")
            t_consumed[tenant.name].LB = min(tenant.fshareload, tenant.load)
            t_consumed[tenant.name].UB = tenant.load
        
    # ============ Remove constraints added in later optimizations =============
    
    obj1_constraint = m.getConstrByName("obj1_constraint")
    assert(obj1_constraint is not None)
    m.remove(obj1_constraint)
    
    obj2_constraint = m.getConstrByName("obj2_constraint")
    assert(obj2_constraint is not None)
    m.remove(obj2_constraint)
    
    # ============================ Update Model =============================
    
    m.update()
    
    # ============================== Optimize (1) =================================
    
    weighted_sum_of_t_excess_consumption = m.getVarByName("weighted_sum_of_t_excess_consumption")
    m.setObjective(weighted_sum_of_t_excess_consumption, GRB.MAXIMIZE)
    m.optimize()
        
    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
    
        # ==================== Variance Objective Optimization =====================
            
        min_weighted_sum_of_t_excess_consumption = m.ObjVal
        m.addConstr(
            weighted_sum_of_t_excess_consumption >= min_weighted_sum_of_t_excess_consumption, 
            name="obj1_constraint")
        
        m.update()
        
        # Objective: Minimize the sum of all absolute differences
        sp_abs_diff = m.getVarByName("sp_abs_diff")
        m.setObjective(sp_abs_diff, GRB.MINIMIZE)
        
        m.optimize()
        
        statuses.append(m.Status)
    
        if m.Status == GRB.OPTIMAL:
            
            # =========================== Optimization minimize distanc between weights ============================
            
            # do this only if you have all the previous weights
            was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
            
            # set that the variance objective is no more as much as what it was in the last optimization
            max_sp_abs_diff = m.ObjVal
            m.addConstr(sp_abs_diff <= max_sp_abs_diff, name="obj2_constraint")
            
            abs_diff = []
            for i in range(len(_workers)):
                abs_diff += [m.getVarByName(f"abs_diff_{i}")]
            # confirm that there is no None in abs_diff
            assert(all(ad is not None for ad in abs_diff))
                
            w = {}
            for worker in _workers:
                w[worker.name] = m.getVarByName(f"w_{worker.name}")
                assert(w[worker.name] is not None)
            
            # set the new objective to minimize the distance between the weights
            for i, worker in enumerate(_workers):
                
                print(f"abs_diff_{i}")
                
                print(m.getConstrByName(f"abs_diff_{i}_1"))                
                m.remove(m.getConstrByName(f"abs_diff_{i}_1"))
                m.remove(m.getConstrByName(f"abs_diff_{i}_2"))
                
                if was_previous_the_same_topology:
                    # print(worker.name, previous_w[worker.name], w[worker.name])
                    m.addConstr(abs_diff[i] >= w[worker.name] - previous_w[worker.name], name=f"abs_diff_{i}_1")
                    m.addConstr(abs_diff[i] >= previous_w[worker.name] - w[worker.name], name=f"abs_diff_{i}_2")
                else:
                    m.addConstr(abs_diff[i] >= w[worker.name] - 0.0, name=f"abs_diff_{i}_1")
                    m.addConstr(abs_diff[i] >= 0.0 - w[worker.name], name=f"abs_diff_{i}_2")
            
            m.update()
            
            m.setObjective(gp.quicksum(abs_diff[i] for i in range(len(_workers))), GRB.MINIMIZE)
            
            m.optimize()
            
            statuses.append(m.Status)
    
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
            "status": statuses,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w_{worker.name}"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

# Linear Single Objective: Just do the first objective (maximize the sum of utilizations of tenants proportionally fairly according to their fshareloads)
def rerun_generic_linear_single_objective_model_nov15(
    m: gp.Model,
    t_min: Tenant_Min,
    t_load: Tenant_Load,
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Load]:
    
    global previous_w
    
    statuses = []
    
    # confirm if the topology is the same, if not, rerun the optimization from scratch
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    if not was_previous_the_same_topology:
        raise Exception("The topology has changed, please rerun the optimization from scratch")
        
        return run_generic_linear_model(_hosts, _tenants, _workers)
    
    #  ============================= Modify Variables =============================
    
    for tenant in _tenants:
        
        t_min_value = min(tenant.fshareload, tenant.load)
        if t_min[tenant.name].LB != t_min_value:
            t_min[tenant.name].LB = t_min_value
            t_min[tenant.name].UB = t_min_value
            
        if t_load[tenant.name].LB != tenant.load:
            t_load[tenant.name].LB = tenant.load
            t_load[tenant.name].UB = tenant.load        
    
    # ============================ Update Model =============================
    
    m.update()
    
    # ============================== Optimize (1) =================================
    
    start_time = time.time()
    
    m.optimize()
    
    optimization_time = (time.time() - start_time) * 1000
        
    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
        
        # print([str(host) for host in _hosts])
        # print([str(tenant) for tenant in _tenants])
        # print([str(worker) for worker in _workers])
        
        raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")    
    
    # if m.Status == GRB.OPTIMAL:
    #     vars = {v.varName: v.x for v in m.getVars()}
    #     print(vars)
        
    if m.Status == GRB.OPTIMAL:        
        
        vars = {v.varName: v.x for v in m.getVars()}
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
            else:
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
        to_return = {
            "status": statuses,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w[{worker.name}]"] for worker in _workers}
        # print("New previous weights:", previous_w)            
        
        # print(to_return)
        
        return to_return, m, t_min, t_load, optimization_time

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": statuses,
            "result": results
        }
        
        # print(to_return)
        
        return to_return, m, t_min, t_load, optimization_time

# Linear Single Objective: Just do the first objective (maximize the sum of utilizations of tenants proportionally fairly according to their fshareloads)
def rerun_generic_linear_single_objective_model(
    m: gp.Model,
    t_min: Tenant_Min,
    t_consumed: Tenant_Consumed,
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[str, gp.Model, Tenant_Min, Tenant_Consumed]:
    
    global previous_w
    
    statuses = []
    
    # confirm if the topology is the same, if not, rerun the optimization from scratch
    was_previous_the_same_topology = all(worker.name in previous_w for worker in _workers) and len(previous_w) == len(_workers)
    if not was_previous_the_same_topology:
        raise Exception("The topology has changed, please rerun the optimization from scratch")
        
        return run_generic_linear_model(_hosts, _tenants, _workers)
    
    #  ============================= Modify Variables =============================
    
    for tenant in _tenants:
        t_min_value = min(tenant.fshareload, tenant.load)
        if t_min[tenant.name].LB != t_min_value:
            t_min[tenant.name].LB = t_min_value
            t_min[tenant.name].UB = t_min_value
        
    for tenant in _tenants:
        if t_consumed[tenant.name].LB != min(tenant.fshareload, tenant.load) or t_consumed[tenant.name].UB != tenant.load:
            print(f"{tenant.name}: (lb: {min(tenant.fshareload, tenant.load)}, ub: {tenant.load})")
            t_consumed[tenant.name].LB = min(tenant.fshareload, tenant.load)
            t_consumed[tenant.name].UB = tenant.load
    
    # ============================ Update Model =============================
    
    m.update()
    
    # ============================== Optimize (1) =================================
    
    m.optimize()
        
    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")    
    
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
            "status": statuses,
            "result": results
        }
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w_{worker.name}"] for worker in _workers}
        print("New previous weights:", previous_w)            
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

    else:
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = 0.0
            else:
                results[worker.tenant][worker.name] = 0.0
        to_return = {
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return, m, t_min, t_consumed

# Quadratic: 2nd obj is minimizing the variance of the spare capacity at each node. Optimizations are done sequentially for each objective
def run_generic_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> str:
    
    global previous_w
    
    statuses = []
    
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

    statuses.append(m.Status)
    
    if m.Status != GRB.OPTIMAL:
            
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
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

        statuses.append(m.Status)
        
    
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

                statuses.append(m.Status)
                
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

                statuses.append(m.Status)
                
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
            "status": statuses,
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
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return

def write_run_to_log(run, logfile="current_exp.json"):
    with open(logfile, "a") as f:
        f.write(dumps({
            "variation": run[0],
            "n_hosts": run[1],
            "n_tenants": run[2],
            "n_workers": run[3],
            "time_taken": run[4],
            "optimization_time": run[5],
            "tenant_loads": run[6],
            "status": run[7]["status"]
        }) + "\n")

def run_scale_experiment(n_hosts):
    
    data = []
    
    for n_hosts in n_hosts: #, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]:
        hosts, tenants, workers, n_workers_per_ms = get_topology(n_hosts)
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Quadratic Model===========================")
        start_time = time.time()
        
        result = run_generic_model(hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved Quadratic Model in ", time_taken)
        data.append(["quadratic", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Linear Multiple Times Model===========================")
        start_time = time.time()
        
        result = run_generic_linear_multioptimization_model(hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved Linear Model in ", time_taken)
        data.append(["linear_multiple", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Linear Model 2===========================")
        start_time = time.time()
        
        result, m, t_min, t_consumed = run_generic_linear_model2(hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved Linear Model in ", time_taken)
        data.append(["linear2", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Rerun Linear Model 2===========================")
        
        prev_loads = [t.load for t in tenants]
        print("prev loads:", prev_loads)
        # change tenant loads
        for i in range(len(tenants)):
            tenants[i].load = np.sum(np.random.exponential(
                WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA, size=n_workers_per_ms[i]))
        print("new tenant loads:", [t.load for t in tenants])
        
        start_time = time.time()
        
        result, m, t_min, t_consumed = rerun_generic_linear_model(m, t_min, t_consumed, hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved rerunLinear Model in ", time_taken)
        data.append(["rerun-linear2", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")

        for i in range(len(tenants)):
            tenants[i].load = prev_loads[i]        
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Linear Model===========================")
        start_time = time.time()
        
        result, m, t_min, t_consumed = run_generic_linear_model(hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved Linear Model in ", time_taken)
        data.append(["linear", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")
        
        print("===========================================================")
        print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
        print("=================Rerun Linear Model===========================")
        
        print("prev loads:", [t.load for t in tenants])
        # change tenant loads
        for i in range(len(tenants)):
            tenants[i].load = np.sum(np.random.exponential(
                WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA, size=n_workers_per_ms[i]))
        print("new tenant loads:", [t.load for t in tenants])
        
        start_time = time.time()
        
        result, m, t_min, t_consumed = rerun_generic_linear_model(m, t_min, t_consumed, hosts, tenants, workers)
        
        time_taken = (time.time() - start_time)*1000
        print("Solved rerunLinear Model in ", time_taken)
        data.append(["rerun-linear", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
        write_run_to_log(data[-1], "temp_log.json")
        
    return data

def is_tenant_load_changed(prev_tenant: Tenant, new_tenant: Tenant) -> bool:
    return prev_tenant.load != new_tenant.load

worker_name = str
worker_utilization = float

# strip topology to only include the tenants with changed loads
def strip_topology(
    hosts: List[Host], 
    tenants: List[Tenant], 
    workers: List[Worker], 
    n_workers_per_ms: List[int],
    updated_tenants: List[Tenant],
    worker_util: Dict[worker_name, worker_utilization]) -> Tuple[
        List[Host], List[Tenant], List[Worker]]:
    
    new_hosts = []
    new_tenants = []
    new_workers = []

    TENANT_ID = {t.name: i for i, t in enumerate(tenants)}
    
    # only keep the hosts with workers who belong to a tenant whose load has changed
    # reduce host capacity by worker util if worker is not of the tenant whose load has changed
    # else add it to the list of new workers
    for host in hosts:
        
        new_host = Host(host.name, host.cap)
        
        keep_host = False
        
        for worker_id in host.worker_ids:
            
            worker = workers[worker_id]
            
            tenant_id = TENANT_ID[worker.tenant]
            
            if is_tenant_load_changed(tenants[tenant_id], updated_tenants[tenant_id]):
                
                new_workers.append(Worker(worker.name, worker.tenant, worker.host, worker.tenant_id))
                new_host.worker_ids.append(len(new_workers) - 1)
                keep_host = True
                
            else:
                
                new_host.cap -= worker_util[worker.name]
                
                if new_host.cap < -0.005:
                    print("Host capacity:", new_host.cap)
                    print("Host:", host)
                    print([(str(workers[w_id]), worker_util[workers[w_id].name]) for w_id in host.worker_ids])
                    raise Exception("Host capacity is negative")
        
        if keep_host:
            new_hosts.append(new_host)
    
    # now let's populate new tenants list
    for i, tenant in enumerate(tenants):
        tenant_id = i
        
        if is_tenant_load_changed(tenant, updated_tenants[tenant_id]):
            new_tenants.append(updated_tenants[tenant_id])
            
    NEW_TENANT_ID = {t.name: i for i, t in enumerate(new_tenants)}
    
    for host in new_hosts:
        
        fshare_of_each_worker = host.cap / len(host.worker_ids) if len(host.worker_ids) > 0 else 0.0
        
        for new_worker_id in host.worker_ids:
            new_worker = new_workers[new_worker_id]
            tenant_id = NEW_TENANT_ID[new_worker.tenant]
            new_tenants[tenant_id].fshareload += fshare_of_each_worker
    
    return new_hosts, new_tenants, new_workers

def run_on_complete_input(variation_name, run_model,
                           hosts, tenants, workers, n_workers_per_ms):
    
    data = []
    
    n_hosts = len(hosts)
    
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"================={variation_name}===========================")
    start_time = time.time()
    
    result, m, t_min, t_consumed = run_model(hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved Linear Model in ", time_taken)
    data.append([f"{variation_name}", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "temp_log.json")
    
    return data

from collections import defaultdict

def run_generic_linear_single_objective_model_nov15_abs_diff_simplified(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[any, float]:
    
    global previous_w
    
    print("|||||||||||||||||||| Setting things up")
    
    # =========================== Begin Optimization ===========================
    
    # MIP  model formulation
    m = gp.Model("lb")
    
    # ============================ Variable Setup ============================

    # Precompute bounds and indices
    cap_bounds = {h.name: h.cap for h in _hosts}
    t_load_bounds = {t.name: t.load for t in _tenants}
    t_min_bounds = {t.name: min(t.fshareload, t.load) for t in _tenants}

    # Initialize Gurobi model
    m = gp.Model("optimized_model")

    # Add Variables (optimized batch addition)
    cap = m.addVars(cap_bounds.keys(), lb=cap_bounds, ub=cap_bounds, vtype=GRB.CONTINUOUS, name="cap")
    w = m.addVars([worker.name for worker in _workers], lb=0.0, vtype=GRB.CONTINUOUS, name="w")
    t_load = m.addVars(t_load_bounds.keys(), lb=t_load_bounds, ub=t_load_bounds, vtype=GRB.CONTINUOUS, name="t_load")
    t_min = m.addVars(t_min_bounds.keys(), lb=t_min_bounds, ub=t_min_bounds, vtype=GRB.CONTINUOUS, name="t_min")
    log_sr = m.addVars([t.name for t in _tenants], lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="log_sr")

    # ============================ Objective Setup ============================

    m.setObjective(
        gp.quicksum(t.fshareload * log_sr[t.name] for t in _tenants),
        GRB.MAXIMIZE
    )

    # ============================ Efficient Precomputation ============================

    host_workers = defaultdict(list)
    tenant_workers = defaultdict(list)

    for worker in _workers:
        host_workers[worker.host].append(worker.name)
        tenant_workers[worker.tenant].append(worker.name)

    # ============================ Constraints Setup ============================

    # Constraint 1: Host capacity constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in host_workers[host.name]) <= cap[host.name]
        for host in _hosts),
        name="host_cap"
    )

    # Constraint 2: Tenant upper bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[tenant.name]) <= t_load[tenant.name]
        for tenant in _tenants),
        name="tenant_ub"
    )

    # Constraint 3: Tenant lower bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[tenant.name]) >= t_min[tenant.name]
        for tenant in _tenants),
        name="tenant_lb"
    )

    # Constraint 4: Logarithmic constraints (using GenConstrLog)
    for tenant in _tenants:
        m.addGenConstrLog(t_load[tenant.name], log_sr[tenant.name], name=f"log_sr_{tenant.name}")
    
    # ============================== Optimize! =================================
    
    
    # #  ============================= Set Variables =============================
    
    # # set host capacity for each host
    # cap = {}
    # for h in _hosts:
    #     cap[h.name] = m.addVar(lb=h.cap, ub=h.cap, vtype=GRB.CONTINUOUS,
    #                     name=f"cap_{h.name}")
        
    # # set variables for the workers
    # w = {}
    # log_w = {}
    # for worker in _workers:
    #     w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
    #                        name=f"w_{worker.name}")
    
    # # state for tenant (to be used for rerunning optimization)
    # t_load = {}
    # t_min = {}
    # for tenant in _tenants:
    #     t_load[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, vtype=GRB.CONTINUOUS,
    #                                    name=f"t_{tenant.name}")
    #     t_min_value = min(tenant.fshareload, tenant.load)
    #     t_min[tenant.name] = m.addVar(lb=t_min_value, ub=t_min_value, vtype=GRB.CONTINUOUS,
    #                                  name=f"t_min_{tenant.name}")
    
    # # set spare resources used by a tenant
    # # sr = {}
    # log_sr = {}
    # for tenant in _tenants:
    #     # sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
    #     #                            ub=GRB.INFINITY,
    #     #                            vtype=GRB.CONTINUOUS,
    #     #                            name=f"sr_{tenant.name}")
    #     log_sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
    #                                     ub=GRB.INFINITY,
    #                                     vtype=GRB.CONTINUOUS,
    #                                     name=f"log_sr_{tenant.name}")

    # # Objective 1: max sum(U(sr_t+, w_t), ∀t)
    # #                  where
    # #                  U(sr_t+, w_t) = w_t * log(sr_t+)
    # #                  w_t = fs_t
    # # ∴ obj1 = sum(fs_t * log(sr_t+), ∀t); maximize this
    # obj1 = gp.quicksum((tenant.fshareload * log_sr[tenant.name] for tenant in _tenants))
    # m.setObjective(obj1, GRB.MAXIMIZE)
    
    # # ============================ Set Constraints =============================
    
    # # Constraint 1: for all host h, sum(w ∈ t) <= cap(h)
    # m.addConstrs(
    #     (gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name)) <= cap[host.name]
    #      for host in _hosts),
    #     name="h_cap"
    # )
    
    # # Constraint 2: for all tenants w, sum(w ∈ t) < t_load
    # m.addConstrs(
    #     (gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) <= t_load[tenant.name]
    #      for tenant in _tenants), 
    #     name="t_ub"
    # )
    
    # # Constraint 3: for all tenants w, sum(w ∈ t) > min(tenant.fshareload, tenant.load)
    # for tenant in _tenants:
    #     m.addConstr(
    #         gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) >= t_min[tenant.name],
    #         name=f"t_lb_{tenant.name}"
    #     )
    
    # # ------ Secondary constraints ------
    
    # # Constraint 4: for all tenants, sr_t = sum(w ∈ t) - min(tenant.fshareload, tenant.load),
    # #                                log_sr_t = log(sr_t)
    # for tenant in _tenants:
    #     m.addGenConstrLog(t_load[tenant.name], log_sr[tenant.name], name="log_sr")
    
    # # ============================== Optimize! =================================
    
    print("|||||||||||||||||||| Optimizing...")
    
    start_time = time.time()
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    optimization_time = (time.time() - start_time)*1000
    
    # =========================== Done Optimization ============================
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
        print(vars.keys())
        
    if m.Status == GRB.OPTIMAL:        
        
        vars = {v.varName: v.x for v in m.getVars()}
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
            else:
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
        to_return = {
            "status": m.Status,
            "result": results
        }   
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w[{worker.name}]"] for worker in _workers}
        print("New previous weights:", previous_w)
        
        print(to_return)
        
        return to_return, m, t_min, t_load, optimization_time

    else:
        
        for _ in range(5):
            print("///////////////////////////////////////////////")
        print("\nOptimization failed\n")
        for _ in range(5):
            print("\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\")
        
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
        
        return to_return, m, t_min, t_load, optimization_time

def run_generic_linear_single_objective_model_nov15_abs_diff_simplified_fast_correct(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[any, gp.Model, Tenant_Min, Tenant_Load]:
    
    global previous_w
    
    print("|||||||||||||||||||| Setting things up")
    
    # =========================== Begin Optimization ===========================
    
    # MIP  model formulation
    m = gp.Model("lb")
    
    # ============================ Variable Setup ============================

    # Precompute bounds and indices
    cap_bounds = {h.name: h.cap for h in _hosts}
    t_load_bounds = {t.name: t.load for t in _tenants}
    t_min_bounds = {t.name: min(t.fshareload, t.load) for t in _tenants}

    # print("cap_bounds:", cap_bounds)

    # Initialize Gurobi model
    m = gp.Model("optimized_model")

    # Add Variables (optimized batch addition)
    cap = m.addVars(cap_bounds.keys(), lb=cap_bounds, ub=cap_bounds, vtype=GRB.CONTINUOUS, name="cap")
    w = m.addVars([worker.name for worker in _workers], lb=0.0, vtype=GRB.CONTINUOUS, name="w")
    t_load = m.addVars(t_load_bounds.keys(), lb=t_load_bounds, ub=t_load_bounds, vtype=GRB.CONTINUOUS, name="t_load")
    t_min = m.addVars(t_min_bounds.keys(), lb=t_min_bounds, ub=t_min_bounds, vtype=GRB.CONTINUOUS, name="t_min")
    sr = m.addVars([t.name for t in _tenants], lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="sr")
    log_sr = m.addVars([t.name for t in _tenants], lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS, name="log_sr")

    # ============================ Objective Setup ============================

    m.setObjective(
        gp.quicksum(t.fshareload * log_sr[t.name] for t in _tenants),
        GRB.MAXIMIZE
    )

    # ============================ Efficient Precomputation ============================

    host_workers = defaultdict(list)
    tenant_workers = defaultdict(list)

    for worker in _workers:
        host_workers[worker.host].append(worker.name)
        tenant_workers[worker.tenant].append(worker.name)

    # ============================ Constraints Setup ============================

    # Constraint 1: Host capacity constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in host_workers[host.name]) <= cap[host.name]
        for host in _hosts),
        name="host_cap"
    )

    # Constraint 2: Tenant upper bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[tenant.name]) <= t_load[tenant.name]
        for tenant in _tenants),
        name="tenant_ub"
    )

    # Constraint 3: Tenant lower bound constraints
    m.addConstrs(
        (gp.quicksum(w[worker_name] for worker_name in tenant_workers[tenant.name]) >= t_min[tenant.name]
        for tenant in _tenants),
        name="tenant_lb"
    )
    
    # Constraint 4: for all tenants, sr_t = sum(w ∈ t) - min(tenant.fshareload, tenant.load),
    m.addConstrs(
        ((gp.quicksum(w[worker_name] for worker_name in tenant_workers[tenant.name]) - t_min[tenant.name]) == sr[tenant.name]
        for tenant in _tenants),
        name="sr"
    )
    
    # m.addConstrs(
    #     ((sr[tenant.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) - t_min[tenant.name]) for tenant in _tenants),
    #     name="sr"
    # )
    # Constraint 5: Logarithmic constraints (using GenConstrLog)
    for tenant in _tenants:
        m.addGenConstrLog(sr[tenant.name], log_sr[tenant.name], name=f"log_sr_{tenant.name}")
    
    # ============================== Optimize! =================================
    
    
    # #  ============================= Set Variables =============================
    
    # # set host capacity for each host
    # cap = {}
    # for h in _hosts:
    #     cap[h.name] = m.addVar(lb=h.cap, ub=h.cap, vtype=GRB.CONTINUOUS,
    #                     name=f"cap_{h.name}")
        
    # # set variables for the workers
    # w = {}
    # log_w = {}
    # for worker in _workers:
    #     w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
    #                        name=f"w_{worker.name}")
    
    # # state for tenant (to be used for rerunning optimization)
    # t_load = {}
    # t_min = {}
    # for tenant in _tenants:
    #     t_load[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, vtype=GRB.CONTINUOUS,
    #                                    name=f"t_{tenant.name}")
    #     t_min_value = min(tenant.fshareload, tenant.load)
    #     t_min[tenant.name] = m.addVar(lb=t_min_value, ub=t_min_value, vtype=GRB.CONTINUOUS,
    #                                  name=f"t_min_{tenant.name}")
    
    # # set spare resources used by a tenant
    # # sr = {}
    # log_sr = {}
    # for tenant in _tenants:
    #     # sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
    #     #                            ub=GRB.INFINITY,
    #     #                            vtype=GRB.CONTINUOUS,
    #     #                            name=f"sr_{tenant.name}")
    #     log_sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
    #                                     ub=GRB.INFINITY,
    #                                     vtype=GRB.CONTINUOUS,
    #                                     name=f"log_sr_{tenant.name}")

    # # Objective 1: max sum(U(sr_t+, w_t), ∀t)
    # #                  where
    # #                  U(sr_t+, w_t) = w_t * log(sr_t+)
    # #                  w_t = fs_t
    # # ∴ obj1 = sum(fs_t * log(sr_t+), ∀t); maximize this
    # obj1 = gp.quicksum((tenant.fshareload * log_sr[tenant.name] for tenant in _tenants))
    # m.setObjective(obj1, GRB.MAXIMIZE)
    
    # # ============================ Set Constraints =============================
    
    # # Constraint 1: for all host h, sum(w ∈ t) <= cap(h)
    # m.addConstrs(
    #     (gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name)) <= cap[host.name]
    #      for host in _hosts),
    #     name="h_cap"
    # )
    
    # # Constraint 2: for all tenants w, sum(w ∈ t) < t_load
    # m.addConstrs(
    #     (gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) <= t_load[tenant.name]
    #      for tenant in _tenants), 
    #     name="t_ub"
    # )
    
    # # Constraint 3: for all tenants w, sum(w ∈ t) > min(tenant.fshareload, tenant.load)
    # for tenant in _tenants:
    #     m.addConstr(
    #         gp.quicksum((w[worker.name] for worker in _workers if worker.tenant == tenant.name)) >= t_min[tenant.name],
    #         name=f"t_lb_{tenant.name}"
    #     )
    
    # # ------ Secondary constraints ------
    
    # # Constraint 4: for all tenants, sr_t = sum(w ∈ t) - min(tenant.fshareload, tenant.load),
    # #                                log_sr_t = log(sr_t)
    # for tenant in _tenants:
    #     m.addGenConstrLog(t_load[tenant.name], log_sr[tenant.name], name="log_sr")
    
    # # ============================== Optimize! =================================
    
    print("|||||||||||||||||||| Optimizing...")
    
    start_time = time.time()
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    optimization_time = (time.time() - start_time)*1000
    
    # =========================== Done Optimization ============================
    
    if m.Status != GRB.OPTIMAL:
        
        print([str(host) for host in _hosts])
        print([str(tenant) for tenant in _tenants])
        print([str(worker) for worker in _workers])
        
        # raise Exception(f"Optimization failed with {len(_hosts)} hosts, {len(_tenants)} tenants, and {len(_workers)} workers")
    
    # if m.Status == GRB.OPTIMAL:
    #     vars = {v.varName: v.x for v in m.getVars()}
    #     # print(vars)
    #     # print(vars.keys())
        
    if m.Status == GRB.OPTIMAL:        
        
        vars = {v.varName: v.x for v in m.getVars()}
        
        results = {}
        for worker in _workers:
            if worker.tenant not in results:
                results[worker.tenant] = {}
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
            else:
                results[worker.tenant][worker.name] = vars[f"w[{worker.name}]"]
        to_return = {
            "status": m.Status,
            "result": results
        }   
        
        # set the previous weights to the current weights
        previous_w = {worker.name: vars[f"w[{worker.name}]"] for worker in _workers}
        # print("New previous weights:", previous_w)
        
        # print(to_return)
        
        return to_return, m, t_min, t_load, optimization_time

    else:
        
        for _ in range(5):
            print("///////////////////////////////////////////////")
        print("\nOptimization failed\n")
        for _ in range(5):
            print("\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\")
        
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
        
        # print(to_return)
        
        return to_return, m, t_min, t_load, optimization_time


def run_on_all_input_cases(variation_name, run_model, rerun_model,
                           hosts, tenants, workers, n_workers_per_ms):
    
    data = []
    
    n_hosts = len(hosts)
    
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"================={variation_name}===========================")
    start_time = time.time()
    
    result, m, t_min, t_consumed, optimization_time = run_model(hosts, tenants, workers)
    print(result)   
    
    time_taken = (time.time() - start_time)*1000
    print("Solved Linear Model in ", time_taken)
    data.append([f"{variation_name}", n_hosts, len(tenants), len(workers), time_taken, optimization_time, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "logs_Apr23_4am.json")
    
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"=================Rerun with some topo change {variation_name}===========================")
    
    prev_loads = [t.load for t in tenants]
    print("prev loads:", prev_loads)
    # change tenant loads
    tenants = change_tenant_loads(tenants, 10, 10)
    
    start_time = time.time()
    
    result, m, t_min, t_consumed, optimization_time = rerun_model(m, t_min, t_consumed, hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved rerunLinear Model in ", time_taken)
    data.append([f"{variation_name}_some_change", n_hosts, len(tenants), len(workers), time_taken, optimization_time, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "logs_Apr23_4am.json")

    # change loads back to previous
    for i in range(len(tenants)):
        tenants[i].load = prev_loads[i]
    
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"=================Rerun with full topo change {variation_name}===========================")
    
    prev_loads = [t.load for t in tenants]
    print("prev loads:", prev_loads)
    # change tenant loads
    for i in range(len(tenants)):
        tenants[i].load = np.sum(np.random.exponential(
            WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA, size=n_workers_per_ms[i]))
    print("new tenant loads:", [t.load for t in tenants])
    
    start_time = time.time()
    
    result, m, t_min, t_consumed, optimization_time = rerun_model(m, t_min, t_consumed, hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved rerunLinear Model in ", time_taken)
    data.append([f"{variation_name}_full_change", n_hosts, len(tenants), len(workers), time_taken, optimization_time, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "logs_Apr23_4am.json")

    # change loads back to previous
    for i in range(len(tenants)):
        tenants[i].load = prev_loads[i]
        
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"=================Rerun with some topo change and stripped topology {variation_name}===========================")
    
    prev_loads = [t.load for t in tenants]
    prev_tenants = [Tenant(t.name, t.load, t.fshareload) for t in tenants]
    print("prev loads:", prev_loads)
    # change tenant loads
    tenants = change_tenant_loads(tenants, 10, 10)
    
    w_utils = {}
    for tenant_name in result["result"]:
        for worker_name, util in result["result"][tenant_name].items():
            w_utils[worker_name] = util
    hosts, tenants, workers = strip_topology(hosts, prev_tenants, workers, n_workers_per_ms, tenants, w_utils)
    
    start_time = time.time()
    
    result, m, t_min, t_consumed, optimization_time = run_model(hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved rerunLinear Model in ", time_taken)
    data.append([f"{variation_name}_some_change_strip", n_hosts, len(tenants), len(workers), time_taken, optimization_time, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "logs_Apr23_4am.json")

    # change loads back to previous
    for i in range(len(tenants)):
        tenants[i].load = prev_loads[i]
        
    return data

def merge_workers(
    hosts: List[Host], 
    tenants: List[Tenant],
    workers: List[Worker]) -> Tuple[List[Host], List[Tenant], List[Worker], List[int]]:
    
    merged_workers = []
    
    for worker in workers:
        
        # check if there is already a worker with the same tenant and host
        
        found = False
        for merged_worker in merged_workers:
            if merged_worker.tenant == worker.tenant and merged_worker.host == worker.host:
                found = True
                break
        
        # add only if not found
        if not found:
            merged_workers.append(Worker(
                worker.name, worker.tenant, worker.host, worker.tenant_id))
            
    return hosts, tenants, merged_workers, [1] * len(tenants)

def get_alibaba_topology():
    filename = sys.argv[2]
            
    with open(filename, "r") as f:
        input_json = f.read()
        
    input = json.loads(input_json)
    # print("Input:", input)
    
    _hosts, _tenants, _workers = input[0], input[1], input[2]
    
    hosts = [Host(h["name"], h["cap"]) for h in _hosts]
    tenants = [Tenant(t["name"], t["load"], t["fshareload"]) for t in _tenants]
    workers = [Worker(w["name"], w["tenant"], w["host"]) for w in _workers]
    
    return hosts, tenants, workers


def run_new_scale_experiment(n_hosts):
    
    data = []
    
    for n_hosts in n_hosts: #, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]:
        # hosts, tenants, workers, _ = get_topology(n_hosts)
        
        n_workers_per_ms = []
        
        # if len(sys.argv) > 1:
        #     hosts, tenants, workers = get_alibaba_topology()
        # else:
        hosts, tenants, workers, n_workers_per_ms = get_topology(n_hosts)
        
        # print(f"OG Topology:\t{len(hosts)} hosts, {len(tenants)} tenants, {len(workers)} workers")
        
        # hosts, tenants, workers, n_workers_per_ms = merge_workers(hosts, tenants, workers)
        
        # print(f"Changed to:\t{len(hosts)} hosts, {len(tenants)} tenants, {len(workers)} workers")
        
        # hosts, tenants, workers, n_workers_per_ms = compress_topology(hosts, tenants, workers)
        
        # data += run_on_all_input_cases(
        #     "linear_multiple",
        #     run_generic_linear_multioptimization_model,
        #     rerun_generic_linear_multioptimization_model,
        #     hosts, tenants, workers, n_workers_per_ms)
        
        data += run_on_all_input_cases(
            "single_obj",
            run_generic_linear_single_objective_model_nov15_abs_diff_simplified_fast_correct,
            rerun_generic_linear_single_objective_model_nov15,
            hosts, tenants, workers, n_workers_per_ms)
        
        # data += run_on_all_input_cases(
        #     "linear_model2",
        #     run_generic_linear_model2,
        #     rerun_generic_linear_model,
        #     hosts, tenants, workers, n_workers_per_ms)
        
    return data

df = pd.DataFrame(columns=['variation', 'n_hosts', 'n_tenants', 'n_workers', 'time_taken', 'tenant_loads', 'result'])

n_hosts = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] * 5
n_hosts += list(range(1100, 10000+1, 1000)) * 5
n_hosts += list(range(15000, 40000+1, 5000)) * 5
n_hosts = ([5] + list(range(500, 10000+1, 500))) * 5
# n_hosts += [2000, 3000, 4000, 5000] * 5
print(len(n_hosts))
print(n_hosts)
input()
run_new_scale_experiment(n_hosts)

