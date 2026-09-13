#!/usr/bin/env python3
"""Run the Section 6.1-inspired fixed-overload fairness experiment.

The default invocation evaluates every canonical scenario that has at least one
valid co-located co-spiker under the requested ``--co-spikers`` value.
``--smoke`` selects three representative scenarios and one repetition while
exercising the same deployment and measurement path.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import random
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from set_topology import setup_clutser_with_new_pods


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
EXPECTED_TOPOLOGY_SHA256 = "ae7009032474de034fe5305680a63fd429e02f085b17e3df2855f3c1b2b470fd"
DEFAULT_TOPOLOGY_LOG = (
    SCRIPT_DIR
    / "logs"
    / "fixed_overload_inputs"
    / "offline_sweep_spike_Jan4_lb_0.00_ub_1.60_topo_sampling_2.log"
)

CANONICAL_SCENARIOS = [
    (935, "svc10"),
    (124, "svc14"),
    (525, "svc1"),
    (105, "svc9"),
    (170, "svc2"),
    (166, "svc11"),
    (446, "svc6"),
    (279, "svc6"),
    (273, "svc8"),
    (412, "svc10"),
    (214, "svc1"),
    (145, "svc11"),
    (111, "svc3"),
    (775, "svc0"),
    (307, "svc13"),
    (869, "svc1"),
    (878, "svc8"),
    (304, "svc8"),
    (63, "svc6"),
    (464, "svc1"),
    (286, "svc1"),
    (976, "svc7"),
    (811, "svc9"),
    (98, "svc3"),
    (652, "svc4"),
    (9, "svc3"),
    (658, "svc3"),
    (0, "svc1"),
    (610, "svc11"),
    (241, "svc8"),
    (301, "svc9"),
    (176, "svc2"),
    (703, "svc8"),
    (522, "svc7"),
    (960, "svc5"),
    (186, "svc11"),
    (608, "svc3"),
    (9, "svc5"),
    (620, "svc12"),
    (49, "svc6"),
    (314, "svc3"),
    (431, "svc12"),
    (223, "svc7"),
    (673, "svc8"),
    (468, "svc4"),
    (569, "svc3"),
    (911, "svc3"),
    (967, "svc2"),
    (650, "svc0"),
    (749, "svc9"),
]

POLICIES = {
    "rabbit": {"strategy": "nodal_leastrequest", "short": "nlr"},
    "nllb": {"strategy": "nodal_leastrequest_rlpb", "short": "nlr_rlpb"},
    "pslb": {"strategy": "leastrequest_plus_rlpb", "short": "lr++_rlpb"},
}
DEFAULT_POLICIES = ["rabbit", "nllb", "pslb"]
SMOKE_SCENARIO_INDICES = [0, 24, 49]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed-overload, two-spiker fairness experiment."
    )
    parser.add_argument("--topology-log", type=Path, default=DEFAULT_TOPOLOGY_LOG)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--scenario-indices",
        help="Comma-separated zero-based indices into the canonical 50-scenario list.",
    )
    parser.add_argument(
        "--policies",
        default=",".join(DEFAULT_POLICIES),
        help="Comma-separated subset/order of rabbit,nllb,pslb.",
    )
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--co-spikers", type=int, default=1)
    parser.add_argument("--selection-seed", type=int, default=20260911)
    parser.add_argument("--duration-seconds", type=int, default=30)
    parser.add_argument("--analysis-start-seconds", type=int, default=15)
    parser.add_argument("--background-factor", type=float, default=0.5)
    parser.add_argument("--spike-ceiling-multiplier", type=float, default=1.25)
    parser.add_argument("--cores-per-node", type=float, default=8.0)
    parser.add_argument("--request-cpu-ms", type=int, default=80)
    parser.add_argument("--gateway-replicas", type=int, default=4)
    parser.add_argument("--arrival-distribution", default="exponential")
    parser.add_argument("--processing-distribution", default="exponential")
    parser.add_argument("--controller-lead-seconds", type=int, default=5)
    parser.add_argument("--controller-tail-seconds", type=int, default=10)
    parser.add_argument("--policy-settle-seconds", type=int, default=5)
    parser.add_argument("--cooldown-seconds", type=int, default=5)
    parser.add_argument(
        "--image-repository", default="ghcr.io/talha-waheed/mplb-plugin"
    )
    parser.add_argument(
        "--image-tag-suffix",
        help="Defaults to lb4-<12-character Git commit>.",
    )
    parser.add_argument(
        "--objective-url", default="http://localhost:4876/simplify_objective"
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-topology-setup", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def command_output(command: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(command, cwd=cwd, text=True).strip()


def run_command(
    command: Sequence[str],
    cwd: Path | None = None,
    stdout: Any = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    print("Command:", " ".join(str(part) for part in command), flush=True)
    return subprocess.run(
        command,
        cwd=cwd,
        stdout=stdout,
        stderr=subprocess.STDOUT if stdout is not None else None,
        text=True,
        timeout=timeout,
        check=True,
    )


def parse_csv(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_scenario_indices(value: str | None, smoke: bool) -> List[int]:
    if smoke and value:
        raise ValueError("--smoke and --scenario-indices cannot be combined")
    if smoke:
        return list(SMOKE_SCENARIO_INDICES)
    if value is None:
        return list(range(len(CANONICAL_SCENARIOS)))
    indices = [int(part) for part in parse_csv(value)]
    if not indices:
        raise ValueError("--scenario-indices selected no scenarios")
    if len(indices) != len(set(indices)):
        raise ValueError("--scenario-indices contains duplicates")
    invalid = [index for index in indices if not 0 <= index < len(CANONICAL_SCENARIOS)]
    if invalid:
        raise ValueError(f"scenario indices out of range: {invalid}")
    return indices


def read_topology_records(path: Path) -> Dict[int, Dict[str, Any]]:
    wanted = {state_id for state_id, _ in CANONICAL_SCENARIOS}
    records: Dict[int, Dict[str, Any]] = {}
    with path.open() as source:
        for line_number, line in enumerate(source):
            if line_number in wanted:
                records[line_number] = json.loads(line)
    missing = sorted(wanted - records.keys())
    if missing:
        raise ValueError(f"topology log is missing state IDs: {missing}")
    return records


def service_number(name: str) -> int:
    match = re.fullmatch(r"svc(\d+)", name)
    if not match:
        raise ValueError(f"invalid service name: {name}")
    return int(match.group(1))


def build_scenario_manifest(args: argparse.Namespace) -> Dict[str, Any]:
    topology_log = args.topology_log.resolve()
    if not topology_log.is_file():
        raise FileNotFoundError(f"topology log not found: {topology_log}")
    topology_sha256 = sha256_file(topology_log)
    if topology_sha256 != EXPECTED_TOPOLOGY_SHA256:
        raise ValueError(
            f"topology log SHA-256 is {topology_sha256}, expected "
            f"{EXPECTED_TOPOLOGY_SHA256}"
        )

    records = read_topology_records(topology_log)
    selector = random.Random(args.selection_seed)
    scenarios = []

    for scenario_index, (state_id, primary) in enumerate(CANONICAL_SCENARIOS):
        record = records[state_id]
        state = record["State"]
        nodes_to_svc = state["NodesToSvc"]
        num_services = int(state["NumOfSvc"])
        if num_services != 15:
            raise ValueError(f"state {state_id} has {num_services} services, expected 15")
        if service_number(primary) >= num_services:
            raise ValueError(f"state {state_id} does not contain {primary}")

        svc_to_nodes: Dict[str, List[str]] = {
            f"svc{svc_id}": [] for svc_id in range(num_services)
        }
        fair_share_cores = {f"svc{svc_id}": 0.0 for svc_id in range(num_services)}
        for node_id, counts in enumerate(nodes_to_svc):
            workers_on_node = sum(int(count) for count in counts)
            if workers_on_node == 0:
                continue
            if workers_on_node < 0:
                raise ValueError(f"state {state_id} node{node_id} has negative workers")
            for svc_id, raw_count in enumerate(counts):
                count = int(raw_count)
                service = f"svc{svc_id}"
                svc_to_nodes[service].extend([f"node{node_id}"] * count)
                fair_share_cores[service] += (
                    count * args.cores_per_node / workers_on_node
                )

        primary_nodes = set(svc_to_nodes[primary])
        candidates = sorted(
            (
                service
                for service, nodes in svc_to_nodes.items()
                if service != primary and primary_nodes.intersection(nodes)
            ),
            key=service_number,
        )
        permutation = list(candidates)
        selector.shuffle(permutation)
        eligible = len(permutation) >= args.co_spikers
        additional_spikers = permutation[: args.co_spikers] if eligible else []
        spikers = [primary, *additional_spikers]
        spiker_nodes = set().union(*(set(svc_to_nodes[svc]) for svc in spikers))
        services: Dict[str, Dict[str, Any]] = {}
        for svc_id in range(num_services):
            service = f"svc{svc_id}"
            unique_nodes = sorted(set(svc_to_nodes[service]))
            isolated_ceiling_cores = args.cores_per_node * len(unique_nodes)
            is_spiker = service in spikers
            offered_cpu_cores = (
                args.spike_ceiling_multiplier * isolated_ceiling_cores
                if is_spiker
                else args.background_factor * fair_share_cores[service]
            )
            offered_rps = offered_cpu_cores * 1000.0 / args.request_cpu_ms
            role = "nonspiker"
            if service == primary:
                role = "primary_spiker"
            elif service in additional_spikers:
                role = "additional_spiker"
            elif set(unique_nodes).intersection(spiker_nodes):
                role = "exposed_nonspiker"
            services[service] = {
                "role": role,
                "nodes_with_multiplicity": svc_to_nodes[service],
                "unique_nodes": unique_nodes,
                "fair_share_cores": fair_share_cores[service],
                "isolated_ceiling_cores": isolated_ceiling_cores,
                "offered_cpu_cores": offered_cpu_cores,
                "offered_rps": offered_rps,
                "request_interval_ms": 1000.0 / offered_rps,
            }

        worker_names = [worker["name"] for worker in record["Workers"]]
        expected_workers = sum(sum(int(value) for value in row) for row in nodes_to_svc)
        if len(worker_names) != expected_workers:
            raise ValueError(
                f"state {state_id} has {len(worker_names)} workers, expected {expected_workers}"
            )

        shared_nodes = {
            candidate: sorted(primary_nodes.intersection(svc_to_nodes[candidate]))
            for candidate in permutation
        }
        scenarios.append(
            {
                "scenario_index": scenario_index,
                "state_id": state_id,
                "primary_spiker": primary,
                "additional_spikers": additional_spikers,
                "spikers": spikers,
                "eligible_co_spikers": candidates,
                "co_spiker_permutation": permutation,
                "eligible_for_requested_x": eligible,
                "ineligibility_reason": (
                    None
                    if eligible
                    else f"only {len(permutation)} co-located services for x={args.co_spikers}"
                ),
                "shared_nodes_with_primary": shared_nodes,
                "services": services,
                "pod_names": worker_names,
                "intended_topology": svc_to_nodes,
            }
        )

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topology_log": str(topology_log),
        "topology_sha256": topology_sha256,
        "selection_seed": args.selection_seed,
        "co_spikers": args.co_spikers,
        "cores_per_node": args.cores_per_node,
        "background_factor": args.background_factor,
        "spike_ceiling_multiplier": args.spike_ceiling_multiplier,
        "request_cpu_ms": args.request_cpu_ms,
        "scenarios": scenarios,
    }


def build_run_plan(
    scenarios: Sequence[Dict[str, Any]],
    scenario_indices: Sequence[int],
    policies: Sequence[str],
    repetitions: int,
    selection_seed: int,
) -> List[Dict[str, Any]]:
    selected = {scenario["scenario_index"]: scenario for scenario in scenarios}
    plan = []
    for selected_position, scenario_index in enumerate(scenario_indices):
        scenario = selected[scenario_index]
        for repetition in range(1, repetitions + 1):
            shift = (selected_position + repetition - 1) % len(policies)
            policy_order = [*policies[shift:], *policies[:shift]]
            run_seed = selection_seed + scenario_index * 1000 + repetition
            for policy_position, policy in enumerate(policy_order):
                co_label = "-".join(scenario["additional_spikers"])
                run_id = (
                    f"s{scenario_index:02d}_state{scenario['state_id']}_"
                    f"primary-{scenario['primary_spiker']}_co-{co_label}_"
                    f"rep{repetition}_{policy}"
                )
                plan.append(
                    {
                        "run_id": run_id,
                        "scenario_index": scenario_index,
                        "state_id": scenario["state_id"],
                        "primary_spiker": scenario["primary_spiker"],
                        "additional_spikers": scenario["additional_spikers"],
                        "policy": policy,
                        "strategy": POLICIES[policy]["strategy"],
                        "policy_position": policy_position,
                        "repetition": repetition,
                        "random_seed": run_seed,
                    }
                )
    return plan


def kubectl_json(arguments: Sequence[str]) -> Dict[str, Any]:
    raw = command_output(["kubectl", *arguments])
    return json.loads(raw)


def is_ready(pod: Dict[str, Any]) -> bool:
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )


def gateway_snapshot(num_services: int, replicas: int) -> Dict[str, Any]:
    node_data = kubectl_json(["get", "nodes", "-l", "mplb/lb-node", "-o", "json"])
    lb_nodes = sorted(item["metadata"]["name"] for item in node_data["items"])
    if len(lb_nodes) != replicas:
        raise RuntimeError(
            f"found {len(lb_nodes)} LB nodes, expected {replicas}: {lb_nodes}"
        )

    pod_data = kubectl_json(["get", "pods", "-n", "istio-ingress", "-o", "json"])
    services: Dict[str, Any] = {}
    for svc_id in range(num_services):
        service = f"svc{svc_id}"
        expected_label = f"ingressgateway-{service}"
        pods = [
            pod
            for pod in pod_data["items"]
            if pod.get("metadata", {}).get("labels", {}).get("istio") == expected_label
            and not pod.get("metadata", {}).get("deletionTimestamp")
        ]
        if len(pods) != replicas:
            raise RuntimeError(
                f"{service} has {len(pods)} gateway pods, expected {replicas}"
            )
        if not all(is_ready(pod) for pod in pods):
            not_ready = [pod["metadata"]["name"] for pod in pods if not is_ready(pod)]
            raise RuntimeError(f"{service} has unready gateway pods: {not_ready}")
        pod_nodes = sorted(pod["spec"]["nodeName"] for pod in pods)
        if pod_nodes != lb_nodes:
            raise RuntimeError(
                f"{service} gateway nodes are {pod_nodes}, expected {lb_nodes}"
            )
        ordered = sorted(pods, key=lambda pod: pod["spec"]["nodeName"])
        services[service] = {
            "pods": [
                {
                    "name": pod["metadata"]["name"],
                    "node": pod["spec"]["nodeName"],
                    "ip": pod["status"]["podIP"],
                }
                for pod in ordered
            ],
            "endpoints": [f"{pod['status']['podIP']}:8080" for pod in ordered],
        }
    return {"lb_nodes": lb_nodes, "services": services}


def workload_snapshot(scenario: Dict[str, Any]) -> Dict[str, Any]:
    pod_data = kubectl_json(["get", "pods", "-n", "default", "-o", "json"])
    actual_by_service: Dict[str, List[str]] = defaultdict(list)
    pods = {}
    unready = []
    for pod in pod_data["items"]:
        service = pod.get("metadata", {}).get("labels", {}).get("app", "")
        if not re.fullmatch(r"svc\d+", service):
            continue
        if pod.get("metadata", {}).get("deletionTimestamp"):
            continue
        pod_name = pod["metadata"]["name"]
        node_name = pod.get("spec", {}).get("nodeName")
        short_node_name = node_name.split(".", 1)[0] if node_name else node_name
        if not is_ready(pod):
            unready.append(pod_name)
        actual_by_service[service].append(short_node_name)
        pods[pod_name] = {
            "service": service,
            "node": node_name,
            "short_node": short_node_name,
        }
    if unready:
        raise RuntimeError(f"workload pods are not ready: {sorted(unready)}")

    expected_by_service = {
        service: sorted(f"node{int(node[4:]) + 1}" for node in logical_nodes)
        for service, logical_nodes in scenario["intended_topology"].items()
    }
    actual_sorted = {
        service: sorted(nodes) for service, nodes in actual_by_service.items()
    }
    if actual_sorted != expected_by_service:
        raise RuntimeError(
            "workload topology mismatch: "
            + json.dumps(
                {"actual": actual_sorted, "expected": expected_by_service},
                sort_keys=True,
            )
        )
    return {
        "pods": pods,
        "by_service": actual_sorted,
        "expected_by_service": expected_by_service,
    }


def render_policy_manifest(
    strategy: str,
    image_repository: str,
    tag_suffix: str,
    destination: Path,
) -> str:
    source = (REPO_ROOT / "mplb-wasm-plugin" / "wasm.yaml").read_text()
    image = f"{image_repository}:{strategy}-{tag_suffix}"
    rendered, substitutions = re.subn(
        rf"oci://{re.escape(image_repository)}:[A-Za-z0-9_.-]+",
        f"oci://{image}",
        source,
    )
    if substitutions == 0:
        raise ValueError(f"no {image_repository} image references found in wasm.yaml")
    destination.write_text(rendered)
    return image


def validate_wasm_policy(image: str) -> None:
    data = kubectl_json(["get", "wasmplugins.extensions.istio.io", "-A", "-o", "json"])
    relevant = [
        item
        for item in data["items"]
        if item["metadata"]["name"].startswith("mplb-wasm-plugin")
    ]
    if len(relevant) < 15:
        raise RuntimeError(f"found only {len(relevant)} MPLB WasmPlugin resources")
    expected_url = f"oci://{image}"
    wrong = [
        f"{item['metadata']['namespace']}/{item['metadata']['name']}="
        f"{item.get('spec', {}).get('url')}"
        for item in relevant
        if item.get("spec", {}).get("url") != expected_url
    ]
    if wrong:
        raise RuntimeError("WasmPlugin image mismatch: " + "; ".join(wrong))


def reset_policy(
    run_dir: Path,
    strategy: str,
    image_repository: str,
    tag_suffix: str,
    settle_seconds: int,
) -> str:
    manifest_path = run_dir / "wasm_policy.yaml"
    image = render_policy_manifest(
        strategy, image_repository, tag_suffix, manifest_path
    )
    run_command(
        [
            "kubectl",
            "delete",
            "-f",
            str(manifest_path),
            "--ignore-not-found=true",
            "--wait=true",
        ],
        cwd=REPO_ROOT,
    )
    run_command(["kubectl", "apply", "-f", str(manifest_path)], cwd=REPO_ROOT)
    time.sleep(settle_seconds)
    validate_wasm_policy(image)
    return image


def set_optimizer_objective(url: str) -> None:
    with urllib.request.urlopen(url, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"optimizer objective endpoint returned {response.status}")
        response.read()


def build_binaries(output_dir: Path) -> Dict[str, Any]:
    binary_dir = output_dir / "bin"
    binary_dir.mkdir(exist_ok=True)
    binaries = {
        "centralcontroller": binary_dir / "centralcontroller",
        "hit": binary_dir / "hit",
    }
    run_command(
        ["go", "build", "-o", str(binaries["centralcontroller"]), "."],
        cwd=REPO_ROOT / "centralcontroller",
    )
    run_command(
        ["go", "build", "-o", str(binaries["hit"]), "."],
        cwd=REPO_ROOT / "hit",
    )
    return {
        name: {"path": str(path), "sha256": sha256_file(path)}
        for name, path in binaries.items()
    }


def make_hit_config(
    scenario: Dict[str, Any],
    gateways: Dict[str, Any],
    run_dir: Path,
    duration_seconds: int,
    processing_distribution: str,
    request_cpu_ms: int,
) -> List[Dict[str, Any]]:
    configs = []
    for service in sorted(scenario["services"], key=service_number):
        details = scenario["services"][service]
        cpu_value = (
            str(request_cpu_ms)
            if processing_distribution in {"none", "uniform"}
            else f"EXP<{request_cpu_ms}>"
        )
        endpoints = [
            {
                "url": f"http://{endpoint}/?cpu_coreMs={cpu_value}",
                "node": 1,
                "app": service_number(service),
                "headers": json.dumps({"Host": f"{service}.mplb.com"}),
            }
            for endpoint in gateways["services"][service]["endpoints"]
        ]
        configs.append(
            {
                "endpoints": endpoints,
                "reqIntervalMs": details["request_interval_ms"],
                "durationMs": duration_seconds * 1000,
                "logFileName": str(run_dir / f"{service}_hit.log"),
                "stallTimeMs": 0,
                "requestIntervalUpdates": [],
            }
        )
    return configs


def run_one_experiment(
    args: argparse.Namespace,
    output_dir: Path,
    binaries: Dict[str, Any],
    scenario: Dict[str, Any],
    run_spec: Dict[str, Any],
    tag_suffix: str,
) -> Dict[str, Any]:
    run_dir = output_dir / "runs" / run_spec["run_id"]
    success_path = run_dir / "SUCCESS.json"
    if success_path.exists() and args.resume:
        print(f"Skipping completed run {run_spec['run_id']}")
        return json.loads(success_path.read_text())
    if run_dir.exists():
        raise FileExistsError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    started_at = time.time()
    image = reset_policy(
        run_dir,
        run_spec["strategy"],
        args.image_repository,
        tag_suffix,
        args.policy_settle_seconds,
    )
    gateways = gateway_snapshot(len(scenario["services"]), args.gateway_replicas)
    set_optimizer_objective(args.objective_url)

    hit_config = make_hit_config(
        scenario,
        gateways,
        run_dir,
        args.duration_seconds,
        args.processing_distribution,
        args.request_cpu_ms,
    )
    hit_config_path = run_dir / "hit.json"
    write_json(hit_config_path, hit_config)

    topology_record = workload_snapshot(scenario)
    topology_record["intended_logical"] = scenario["intended_topology"]
    metadata = {
        **run_spec,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "image": image,
        "duration_seconds": args.duration_seconds,
        "analysis_start_seconds": args.analysis_start_seconds,
        "arrival_distribution": args.arrival_distribution,
        "processing_distribution": args.processing_distribution,
        "gateway_snapshot": gateways,
        "topology": topology_record,
        "services": scenario["services"],
        "hit_config": str(hit_config_path),
    }
    write_json(run_dir / "metadata.json", metadata)

    controller_duration_ms = (
        args.duration_seconds
        + args.controller_lead_seconds
        + args.controller_tail_seconds
    ) * 1000
    controller_log = run_dir / "centralcontroller.log"
    controller_stdout = run_dir / "centralcontroller.stdout.log"
    hit_stdout = run_dir / "hit.stdout.log"
    controller_command = [
        binaries["centralcontroller"]["path"],
        "-logfile",
        str(controller_log),
        "-enforcement=LB",
        f"-d={controller_duration_ms}",
    ]
    hit_command = [
        binaries["hit"]["path"],
        "-distr",
        args.arrival_distribution,
        "-seed",
        str(run_spec["random_seed"]),
        "-f",
        str(hit_config_path),
    ]

    controller_started = time.time()
    controller_process: subprocess.Popen[str] | None = None
    hit_started = 0.0
    hit_ended = 0.0
    controller_ended = 0.0
    try:
        with controller_stdout.open("w") as controller_output:
            print("Command:", " ".join(controller_command), flush=True)
            controller_process = subprocess.Popen(
                controller_command,
                cwd=SCRIPT_DIR,
                stdout=controller_output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            time.sleep(args.controller_lead_seconds)
            hit_started = time.time()
            with hit_stdout.open("w") as hit_output:
                run_command(
                    hit_command,
                    cwd=SCRIPT_DIR,
                    stdout=hit_output,
                    timeout=args.duration_seconds + 90,
                )
            hit_ended = time.time()
            controller_process.wait(timeout=args.controller_tail_seconds + 30)
            controller_ended = time.time()
            if controller_process.returncode != 0:
                raise RuntimeError(
                    f"central controller exited with {controller_process.returncode}"
                )
    finally:
        if controller_process is not None and controller_process.poll() is None:
            controller_process.terminate()
            try:
                controller_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                controller_process.kill()
                controller_process.wait(timeout=5)

    missing_logs = []
    log_sizes = {}
    for service in scenario["services"]:
        log_path = run_dir / f"{service}_hit.log"
        if not log_path.is_file() or log_path.stat().st_size == 0:
            missing_logs.append(service)
        else:
            log_sizes[service] = log_path.stat().st_size
    if missing_logs:
        raise RuntimeError(f"missing or empty hit logs: {missing_logs}")

    times_path = run_dir / "run.times"
    with times_path.open("w") as times_file:
        times_file.write(json.dumps(topology_record, sort_keys=True) + "\n")
        times_file.write(f"centralcontroller {controller_started} {controller_ended}\n")
        times_file.write(f"hit {hit_started} {hit_ended}\n")

    result = {
        **metadata,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.time() - started_at,
        "hit_log_sizes": log_sizes,
        "status": "success",
    }
    write_json(success_path, result)
    return result


def prepare_output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir:
        output_dir = args.output_dir.resolve()
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = SCRIPT_DIR / "logs" / f"fixed_overload_fairness_{timestamp}"
    if output_dir.exists() and not args.resume:
        raise FileExistsError(
            f"output directory exists; choose another or pass --resume: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=args.resume)
    return output_dir


def main() -> int:
    args = parse_args()
    if args.repetitions is None:
        args.repetitions = 1 if args.smoke else 3
    if args.repetitions <= 0:
        raise ValueError("repetitions must be >= 1")
    if args.co_spikers <= 0:
        raise ValueError("co-spikers must be >= 1")
    if not 0 <= args.background_factor <= 1:
        raise ValueError("background-factor must be between 0 and 1")
    if args.spike_ceiling_multiplier <= 1:
        raise ValueError("spike-ceiling-multiplier must be greater than 1")
    if args.cores_per_node <= 0 or args.request_cpu_ms <= 0:
        raise ValueError("cores-per-node and request-cpu-ms must be positive")
    if args.duration_seconds <= args.analysis_start_seconds:
        raise ValueError("duration must be greater than analysis start")
    if args.gateway_replicas != 4:
        raise ValueError("this experiment requires exactly four gateway replicas")

    policies = parse_csv(args.policies)
    if not policies or len(policies) != len(set(policies)):
        raise ValueError("--policies must contain a nonempty set without duplicates")
    unknown_policies = sorted(set(policies) - POLICIES.keys())
    if unknown_policies:
        raise ValueError(f"unknown policies: {unknown_policies}")
    scenario_indices = parse_scenario_indices(args.scenario_indices, args.smoke)

    repo_commit = command_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
    tag_suffix = args.image_tag_suffix or f"lb4-{repo_commit[:12]}"
    output_dir = prepare_output_dir(args)
    scenario_manifest = build_scenario_manifest(args)
    scenarios_by_index = {
        scenario["scenario_index"]: scenario
        for scenario in scenario_manifest["scenarios"]
    }
    excluded_scenarios = [
        {
            "scenario_index": scenario_index,
            "state_id": scenarios_by_index[scenario_index]["state_id"],
            "primary_spiker": scenarios_by_index[scenario_index]["primary_spiker"],
            "reason": scenarios_by_index[scenario_index]["ineligibility_reason"],
        }
        for scenario_index in scenario_indices
        if not scenarios_by_index[scenario_index]["eligible_for_requested_x"]
    ]
    if args.scenario_indices and excluded_scenarios:
        raise ValueError(
            "explicitly selected scenarios are ineligible: "
            + json.dumps(excluded_scenarios, sort_keys=True)
        )
    runnable_scenario_indices = [
        scenario_index
        for scenario_index in scenario_indices
        if scenarios_by_index[scenario_index]["eligible_for_requested_x"]
    ]
    if not runnable_scenario_indices:
        raise ValueError("no selected scenarios have enough co-located co-spikers")
    run_plan = build_run_plan(
        scenario_manifest["scenarios"],
        runnable_scenario_indices,
        policies,
        args.repetitions,
        args.selection_seed,
    )
    write_json(output_dir / "scenario_manifest.json", scenario_manifest)
    write_json(output_dir / "run_plan.json", run_plan)

    experiment_manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_commit": repo_commit,
        "image_repository": args.image_repository,
        "image_tag_suffix": tag_suffix,
        "requested_scenario_indices": scenario_indices,
        "scenario_indices": runnable_scenario_indices,
        "excluded_scenarios": excluded_scenarios,
        "policies": policies,
        "repetitions": args.repetitions,
        "planned_runs": len(run_plan),
        "smoke": args.smoke,
        "duration_seconds": args.duration_seconds,
        "analysis_start_seconds": args.analysis_start_seconds,
        "arrival_distribution": args.arrival_distribution,
        "processing_distribution": args.processing_distribution,
        "gateway_replicas": args.gateway_replicas,
        "topology_sha256": scenario_manifest["topology_sha256"],
    }
    write_json(output_dir / "experiment_manifest.json", experiment_manifest)
    print(
        f"Planned {len(run_plan)} runs across {len(runnable_scenario_indices)} scenarios, "
        f"{len(policies)} policies, and {args.repetitions} repetitions."
    )
    if excluded_scenarios:
        print("Excluded structurally ineligible scenarios:")
        for excluded in excluded_scenarios:
            print(
                f"  index {excluded['scenario_index']} / state {excluded['state_id']} / "
                f"{excluded['primary_spiker']}: {excluded['reason']}"
            )
    print(f"Output directory: {output_dir}")
    if args.dry_run:
        print("Dry run complete; no cluster state was changed.")
        return 0

    binaries = build_binaries(output_dir)
    experiment_manifest["binaries"] = binaries
    experiment_manifest["initial_gateway_snapshot"] = gateway_snapshot(15, 4)
    write_json(output_dir / "experiment_manifest.json", experiment_manifest)

    completed = []
    failures = []
    prepared_scenario_index = None
    for ordinal, run_spec in enumerate(run_plan, start=1):
        scenario = scenarios_by_index[run_spec["scenario_index"]]
        print(
            f"\n=== Run {ordinal}/{len(run_plan)}: {run_spec['run_id']} ===",
            flush=True,
        )
        if prepared_scenario_index != scenario["scenario_index"]:
            if args.skip_topology_setup:
                print("Skipping topology setup as requested.")
            else:
                if not setup_clutser_with_new_pods(scenario["pod_names"]):
                    raise RuntimeError(
                        f"failed to set up topology for scenario {scenario['scenario_index']}"
                    )
            gateway_snapshot(15, 4)
            workload_snapshot(scenario)
            prepared_scenario_index = scenario["scenario_index"]

        try:
            result = run_one_experiment(
                args,
                output_dir,
                binaries,
                scenario,
                run_spec,
                tag_suffix,
            )
            completed.append(result["run_id"])
        except Exception as error:
            failure = {
                "run_id": run_spec["run_id"],
                "time": datetime.now(timezone.utc).isoformat(),
                "error": repr(error),
            }
            failures.append(failure)
            failure_dir = output_dir / "runs" / run_spec["run_id"]
            failure_dir.mkdir(parents=True, exist_ok=True)
            write_json(failure_dir / "FAILED.json", failure)
            print(f"FAILED: {failure}", file=sys.stderr, flush=True)
            if not args.continue_on_error:
                break
        time.sleep(args.cooldown_seconds)

    summary = {
        "completed_runs": completed,
        "failures": failures,
        "planned_runs": len(run_plan),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_dir / "summary.json", summary)
    print(
        f"Completed {len(completed)}/{len(run_plan)} runs with {len(failures)} failures."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
