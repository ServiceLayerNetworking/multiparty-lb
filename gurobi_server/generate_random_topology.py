from typing import List, Tuple
import time
import numpy as np

from gurobi_server import run_generic_model

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

def get_topology(n_hosts: int) -> Tuple[List[Host], List[Tenant], List[Worker]]:
    
    print(f"number of hosts: {n_hosts}")
    
    n_tenants = int(n_hosts * 0.65)
    print(f"number of tenants: {n_tenants}")    
    
    n_workers_per_ms = list(map(int, np.random.exponential(
        N_WORKERS_EXPONENTIAL_DISTR_LAMBDA, size=n_tenants)))
    print(f"number of workers: {np.sum(n_workers_per_ms)}")
    
    hosts = [Host(f"host{i}", 1.0) for i in range(n_hosts)]
    
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
    
    print("Hosts:")
    for host in hosts:
        print(host)
    
    print("Tenants:")
    for tenant in tenants:
        print(tenant)
        
    print("Workers:")
    for worker in workers:
        print(worker)
    
    return hosts, tenants, workers

def run_scale_experiment():
    
    n_hosts = [125, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]
    times = []
    
    for n_hosts in [100]: #, 125, 250, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000]:
        hosts, tenants, workers = get_topology(n_hosts)
        
        start_time = time.time()
        run_generic_model(hosts, tenants, workers)
        time_taken = time.time() - start_time
        
        print(f"Time taken for {n_hosts} hosts: {time_taken*1000:.2f}ms")


run_scale_experiment()