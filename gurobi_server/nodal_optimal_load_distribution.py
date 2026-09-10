from collections import defaultdict
from json import dumps
from time import time
from typing import Dict, List, Tuple
import json
import math
import sys

import gurobipy as gp
from gurobipy import GRB


class Host:
    def __init__(self, name: str, cap: float):
        self.name = name
        self.cap = float(cap)
        self.worker_ids: List[int] = []

    def __str__(self):
        return f"{self.name}: cap={self.cap}, n_workers={len(self.worker_ids)}"


class Tenant:
    def __init__(self, name: str, load: float):
        self.name = name
        self.load = float(load)

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


def _validate_inputs(
    hosts: List[Host],
    tenants: List[Tenant],
    workers: List[Worker],
) -> Tuple[Dict[str, Host], Dict[str, Tenant]]:
    host_by_name = {host.name: host for host in hosts}
    tenant_by_name = {tenant.name: tenant for tenant in tenants}

    if len(host_by_name) != len(hosts):
        raise ValueError("Host names must be unique")
    if len(tenant_by_name) != len(tenants):
        raise ValueError("Tenant names must be unique")
    if len({worker.name for worker in workers}) != len(workers):
        raise ValueError("Worker names must be unique")

    for host in hosts:
        if not math.isfinite(host.cap) or host.cap < 0:
            raise ValueError(f"Invalid capacity for host {host.name}: {host.cap}")
    for tenant in tenants:
        if not math.isfinite(tenant.load) or tenant.load < 0:
            raise ValueError(f"Invalid load for tenant {tenant.name}: {tenant.load}")

    tenant_worker_counts = defaultdict(int)
    for worker in workers:
        if worker.host not in host_by_name:
            raise ValueError(f"Worker {worker.name} has unknown host {worker.host}")
        if worker.tenant not in tenant_by_name:
            raise ValueError(
                f"Worker {worker.name} has unknown tenant {worker.tenant}"
            )
        tenant_worker_counts[worker.tenant] += 1

    missing_workers = [
        tenant.name for tenant in tenants if tenant_worker_counts[tenant.name] == 0
    ]
    if missing_workers:
        raise ValueError(f"Tenants without workers: {missing_workers[:5]}")

    return host_by_name, tenant_by_name


def get_nodal_optimal_load_distribution_fast(
    hosts: List[Host],
    tenants: List[Tenant],
    workers: List[Worker],
    queue_tolerance: float = 1e-7,
) -> Dict[str, Dict[str, float]]:
    """Compute a fluid equilibrium for node-level least-outstanding routing.

    Let ``x[t, w]`` be the fraction of tenant ``t`` traffic routed to worker
    ``w`` and let the offered work at host ``h`` be the sum of the corresponding
    tenant loads.  A host's fluid backlog is the positive part of offered work
    minus capacity.  NLLB sends a request to a reachable endpoint whose host has
    the least aggregate outstanding work.  Its steady-state (Wardrop)
    equilibrium therefore minimizes the Beckmann potential

        1/2 * sum_h backlog[h]^2.

    The first convex optimization finds the unique optimal host-backlog vector.
    Routing can be non-unique when multiple endpoints have the same node signal,
    so a second optimization fixes that backlog vector (within numerical
    tolerance) and minimizes the squared routing fractions.  This reproduces
    equal random tie splitting without changing the least-outstanding
    equilibrium.

    Finally, each host applies the same per-worker max-min processor sharing as
    ``get_locally_optimal_load_distribution_fast``.  The returned values are
    processed work per worker, matching the PSLB solver's output schema.
    """

    if queue_tolerance <= 0:
        raise ValueError("queue_tolerance must be positive")

    host_by_name, tenant_by_name = _validate_inputs(hosts, tenants, workers)

    tenant_to_worker_indices = defaultdict(list)
    host_to_worker_indices = defaultdict(list)
    for worker_index, worker in enumerate(workers):
        tenant_to_worker_indices[worker.tenant].append(worker_index)
        host_to_worker_indices[worker.host].append(worker_index)

    model = gp.Model("nodal_least_outstanding_equilibrium")
    model.Params.OutputFlag = 0

    route_fraction = model.addVars(
        len(workers),
        lb=0.0,
        ub=1.0,
        vtype=GRB.CONTINUOUS,
        name="route_fraction",
    )
    backlog = model.addVars(
        [host.name for host in hosts],
        lb=0.0,
        vtype=GRB.CONTINUOUS,
        name="backlog",
    )

    for tenant in tenants:
        model.addConstr(
            gp.quicksum(
                route_fraction[index]
                for index in tenant_to_worker_indices[tenant.name]
            )
            == 1.0,
            name=f"tenant_route_{tenant.name}",
        )

    host_load = {}
    for host in hosts:
        host_load[host.name] = gp.quicksum(
            tenant_by_name[workers[index].tenant].load * route_fraction[index]
            for index in host_to_worker_indices[host.name]
        )
        model.addConstr(
            backlog[host.name] >= host_load[host.name] - host.cap,
            name=f"host_backlog_{host.name}",
        )

    model.setObjective(
        0.5
        * gp.quicksum(
            backlog[host.name] * backlog[host.name] for host in hosts
        ),
        GRB.MINIMIZE,
    )
    model.optimize()

    if model.Status != GRB.OPTIMAL:
        return _empty_result(model.Status, workers)

    # Barrier can leave a tiny positive value in an otherwise-unconstrained
    # zero-backlog auxiliary variable.  Physical backlog is defined by the
    # optimized offered load, so derive it from load minus capacity instead of
    # copying the auxiliary variable's numerical residue.
    optimal_backlog = {
        host.name: max(
            0.0,
            float(host_load[host.name].getValue()) - host.cap,
        )
        for host in hosts
    }

    # Preserve the primary equilibrium while selecting equal endpoint splitting
    # among its otherwise-equivalent routing solutions.
    for host in hosts:
        value = optimal_backlog[host.name]
        allowed_error = queue_tolerance * max(1.0, host.cap, value)
        model.addConstr(
            host_load[host.name] <= host.cap + value + allowed_error,
            name=f"preserve_host_load_upper_{host.name}",
        )
        if value > allowed_error:
            model.addConstr(
                host_load[host.name]
                >= host.cap + value - allowed_error,
                name=f"preserve_host_load_lower_{host.name}",
            )

    model.setObjective(
        gp.quicksum(
            route_fraction[index] * route_fraction[index]
            for index in range(len(workers))
        ),
        GRB.MINIMIZE,
    )
    model.optimize()

    if model.Status != GRB.OPTIMAL:
        return _empty_result(model.Status, workers)

    for worker_index, worker in enumerate(workers):
        tenant_load = tenant_by_name[worker.tenant].load
        worker.load = tenant_load * max(0.0, float(route_fraction[worker_index].X))

    host_to_workers = defaultdict(dict)
    for worker in workers:
        host_to_workers[worker.host][worker.name] = worker

    for host in hosts:
        workers_on_host = host_to_workers[host.name]
        fair_shares = get_max_min_processing_times(
            host.cap,
            {name: worker.load for name, worker in workers_on_host.items()},
        )
        for name, (processed, _completion_time) in fair_shares.items():
            workers_on_host[name].processed = processed

    results = defaultdict(dict)
    for worker in workers:
        results[worker.tenant][worker.name] = worker.processed

    return {
        "status": GRB.OPTIMAL,
        "result": dict(results),
    }


def _empty_result(status: int, workers: List[Worker]):
    results = defaultdict(dict)
    for worker in workers:
        results[worker.tenant][worker.name] = 0.0
    return {
        "status": status,
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
