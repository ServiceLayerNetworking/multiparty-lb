from collections import defaultdict
from json import dumps
from time import time
from typing import Dict, List, Tuple
import json
import sys

from gurobipy import GRB


class Host:
    def __init__(self, name: str, cap: float):
        self.name = name
        self.cap = cap
        self.worker_ids: List[int] = []

    def __str__(self):
        return f"{self.name}: cap={self.cap}, n_workers={len(self.worker_ids)}"


class Tenant:
    def __init__(self, name: str, load: float):
        self.name = name
        self.load = load

    def __str__(self):
        return f"{self.name}: load={self.load}"


class Worker:
    def __init__(self, name: str, tenant: str, host: str):
        self.name = name
        self.tenant = tenant
        self.host = host
        self.load = 0.0
        self.processed = 0.0

    def __str__(self):
        return f"{self.name}: load={self.load}, processed={self.processed}"


def get_max_min_processing_times(
    total_time: float,
    job_times: Dict[str, float],
) -> Dict[str, Tuple[float, float]]:
    """Apply the same per-worker max-min processor sharing used by PSLB."""

    sorted_jobs = sorted(job_times.items(), key=lambda item: item[1])

    job_stats = {}
    curr_time = 0.0
    per_job_curr_time = 0.0
    current_jobs = list(sorted_jobs)

    for job_name, job_finish_time in sorted_jobs:
        prev_curr_time = curr_time
        curr_time += (job_finish_time - per_job_curr_time) * len(current_jobs)

        if curr_time <= total_time:
            per_job_curr_time = job_finish_time
        else:
            time_left = total_time - prev_curr_time
            per_job_curr_time += time_left / len(current_jobs)
            curr_time = total_time

        job_stats[job_name] = (per_job_curr_time, curr_time)
        current_jobs = current_jobs[1:]

    return job_stats


def get_nodal_optimal_load_distribution_fast(
    hosts: List[Host],
    tenants: List[Tenant],
    workers: List[Worker],
    epsilon: float = 1e-12,
    max_iterations: int = 10_000,
) -> Dict[str, Dict[str, float]]:
    """Compute the fixed point of node-aggregated proportional routing.

    This mirrors ``get_locally_optimal_load_distribution_fast`` except for the
    routing signal.  PSLB gives each endpoint a weight equal to the work that
    endpoint processed in the previous iteration.  NLLB gives each endpoint a
    weight equal to the total work processed by every endpoint on its host.

    All endpoints on one host therefore expose the same node-level signal.  If
    a tenant has multiple endpoints on that host, each endpoint inherits that
    signal, which matches endpoint selection using a node-aggregated metric.
    When every reachable node has processed zero work, the tenant load is split
    equally among its endpoints, as in the PSLB implementation.

    After routing, every host processes its assigned endpoint loads using the
    same per-worker max-min fair sharing routine as the PSLB implementation.
    The route/process steps repeat until no worker's processed load changes by
    more than ``epsilon`` or ``max_iterations`` is reached.
    """

    for worker in workers:
        worker.processed = 0.0

    tenant_to_workers = defaultdict(list)
    host_to_workers = defaultdict(dict)
    for worker in workers:
        tenant_to_workers[worker.tenant].append(worker)
        host_to_workers[worker.host][worker.name] = worker

    for i_iteration in range(max_iterations):
        is_worker_processed_changed = False

        print(f"Iteration #{i_iteration}")

        # Use one aggregate processing signal for every endpoint on a host.
        host_processed = {
            host.name: sum(
                worker.processed
                for worker in host_to_workers[host.name].values()
            )
            for host in hosts
        }

        # Distribute each tenant's load among its endpoints in proportion to
        # the aggregate work processed on their respective hosts.
        for tenant in tenants:
            tenant_workers = tenant_to_workers[tenant.name]
            total_processing = sum(
                host_processed[worker.host] for worker in tenant_workers
            )

            if total_processing > 0:
                for worker in tenant_workers:
                    worker.load = tenant.load * (
                        host_processed[worker.host] / total_processing
                    )
            else:
                equal_load = tenant.load / len(tenant_workers)
                for worker in tenant_workers:
                    worker.load = equal_load

        # Preserve the PSLB model's per-worker max-min fair processing at each
        # host.  Only the preceding routing signal differs.
        for host in hosts:
            workers_on_host = host_to_workers[host.name]
            worker_loads = {
                name: worker.load for name, worker in workers_on_host.items()
            }
            fair_shares = get_max_min_processing_times(host.cap, worker_loads)

            for name, (new_processed, _time_to_process_load) in fair_shares.items():
                worker = workers_on_host[name]
                if abs(worker.processed - new_processed) > epsilon:
                    is_worker_processed_changed = True
                worker.processed = new_processed

        if not is_worker_processed_changed:
            break

    results = defaultdict(dict)
    for worker in workers:
        results[worker.tenant][worker.name] = worker.processed

    return {
        "status": GRB.OPTIMAL,
        "result": dict(results),
    }


def run_from_json(hosts, tenants, workers):
    """Run the NLLB fluid model from the shared optimizer JSON schema."""

    parsed_hosts = [Host(host["name"], host["cap"]) for host in hosts]
    parsed_tenants = [Tenant(tenant["name"], tenant["load"]) for tenant in tenants]
    parsed_workers = [
        Worker(worker["name"], worker["tenant"], worker["host"])
        for worker in workers
    ]

    return get_nodal_optimal_load_distribution_fast(
        parsed_hosts,
        parsed_tenants,
        parsed_workers,
    )


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "-f":
        filename = sys.argv[2]

        with open(filename, "r") as input_file:
            input_json = input_file.read()

        start_time = time()
        optimizer_input = json.loads(input_json)
        print("Input:", optimizer_input)

        hosts, tenants, workers = optimizer_input[0:3]
        output = run_from_json(hosts, tenants, workers)

        time_taken = time() - start_time
        print(f"{time_taken * 1000:.2f} ms")

        with open(filename + "_nodal_opt_output", "w") as output_file:
            output_file.write(dumps(output))
    elif len(sys.argv) > 1:
        print("Invalid argument, use -f <filename> to run sample json")
    else:
        print("No argument provided, use -f <filename> to run sample json")
