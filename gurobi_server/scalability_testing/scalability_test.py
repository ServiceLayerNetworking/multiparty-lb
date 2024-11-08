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

Tenant_Min = Dict[str, gp.Var]
Tenant_Consumed = Dict[str, gp.Var]

previous_w: Dict[str,float] = {}
 
N_WORKERS_EXPONENTIAL_DISTR_LAMBDA = 17
WORKER_LOAD_EXPONENTIAL_DISTR_LAMBDA = 0.075 #0.7
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
            "tenant_loads": run[5],
            "status": run[6]["status"]
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

def run_on_all_input_cases(variation_name, run_model, rerun_model,
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
    
    print("===========================================================")
    print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    print(f"=================Rerun with some topo change {variation_name}===========================")
    
    prev_loads = [t.load for t in tenants]
    print("prev loads:", prev_loads)
    # change tenant loads
    tenants = change_tenant_loads(tenants, 10, 10)
    
    start_time = time.time()
    
    result, m, t_min, t_consumed = rerun_model(m, t_min, t_consumed, hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved rerunLinear Model in ", time_taken)
    data.append([f"{variation_name}_some_change", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "temp_log.json")

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
    
    result, m, t_min, t_consumed = rerun_model(m, t_min, t_consumed, hosts, tenants, workers)
    
    time_taken = (time.time() - start_time)*1000
    print("Solved rerunLinear Model in ", time_taken)
    data.append([f"{variation_name}_full_change", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
    write_run_to_log(data[-1], "temp_log.json")

    # change loads back to previous
    for i in range(len(tenants)):
        tenants[i].load = prev_loads[i]
        
    # print("===========================================================")
    # print(f"Topology: {n_hosts} hosts, {len(tenants)} tenants, {len(workers)} workers")
    # print(f"=================Rerun with some topo change and stripped topology {variation_name}===========================")
    
    # prev_loads = [t.load for t in tenants]
    # prev_tenants = [Tenant(t.name, t.load, t.fshareload) for t in tenants]
    # print("prev loads:", prev_loads)
    # # change tenant loads
    # tenants = change_tenant_loads(tenants, 10, 10)
    
    # w_utils = {}
    # for tenant_name in result["result"]:
    #     for worker_name, util in result["result"][tenant_name].items():
    #         w_utils[worker_name] = util
    # hosts, tenants, workers = strip_topology(hosts, prev_tenants, workers, n_workers_per_ms, tenants, w_utils)
    
    # start_time = time.time()
    
    # result, m, t_min, t_consumed = run_model(hosts, tenants, workers)
    
    # time_taken = (time.time() - start_time)*1000
    # print("Solved rerunLinear Model in ", time_taken)
    # data.append([f"{variation_name}_some_change_strip", n_hosts, len(tenants), len(workers), time_taken, [t.load for t in tenants], result])
    # write_run_to_log(data[-1], "temp_log.json")

    # # change loads back to previous
    # for i in range(len(tenants)):
    #     tenants[i].load = prev_loads[i]
        
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

def run_new_scale_experiment(n_hosts):
    
    data = []
    
    for n_hosts in n_hosts: #, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]:
        hosts, tenants, workers, n_workers_per_ms = get_topology(n_hosts)
        
        # print(f"OG Topology:\t{len(hosts)} hosts, {len(tenants)} tenants, {len(workers)} workers")
        
        # hosts, tenants, workers, n_workers_per_ms = merge_workers(hosts, tenants, workers)
        
        # print(f"Changed to:\t{len(hosts)} hosts, {len(tenants)} tenants, {len(workers)} workers")
        
        # hosts, tenants, workers, n_workers_per_ms = compress_topology(hosts, tenants, workers)
        
        data += run_on_all_input_cases(
            "linear_multiple",
            run_generic_linear_multioptimization_model,
            rerun_generic_linear_multioptimization_model,
            hosts, tenants, workers, n_workers_per_ms)
        
        # data += run_on_all_input_cases(
        #     "linear_model2",
        #     run_generic_linear_model2,
        #     rerun_generic_linear_model,
        #     hosts, tenants, workers, n_workers_per_ms)
        
    return data



df = pd.DataFrame(columns=['variation', 'n_hosts', 'n_tenants', 'n_workers', 'time_taken', 'tenant_loads', 'result'])

n_hosts = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 200] * 5 + [300] * 5
n_hosts += [400, 500] * 5
n_hosts += [600] * 5

n_hosts = [400, 500, 600] * 1
print(n_hosts)
input()
run_new_scale_experiment(n_hosts)

# df = pd.concat([df, pd.DataFrame(run_scale_experiment(), columns=['n_hosts', 'time_taken'])])
# df

# for _ in range(1, 10):
#     for n_hosts in [1, 3, 5, 10, 100, 150, 200, 250, 300, 350]:
#         data = run_scale_experiment([n_hosts])
#         with open("scale_experiment_log.json", "a") as f:
#             for run in data:
#                 f.write(dumps({
#                     "variation": run[0],
#                     "n_hosts": run[1],
#                     "n_tenants": run[2],
#                     "n_workers": run[3],
#                     "time_taken": run[4],
#                     "tenant_loads": run[5],
#                     "result": run[6]
#                 }) + "\n")
#         # df = pd.concat([df, pd.DataFrame(data, columns=['variation', 'n_hosts', 'n_tenants', 'n_workers', 'time_taken', 'tenant_loads', 'result'])])

# for _ in range(1, 10):
#     for n_hosts in [400, 450, 500, 550, 600]:
#         data = run_scale_experiment([n_hosts])
#         with open("scale_experiment_log.json", "a") as f:
#             for run in data:
#                 f.write(dumps({
#                     "variation": run[0],
#                     "n_hosts": run[1],
#                     "n_tenants": run[2],
#                     "n_workers": run[3],
#                     "time_taken": run[4],
#                     "tenant_loads": run[5],
#                     "result": run[6]
#                 }) + "\n")
#         # df = pd.concat([df, pd.DataFrame(data, columns=['variation', 'n_hosts', 'n_tenants', 'n_workers', 'time_taken', 'tenant_loads', 'result'])])

# for _ in range(1, 3):
#     for n_hosts in range(1, 40+1):
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)

# for _ in range(1, 10):
#     for n_hosts in range(31, 40+1):
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)
            
# for _ in range(1, 10):
#     for n_hosts in [50, 60, 70, 80, 90, 100]:
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)
            
# for _ in range(1, 10):
#     for n_hosts in [150, 200, 250, 300]:
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)
            
# for n_hosts in [400, 450, 500, 550, 600]:
#     data = run_scale_experiment([n_hosts])
#     for run in data:
#         write_run_to_log(run)
            
# for _ in range(1, 10):
#     for n_hosts in [400, 450, 500]:
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)
            
# for _ in range(1, 10):
#     for n_hosts in [550, 600]:
#         data = run_scale_experiment([n_hosts])
#         for run in data:
#             write_run_to_log(run)

# def test_change_tenant_loads():
    
#     _, tenants, _, _ = get_topology(200)
    
#     for i, tenant in enumerate(tenants):
#         print(f"Tenant {i}: {str(tenant)}")
#     tenants = change_tenant_loads(tenants, 10, 10)
    
#     print("New Tenants:")
#     for i, tenant in enumerate(tenants):
#         print(f"Tenant {i}: {str(tenant)}")
    
# test_change_tenant_loads()

# [
#     ('tenant1_7: tenant=tenant1, host=host19', 0.1223701209829442),
#     ('tenant7_1: tenant=tenant7, host=host19', 0.11159946280458233),
#     ('tenant12_21: tenant=tenant12, host=host19', 0.0),
#     ('tenant12_46: tenant=tenant12, host=host19', 0.0),
#     ('tenant18_8: tenant=tenant18, host=host19', 0.0),
#     ('tenant23_13: tenant=tenant23, host=host19', 0.0),
#     ('tenant24_27: tenant=tenant24, host=host19', 0.0),
#     ('tenant36_5: tenant=tenant36, host=host19', 0.09945848062253526),
#     ('tenant40_3: tenant=tenant40, host=host19', 0.0),
#     ('tenant40_20: tenant=tenant40, host=host19', 0.6014644233653359),
#     ('tenant41_6: tenant=tenant41, host=host19', 0.06510751222460237),
#     ('tenant41_54: tenant=tenant41, host=host19', 0.0),
#     ('tenant44_4: tenant=tenant44, host=host19', 0.0),
#     ('tenant44_30: tenant=tenant44, host=host19', 0.0)
# ]

# 1-0.06510751222460237-0.6014644233653359-0.09945848062253526-0.11159946280458233-0.1223701209829442