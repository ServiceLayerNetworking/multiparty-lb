import numpy as np
import gurobipy as gp
from gurobipy import GRB
import os
from time import time
from flask import Flask, request
from json import dumps
import json
from typing import List, Dict

def run_model(_host_cap, _t0, _t1, _t2):

    # MIP  model formulation
    m = gp.Model("lb")

    host_cap = m.addVar(lb=_host_cap, ub=_host_cap, vtype=GRB.CONTINUOUS,
                        name="host_cap")

    t0 = m.addVar(lb=_t0, ub=_t0, vtype=GRB.CONTINUOUS, name="t0")
    t00 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t00")
    t01 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t01")

    t1 = m.addVar(lb=_t1, ub=_t1, vtype=GRB.CONTINUOUS, name="t1")
    t11 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t11")
    t12 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t12")

    t2 = m.addVar(lb=_t2, ub=_t2, vtype=GRB.CONTINUOUS, name="t2")
    t20 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t20")

    # sp_cap_0 = m.addVar(lb=float("-inf"), vtype=GRB.CONTINUOUS, name="sp_cap_0")
    # sp_cap_1 = m.addVar(lb=float("-inf"), vtype=GRB.CONTINUOUS, name="sp_cap_1")
    # sp_cap_2 = m.addVar(lb=float("-inf"), vtype=GRB.CONTINUOUS, name="sp_cap_2")

    sp_cap_0 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_0")
    sp_cap_1 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_1")
    sp_cap_2 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_2")

    share0 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="share0")
    share1 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="share1")
    share2 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="share2")
    
    fshare0 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="fshare0")
    fshare1 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="fshare1")
    fshare2 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="fshare2")
    
    smallest_sp_cap_log = m.addVar(lb=float("-inf"), vtype=GRB.CONTINUOUS,
                                   name="smallest_sp_cap_log")

    smallest_sp_cap = m.addVar(lb=0, vtype=GRB.CONTINUOUS,
                               name="smallest_sp_cap")

    m.setObjective(smallest_sp_cap_log, GRB.MAXIMIZE)

    m.addGenConstrMin(smallest_sp_cap, [sp_cap_0, sp_cap_1, sp_cap_2],
                      name="min_sp_cap")
    
    m.addGenConstrLog(smallest_sp_cap, smallest_sp_cap_log)

    m.addConstr(t20 + t00 + sp_cap_0 <= host_cap, name="h0")
    m.addConstr(t01 + t11 + sp_cap_1 <= host_cap, name="h1")
    m.addConstr(t12 +       sp_cap_2 <= host_cap, name="h2")

    m.addConstr(t0 >= t00 + t01, name="t0")
    m.addConstr(t1 >= t11 + t12, name="t1")
    m.addConstr(t2 >= t20, name="t2")
    
    m.addConstr(fshare0 == 2 * host_cap, name="fshare_0")
    m.addConstr(fshare1 == 2.5 * host_cap, name="fshare_1")
    m.addConstr(fshare2 == 1 * host_cap, name="fshare_2")
    
    m.addGenConstrMin(share0, [fshare0, t0], name="share0")
    m.addGenConstrMin(share1, [fshare1, t1], name="share1")
    m.addGenConstrMin(share2, [fshare2, t2], name="share2")
    
    m.addConstr(share0 == t00 + t01, name="share_0")
    m.addConstr(share1 == t11 + t12, name="share_1")
    m.addConstr(share2 == t20, name="share_2")

    m.optimize()
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        to_return = {
            "status": m.Status,
            "t00": vars["t00"],
            "t01": vars["t01"],
            "t11": vars["t11"],
            "t12": vars["t12"],
            "t20": vars["t20"],
        }
        print(to_return)
        return to_return
    else:
        to_return = {
            "status": m.Status,
            "t00": 0.0,
            "t01": 0.0,
            "t11": 0.0,
            "t12": 0.0,
            "t20": 0.0,
        }
        print(to_return)
        return to_return

def run_new_model(_host_cap, _t0, _t1, _t2):

    # MIP  model formulation
    m = gp.Model("lb")

    host_cap = m.addVar(lb=_host_cap, ub=_host_cap, vtype=GRB.CONTINUOUS, name="host_cap")

    t_min = m.addVar(lb=0.0, ub=0.0, vtype=GRB.CONTINUOUS, name="t_min")

    t0 = m.addVar(lb=_t0, ub=_t0, vtype=GRB.CONTINUOUS, name="t0")
    t00 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t00")
    t01 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t01")

    t1 = m.addVar(lb=_t1, ub=_t1, vtype=GRB.CONTINUOUS, name="t1")
    t11 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t11")
    t12 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t12")

    t2 = m.addVar(lb=_t2, ub=_t2, vtype=GRB.CONTINUOUS, name="t2")
    t20 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="t20")
    
    h0_sum = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="h0_sum")
    h1_sum = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="h1_sum")
    h2_sum = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="h2_sum")

    h0_log = m.addVar(vtype=GRB.CONTINUOUS, name="h0_log")
    h1_log = m.addVar(vtype=GRB.CONTINUOUS, name="h1_log")
    h2_log = m.addVar(vtype=GRB.CONTINUOUS, name="h2_log")

    # sp_cap_0 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_0")
    # sp_cap_1 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_1")
    # sp_cap_2 = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="sp_cap_2")

    # smallest_sp_cap = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
    #       name="smallest_sp_cap")

    # objective = (h0_log + h1_log + h2_log) + \
    #     ((host_cap - h0_sum) + (host_cap - h1_sum) + (host_cap - h2_sum))

    m.setObjective((h0_log + h1_log + h2_log) + \
        ((host_cap - h0_sum) + (host_cap - h1_sum) + (host_cap - h2_sum)), GRB.MAXIMIZE)

    # m.addGenConstrMin(smallest_sp_cap, [sp_cap_0, sp_cap_1, sp_cap_2],
    #       name="min_sp_cap")

    m.addConstr(t20 + t00 <= host_cap, name="h0")
    m.addConstr(t01 + t11 <= host_cap, name="h1")
    m.addConstr(t12       <= host_cap, name="h2")
    
    # add constraint for sum of each host
    m.addConstr(t20 + t00 == h0_sum, name="h0_sum")
    m.addConstr(t01 + t11 == h1_sum, name="h1_sum")
    m.addConstr(t12       == h2_sum, name="h2_sum")
    
    m.addGenConstrLog(h0_sum, h0_log)
    m.addGenConstrLog(h1_sum, h1_log)
    m.addGenConstrLog(h2_sum, h2_log)

    m.addConstr(t00 + t01 >= t0, name="t0")
    m.addConstr(t11 + t12 >= t1, name="t1")
    m.addConstr(t20       >= t2, name="t2")
    
    m.addConstr(t00 + t01 >= t_min, name="t0")
    m.addConstr(t11 + t12 >= t_min, name="t1")
    m.addConstr(t20       >= t_min, name="t2")
    
    m.optimize()
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        to_return = {
            "status": m.Status,
            "t00": vars["t00"],
            "t01": vars["t01"],
            "t11": vars["t11"],
            "t12": vars["t12"],
            "t20": vars["t20"],
        }
        # print(vars)
        return to_return
    else:
        to_return = {
            "status": m.Status,
            "t00": 0.0,
            "t01": 0.0,
            "t11": 0.0,
            "t12": 0.0,
            "t20": 0.0,
        }
        # print(vars)
        return to_return

def run_general_model(_host_cap: float, _t: List[float]) -> str:

    # MIP  model formulation
    m = gp.Model("lb")
    
    n_hosts = len(_t)
    n_tenants = len(_t)
    
    host_cap = m.addVar(lb=_host_cap, ub=_host_cap, vtype=GRB.CONTINUOUS,
                        name="host_cap")
    
    t = [m.addVar(lb=_t[i], ub=_t[i], vtype=GRB.CONTINUOUS, name=f"t{i}")
         for i in range(n_tenants)]

    w = {}
    
    for tenant in range(n_tenants):
        hosts = [tenant] if tenant == 0 else [tenant-1, tenant]
        for host in hosts:
            w[tenant, host] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                       name=f"w{tenant}{host}")
            
    print(w)
             
    sp = {}
    for host in range(n_hosts):
        sp[host] = m.addVar(vtype=GRB.CONTINUOUS, name=f"sp{host}")
        
    log_sp = {}
    for host in range(n_hosts):
        log_sp[host] = m.addVar(vtype=GRB.CONTINUOUS, name=f"log_sp{host}")
    
    share = {}
    for tenant in range(n_tenants):
        share[tenant] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"share{tenant}")
        
    fshare = {}
    for tenant in range(n_tenants):
        fshare[tenant] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"fshare{tenant}")
        
    smallest_log_sp_cap = m.addVar(vtype=GRB.CONTINUOUS,
                               name="smallest_sp_cap")
    
    m.setObjective(smallest_log_sp_cap, GRB.MAXIMIZE)
    
    m.addGenConstrMin(smallest_log_sp_cap,
                      [sp[host] for host in range(n_hosts)],
                      name="min_sp_cap")
    
    # for host in range(n_hosts):
    #     m.addGenConstrLog(sp[host], log_sp[host], name=f"log_sp{host}")
   
    for host in range(n_hosts):
        m.addConstr(gp.quicksum((w[tenant, host]
                                for tenant in (
                                    [host] if host == (n_hosts - 1) else [host, host+1])))
                    + sp[host] == host_cap,
                    name=f"h{host}")
    
    for tenant in range(n_tenants):
        m.addConstr(
            gp.quicksum(
                (w[tenant, host]
                for host in ([tenant] if tenant == 0 else [tenant, tenant-1]))) 
            <= t[tenant],
            name=f"t{tenant}")

    for tenant in range(n_tenants):
        if tenant == 0:
            m.addConstr(fshare[tenant] == 0.5 * host_cap, name=f"fshare{tenant}")
        elif tenant == n_tenants - 1:
            m.addConstr(fshare[tenant] == 1.5 * host_cap, name=f"fshare{tenant}")
        else:
            m.addConstr(fshare[tenant] == 1 * host_cap, name=f"fshare{tenant}")
            
    for tenant in range(n_tenants):
        m.addGenConstrMin(share[tenant], [fshare[tenant], t[tenant]],
                          name=f"share{tenant}")
        
    for tenant in range(n_tenants):
        m.addConstr(
            share[tenant] <= gp.quicksum(
                (w[tenant, host]
                    for host in ([tenant] if tenant == 0 else [tenant, tenant-1]))),
            name=f"share_{tenant}")
        
    m.optimize()
    
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        print(vars)
        
    if m.Status == GRB.OPTIMAL:
        vars = {v.varName: v.x for v in m.getVars()}
        to_return = {
            "status": m.Status,
            "t00": vars["w10"] + 0.00001,
            "t01": vars["w11"] + 0.00001,
            "t11": vars["w21"] + 0.00001,
            "t12": vars["w22"] + 0.00001,
            "t20": vars["w00"] + 0.00001,
        }
        print(to_return)
        return to_return
    else:
        to_return = {
            "status": m.Status,
            "t00": 0.0 + 0.00001,
            "t01": 0.0 + 0.00001,
            "t11": 0.0 + 0.00001,
            "t12": 0.0 + 0.00001,
            "t20": 0.0 + 0.00001,
        }
        print(to_return)
        return to_return

class Host:
    def __init__(self, name: str, cap: float):
        self.name: str = name
        self.cap: str = cap

class Tenant:
    def __init__(self, name: str, load: float, fshare: float = 0.0):
        self.name: str = name
        self.load: float = load
        self.fshareload: float = fshare

class Worker:
    def __init__(self, name: str, tenant: str, host: str):
        self.name: str = name
        self.tenant: str = tenant
        self.host: str = host
        
def run_generic_model(
    _hosts: List[Host],
    _tenants: List[Tenant],
    _workers: List[Worker]):
    
    # =========================== Begin Optimization ===========================
    
    # MIP  model formulation
    m = gp.Model("lb")
    
    #  ============================= Set Variables =============================
    
    # set host capacity for each host
    cap = {}
    for h in _hosts:
        cap[h.name] = m.addVar(lb=h.cap, ub=h.cap, vtype=GRB.CONTINUOUS,
                        name=f"cap_{h.name}")
    
    # set variables for the tenant loads
    t = {}
    for tenant in _tenants:
        t[tenant.name] = m.addVar(lb=tenant.load, ub=tenant.load, 
                                  vtype=GRB.CONTINUOUS, name=f"t_{tenant.name}")
    
    # set variables for the workers
    w = {}   
    for worker in _workers:
        w[worker.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                           name=f"w_{worker.name}")
    
    print(w)
    
    # set spare caps
    sp = {}
    for host in _hosts:
        sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS, name=f"sp_{host.name}")
    log_sp = {}
    for host in _hosts:
        log_sp[host.name] = m.addVar(vtype=GRB.CONTINUOUS,
                                     name=f"log_sp_{host.name}")
        
    share = {}
    for tenant in _tenants:
        share[tenant.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"share_{tenant.name}")
        
    fshare = {}
    for tenant in _tenants:
        fshare[tenant.name] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS,
                                 name=f"fshare_{tenant.name}")
    
    smallest_log_sp_cap = m.addVar(vtype=GRB.CONTINUOUS,
                                 name="smallest_sp_cap")
    
    # ============================= Set Objective ==============================
    
    m.setObjective(smallest_log_sp_cap, GRB.MAXIMIZE)
    
    # ============================ Set Constraints =============================
    
    # smallest_log_sp_cap = min(sp)
    m.addGenConstrMin(smallest_log_sp_cap,
                        [sp[host.name] for host in _hosts],
                        name="min_sp_cap")
    
    # for host in _hosts:
    #     m.addGenConstrLog(sp[host.name], log_sp[host.name],
    #                       name=f"log_sp{host}")
    
    # at each host, sum(w) + sp = cap
    for host in _hosts:
        m.addConstr(gp.quicksum(
            (w[worker.name] for worker in _workers if worker.host == host.name))
                    + sp[host.name] == cap[host.name],
                    name=f"h_{host.name}")
    
    for tenant in _tenants:
        print()
        print(tenant.name, [worker.name
              for worker in _workers if worker.tenant == tenant.name])
        print()
        
    # at each tenant, sum(w) <= t
    for tenant in _tenants:
        m.addConstr(
            gp.quicksum(
                (w[worker.name]
                for worker in _workers if worker.tenant == tenant.name)) 
            <= t[tenant.name],
            name=f"t_{tenant.name}")
    
    # for each tenant, set fshare
    for tenant in _tenants:
        m.addConstr(fshare[tenant.name] == tenant.fshareload, 
                    name=f"fshare_{tenant.name}")
    
    # for each tenant, share = min(fshare, t)
    for tenant in _tenants:
        m.addGenConstrMin(share[tenant.name],
                          [fshare[tenant.name], t[tenant.name]],
                          name=f"share_{tenant.name}")
    
    # for each tenant, share(tenant) <= sum(w)
    for tenant in _tenants:
        m.addConstr(share[tenant.name] <= 
                    gp.quicksum((w[worker.name] 
                                 for worker in _workers 
                                 if worker.tenant == tenant.name)), 
                    name=f"share_{tenant}")
    
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
    return run_generic_model(hosts, tenants, workers)
    
# test run for the 3-node scenario on the newly written generic model func
def test_3_node_run_generic_model(host_cap, tenant_loads):
    
    hosts = [
        Host("0", host_cap),
        Host("1", host_cap),
        Host("2", host_cap)
    ]
    tenants = [
        Tenant("0", tenant_loads[0], 0.5 * host_cap),
        Tenant("1", tenant_loads[1], 1.5 * host_cap),
        Tenant("2", tenant_loads[2], 1.5 * host_cap)
    ]
    workers = [
        Worker("00", "0", "0"),
        Worker("10", "1", "0"),
        Worker("11", "1", "1"),
        Worker("21", "2", "1"),
        Worker("22", "2", "2"),        
    ]
    
    return run_generic_model(hosts, tenants, workers)
    
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def gurobi_server():
    
    print("======================reached here")
    
    if request.method == "GET":
    
        print("reached here", request.args, request.args["host_cap"])
        start_time = time()
        
        variables = run_general_model(
            float(request.args["host_cap"]), 
            [float(request.args["t2"]),
            float(request.args["t0"]),
            float(request.args["t1"])])
       
        time_taken = time() - start_time
        print(f"{time_taken*1000:.2f} ms")
        
        return dumps(variables)
        
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
            print("Invalid argument, use -sample_json to run sample json")
            
    else:
        print("======================reached here")
        app.run(host="localhost", port=5000, debug=True)
    
    # run_general_model(210, [79.8, 119, 202])
    # b = test_3_node_run_generic_model(200, [100, 300, 200])
    
    # print(a)
    # print(b)
    
    # # run_general_model(2, [89/100, 236/100, 185/100])
    # result = run_general_model(float(sys.argv[1]), [float(v) for v in sys.argv[2:]])
    
    # print()
    
    # print(
    #     {
    #         "node1-app3": f'{result["t20"]:.2f}',
    #         "node1-app1": f'{result["t00"]:.2f}',
    #         "node2-app1": f'{result["t01"]:.2f}',
    #         "node2-app2": f'{result["t11"]:.2f}',
    #         "node3-app2": f'{result["t12"]:.2f}'
    #     }
    # )

# run_model(20, 100, 30, 10)

# times = {}

# for size in [1, 10, 100, 1000, 10000, 100000]:

#     a = np.random.randint(0, 30, size=size)

#     start_time = time()
#     run_general_model(20, a)
#     time_taken = time() - start_time
#     print(f"{time_taken*1000:.2f} ms")

#     a = np.random.randint(0, 30, size=size)

#     start_time = time()
#     run_general_model(20, a)
#     time_taken = time() - start_time
#     print(f"{time_taken*1000:.2f} ms")
    
#     times[size] = time_taken*1000
    
# print(times)

# run_general_model(20, [10, 100, 40])