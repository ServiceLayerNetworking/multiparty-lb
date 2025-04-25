import numpy as np
import gurobipy as gp
from gurobipy import GRB
import os
from time import time
from flask import Flask, request
from json import dumps
import json
from typing import Tuple, List, Dict
from collections import defaultdict

Tenant_Min = Dict[str, gp.Var]
Tenant_Consumed = Dict[str, gp.Var]
Tenant_Load = Dict[str, gp.Var]

previous_w: Dict[str,float] = {}
is_objective_simple: bool = True

GUROBI_PORT = 4876

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

# Linear Single Combined Objective
def run_generic_linear_single_objective_model_nov15_abs_diff(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[any, gp.Model, Tenant_Min, Tenant_Load]:
    
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
        
    # # Constraint 6: for all workers, log_w = log(w)
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
        
        return to_return, m, t_min, t_load

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
        # raise Exception("The topology has changed, please rerun the optimization from scratch")
        
        return run_generic_linear_single_objective_model_nov15_abs_diff(_hosts, _tenants, _workers)
    
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
            "status": statuses,
            "result": results
        }
        
        print(to_return)
        
        return to_return, m, t_min, t_load

# Linear Single Combined Objective
def run_generic_linear_single_objective_model_nov15_abs_diff_simplified(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]) -> Tuple[any, gp.Model, Tenant_Min, Tenant_Load]:
    
    global previous_w
    
    print("|||||||||||||||||||| Setting things up")
    
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
        sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
                                   ub=GRB.INFINITY,
                                   vtype=GRB.CONTINUOUS,
                                   name=f"sr_{tenant.name}")
        log_sr[tenant.name] = m.addVar(lb=-GRB.INFINITY,
                                        ub=GRB.INFINITY,
                                        vtype=GRB.CONTINUOUS,
                                        name=f"log_sr_{tenant.name}")
    
    # set spare capacities at hosts
    # sp = {}
    # log_sp = {}
    # for host in _hosts:
    #     sp[host.name] = m.addVar(lb=0.0,
    #                              ub=host.cap,
    #                              vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
    #     log_sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS,
    #                                  lb=-GRB.INFINITY,
    #                                  ub=GRB.INFINITY,
    #                                  name=f"log_sp_{host.name}")
    
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
    # obj2 = gp.quicksum([log_sp[host.name] for host in _hosts])
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
    
    # obj1_w = np.sum([host.cap for host in _hosts])
    # obj2_w = 0.1
    # obj3_w = 0.001
    # obj = obj1_w * obj1 + obj2_w * obj2 + obj3_w * obj3
    m.setObjective(obj1, GRB.MAXIMIZE)
        
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
    # m.addConstrs(
    #     ((sp[host.name] == gp.quicksum((w[worker.name] for worker in _workers if worker.host == host.name))) for host in _hosts),
    #     name="sp"
    # )
    # for host in _hosts:
    #     m.addGenConstrLog(sp[host.name], log_sp[host.name], name=f"log_sp_{host.name}")
        
    # # # Constraint 6: for all workers, log_w = log(w)
    # for worker in _workers:
    #     m.addGenConstrLog(w[worker.name], log_w[worker.name], name=f"log_w_{worker.name}")
    
    # ============================== Optimize! =================================
    
    print("|||||||||||||||||||| Optimizing...")
    
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
        
        return to_return, m, t_min, t_load

def run_generic_linear_single_objective_model_nov15_abs_diff_simplified_fast(
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
    
    start_time = time()
    
    # m.setParam('FeasibilityTol', 1e-9)  # Set a tighter feasibility tolerance, if desired
    m.optimize()
    
    optimization_time = (time() - start_time)*1000
    
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


# run generic model from json input (from cc)
def run_from_json(hosts, tenants, workers):
    hosts = [Host(h["name"], h["cap"]) for h in hosts]
    tenants = [Tenant(t["name"], t["load"], t["fshareload"]) for t in tenants]
    workers = [Worker(w["name"], w["tenant"], w["host"]) for w in workers]
    
    # global previous_w
    # previous_w = {'app1-node1': 105.6, 'app1-node2': 95.4, 'app2-node1': 95.4, 'app2-node2': 105.6}
    
    if is_objective_simple:
        to_return = run_generic_linear_single_objective_model_nov15_abs_diff_simplified_fast(hosts, tenants, workers)[0]
    else:
        to_return = run_generic_linear_single_objective_model_nov15_abs_diff(hosts, tenants, workers)[0]
    
    # # print(previous_w)
    print("Objective was simplified:", is_objective_simple)
    
    return to_return
    # return run_generic_model(hosts, tenants, workers)
    
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

@app.route('/simplify_objective', methods=['GET'])
def simplify_objective():
    
    global is_objective_simple
    is_objective_simple = True
    
    return "Objective simplified"

@app.route('/complicate_objective', methods=['GET'])
def complicate_objective():
    
    global is_objective_simple
    is_objective_simple = False
    
    return "Objective complicated"

@app.route('/reset', methods=['GET'])
def reset_weights():
    
    global previous_w
    previous_w = {}
    
    return "Weights reset!"

@app.route('/set', methods=['POST'])
def set_weights():
    
    global previous_w
    
    start_time = time()
    print("reached here")
    request_data = request.get_json(force=False)
    print("Received:", request_data)
    previous_w = request_data
    
    return "Weights set: " + str(previous_w)

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
            # print("Input:", input)
            
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
        app.run(host="localhost", port=GUROBI_PORT, debug=True)
        
    # run started on 7:06pm