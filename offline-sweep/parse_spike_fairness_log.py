import json
import sys
import numpy as np
import matplotlib.pyplot as plt

LOGFILE = "logs/offline_sweep_spike_fairness_Apr26_lb_0.50_ub_0.50_topo_sampling_2.log"


def allocated(result_dict: dict) -> float:
    return sum(result_dict.values())


def _draw_cdf_axes(ax, series, xlabel, title):
    for diffs, label, color in series:
        if not diffs:
            continue
        d = np.sort(diffs)
        cdf = np.arange(1, len(d) + 1) / len(d)
        ax.plot(d, cdf, label=label, color=color)
    ax.axvline(0, color="grey", linestyle="--", linewidth=1.2, label="Global (0)")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("CDF")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)


def plot_cdf(local_diffs, nodal_diffs, local_pct_diffs, nodal_pct_diffs, outfile=None):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    series = [
        (local_diffs, "Local − Global", "tab:blue"),
        (nodal_diffs, "Nodal − Global",  "tab:orange"),
    ]
    _draw_cdf_axes(ax1, series,
                   xlabel="Allocated load difference from Global",
                   title="CDF of load difference from Global")

    pct_series = [
        (local_pct_diffs, "Local − Global", "tab:blue"),
        (nodal_pct_diffs, "Nodal − Global",  "tab:orange"),
    ]
    _draw_cdf_axes(ax2, pct_series,
                   xlabel="Allocated load % difference from Global",
                   title="CDF of % load difference from Global")

    plt.tight_layout()

    if outfile:
        plt.savefig(outfile)
        print(f"Plot saved to {outfile}")
    else:
        plt.show()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("logfile", nargs="?", default=LOGFILE)
    parser.add_argument("outfile", nargs="?", default=None)
    parser.add_argument("--start", type=int, default=1, metavar="N", help="First state to include (1-indexed)")
    parser.add_argument("--end",   type=int, default=None, metavar="N", help="Last state to include (1-indexed, inclusive)")
    args = parser.parse_args()

    logfile   = args.logfile
    start_idx = args.start - 1          # convert to 0-indexed
    end_idx   = args.end                # None means no upper bound

    local_diffs     = []
    nodal_diffs     = []
    local_pct_diffs = []
    nodal_pct_diffs = []

    with open(logfile) as f:
        for idx, line in enumerate(f):
            if idx < start_idx:
                continue
            if end_idx is not None and idx >= end_idx:
                break
            entry = json.loads(line)

            selected = entry["SelectedServices"]
            tenants  = entry["Tenants"]
            s_local  = entry["SpikeResultsLocal"]
            s_global = entry["SpikeResultsGlobal"]
            s_nodal  = entry.get("SpikeResultsNodal", {})

            base_loads = {t["name"]: float(t["load"]) for t in tenants}

            print(f"\n=== State {idx + 1} | Selected: {selected} ===")

            local_sel_total  = 0.0
            global_sel_total = 0.0
            nodal_sel_total  = 0.0

            for svc in selected:
                local_alloc  = allocated(s_local[svc]["result"])
                global_alloc = allocated(s_global[svc]["result"])
                nodal_alloc  = allocated(s_nodal[svc]["result"]) if svc in s_nodal else float("nan")
                base         = s_local[svc]["base"]
                spiked       = s_local[svc]["spiked_load"]
                n_nodes      = s_local[svc]["n_nodes"]

                local_sel_total  += local_alloc
                global_sel_total += global_alloc
                if svc in s_nodal:
                    nodal_sel_total += nodal_alloc

                local_diffs.append(local_alloc - global_alloc)
                if global_alloc != 0:
                    local_pct_diffs.append((local_alloc - global_alloc) / global_alloc * 100)
                if svc in s_nodal:
                    nodal_diffs.append(nodal_alloc - global_alloc)
                    if global_alloc != 0:
                        nodal_pct_diffs.append((nodal_alloc - global_alloc) / global_alloc * 100)

                print(f"  {svc}: base={base:.1f}  spiked={spiked:.1f}  ({n_nodes} nodes)")
                print(f"    Local  allocated: {local_alloc:7.2f}  feasible={s_local[svc]['feasible']}")
                print(f"    Global allocated: {global_alloc:7.2f}  feasible={s_global[svc]['feasible']}")
                if svc in s_nodal:
                    print(f"    Nodal  allocated: {nodal_alloc:7.2f}  feasible={s_nodal[svc]['feasible']}")

            non_sel_base = sum(v for k, v in base_loads.items() if k not in selected)
            local_cluster_total  = local_sel_total  + non_sel_base
            global_cluster_total = global_sel_total + non_sel_base
            nodal_cluster_total  = nodal_sel_total  + non_sel_base

            print(f"\n  Sum allocated (selected services) — Local: {local_sel_total:.2f}  Global: {global_sel_total:.2f}  Nodal: {nodal_sel_total:.2f}")
            print(f"  Sum utilization (entire cluster)  — Local: {local_cluster_total:.2f}  Global: {global_cluster_total:.2f}  Nodal: {nodal_cluster_total:.2f}")

    print(f"\nCollected {len(local_diffs)} local diffs, {len(nodal_diffs)} nodal diffs across all selected services.")
    outfile = args.outfile or logfile.replace(".log", "_cdf.png")
    plot_cdf(local_diffs, nodal_diffs, local_pct_diffs, nodal_pct_diffs, outfile=outfile)


if __name__ == "__main__":
    main()
