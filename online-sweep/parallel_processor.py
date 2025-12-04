from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd
import json
import multiprocessing as mp

def process_single_run_iteration(params):
    """Process a single (run, iteration) combination"""
    from typing import Tuple
    
    # Import required functions - assuming they're available
    run, iteration, lb, distr, process_distribution, scale_factor, log_folder, topologies, \
        get_file_text, get_times, get_podname, get_node, get_hit_data_df = params
    
    cpu_data = []
    rps_data = []
    error = None
    
    try:
        cc_file = f"{log_folder}/{distr}_{process_distribution}_{lb}_{run}_{iteration}_{scale_factor}_cc.log"
        
        cc_text, err_str = get_file_text(cc_file)
        if err_str != "":
            return None, None, None, (lb, run, iteration, scale_factor, err_str)
        
        cc_text = cc_text.strip().split("\n")
        is_first_req_stat = True
        
        start_time, stop_time, topology = get_times(topologies, distr, process_distribution, lb, run, iteration, scale_factor)
        
        for line in cc_text:
            # if the line is a requests log
            if line[:8] == "ReqStats":
                if is_first_req_stat:
                    is_first_req_stat = False
                    continue
                
                line_data = json.loads(line[10:])
                
                for req in line_data:
                    app = req["dstSvc"].split(".")[0]
                    start_time_s = float(req["startTimeMs"])/10**3
                    end_time_s = float(req["endTimeMs"])/10**3
                    to_append = {
                        "SrcPod": get_podname(req["srcPod"], topology),
                        "SrcSvc": req["srcSvc"],
                        "DstPod": get_podname(req["dstPod"], topology),
                        "DstSvc": req["dstSvc"],
                        "DstSvcNum": int(app[3:])+1,
                        "StartTime": start_time_s,
                        "EndTime": end_time_s,
                        "Latency": end_time_s - start_time_s,
                        "LatencyMs": (end_time_s - start_time_s) * 1000,
                        "LB": lb,
                        "Distribution": distr,
                        "Run": run,
                        "ScaleFactor": scale_factor,
                        "Iteration": iteration,
                        "Node": get_node(req["dstPod"], topology),
                        "ProcessDistribution": process_distribution
                    }
                    rps_data.append(to_append)
            
            # if the line is a cpu utilization log
            else:
                try:
                    line_data = json.loads(line)
                except Exception as e:
                    continue
                
                for podname, cpu_util in line_data["CPUUtilizations"].items():
                    if podname == "utils":
                        continue
                    svc = "-".join(podname.split("-")[:-1])
                    appNum = int(svc[3:]) if svc.startswith("svc") else -1
                    try:
                        if "LBWeights" in line_data:
                            to_append = {
                                "Svc": svc,
                                "AppNum": appNum,
                                "Pod": get_podname(podname, topology),
                                "Time": float(line_data["time"])/10**9,
                                "CPUUtil": float(cpu_util),
                                "LB": lb,
                                "Distribution": distr,
                                "LBWeight": line_data["LBWeights"][svc][podname] if "mplb" in lb and "hostagent" not in podname else 0,
                                "CPUConsumptionPerReq": 0.0,
                                "CPUAllocated": 0.0,
                                "PerfBasedRPSAllowed": 0.0,
                                "MaxRPSAllowed": 0,
                                "Run": run,
                                "ScaleFactor": scale_factor,
                                "Iteration": iteration,
                                "Node": get_node(podname, topology),
                                "ProcessDistribution": process_distribution
                            }
                        else:
                            maxAllowedRPS = 0
                            if "mplb" in lb and "hostagent" not in podname:
                                cpu_consumption_per_req = float(line_data["LBStats"][svc]["CPUConsumptionPerReq"])
                                if cpu_consumption_per_req > 0:
                                    maxAllowedRPS = int(float(line_data["LBStats"][svc]["CPUAllocated"]) / cpu_consumption_per_req)
                            
                            appNum = int(svc[3:]) if svc.startswith("svc") else -1
                            to_append = {
                                "Svc": svc,
                                "AppNum": appNum,
                                "Pod": get_podname(podname, topology),
                                "Time": float(line_data["time"])/10**9,
                                "CPUUtil": float(cpu_util),
                                "LB": lb,
                                "Distribution": distr,
                                "LBWeight": line_data["LBStats"][svc]["Weights"][podname] if "mplb" in lb and "hostagent" not in podname else 0,
                                "CPUConsumptionPerReq": float(line_data["LBStats"][svc]["CPUConsumptionPerReq"]) if "mplb" in lb and "hostagent" not in podname else 0,
                                "CPUAllocated": float(line_data["LBStats"][svc]["CPUAllocated"]) if "mplb" in lb and "hostagent" not in podname else 0,
                                "PerfBasedRPSAllowed": float(line_data["LBStats"][svc]["PerfBasedRPSAllowed"]) if "mplb" in lb and "hostagent" not in podname else 0,
                                "MaxRPSAllowed": maxAllowedRPS,
                                "Run": run,
                                "ScaleFactor": scale_factor,
                                "Iteration": iteration,
                                "Node": get_node(podname, topology),
                                "ProcessDistribution": process_distribution
                            }
                    except Exception as e:
                        print(f"Error in CPU Utilization log: {e}")
                        raise
                    cpu_data.append(to_append)
        
        # Process dataframes
        tmp_req_df = pd.DataFrame(rps_data)
        tmp_req_df["in_experiment"] = (tmp_req_df["StartTime"] >= start_time) & (tmp_req_df["StartTime"] <= stop_time)
        tmp_req_df["StartTime"] = tmp_req_df["StartTime"] - start_time
        tmp_req_df["EndTime"] = tmp_req_df["EndTime"] - start_time
        
        tmp_cpu_df = pd.DataFrame(cpu_data)
        tmp_cpu_df["in_experiment"] = (tmp_cpu_df["Time"] >= start_time) & (tmp_cpu_df["Time"] <= stop_time)
        tmp_cpu_df["Time"] = tmp_cpu_df["Time"] - start_time
        
        tmp_hit_df = get_hit_data_df(topology, distr, process_distribution, lb, run, iteration, scale_factor)
        tmp_hit_df["in_experiment"] = (tmp_hit_df["StartTime"] >= start_time) & (tmp_hit_df["StartTime"] <= stop_time)
        tmp_hit_df["StartTime"] = tmp_hit_df["StartTime"] - start_time
        tmp_hit_df["EndTime"] = tmp_hit_df["EndTime"] - start_time
        
        return tmp_req_df, tmp_cpu_df, tmp_hit_df, None
        
    except Exception as e:
        error = (lb, run, iteration, scale_factor, str(e))
        return None, None, None, error


def process_parallel(RUNS, ITERATIONS, log_folder, topologies, 
                     get_file_text, get_times, get_podname, get_node, get_hit_data_df):
    """
    Main function to process data in parallel
    
    Returns: req_df, cpu_df, hit_df, errors
    """
    req_df = pd.DataFrame()
    cpu_df = pd.DataFrame()
    hit_df = pd.DataFrame()
    errors = []
    
    # Prepare all parameter combinations
    tasks = []
    for distr, process_distribution in [("exponential", "exponential")]:
        for scale_factor in [0.9]:
            for lb in ["mplb_nlr", "mplb_lr++_rlpb", "mplb_nlr_rlpb", "mplb_md", "mplb_onlr", "mplb_lr++"]:
                for run in RUNS:
                    for iteration in ITERATIONS:
                        tasks.append((run, iteration, lb, distr, process_distribution, scale_factor, 
                                    log_folder, topologies, get_file_text, get_times, 
                                    get_podname, get_node, get_hit_data_df))
    
    print(f"Total tasks to process: {len(tasks)}")
    
    # Process in parallel
    max_workers = min(mp.cpu_count(), 8)  # Use up to 8 cores
    print(f"Using {max_workers} workers")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {executor.submit(process_single_run_iteration, task): task for task in tasks}
        
        # Collect results as they complete
        completed = 0
        for future in as_completed(futures):
            task = futures[future]
            run, iteration, lb = task[0], task[1], task[2]
            
            try:
                tmp_req_df, tmp_cpu_df, tmp_hit_df, error = future.result()
                
                if error:
                    errors.append(error)
                    print(f"Error in {lb} {run}_{iteration}: {error[-1]}")
                else:
                    req_df = pd.concat([req_df, tmp_req_df], ignore_index=True)
                    cpu_df = pd.concat([cpu_df, tmp_cpu_df], ignore_index=True)
                    hit_df = pd.concat([hit_df, tmp_hit_df], ignore_index=True)
                    
                completed += 1
                if completed % 10 == 0:
                    print(f"Completed {completed}/{len(tasks)} tasks")
                    
            except Exception as e:
                print(f"Exception processing {lb} {run}_{iteration}: {e}")
                errors.append((lb, run, iteration, task[5], str(e)))
    
    print(f"Processing complete! Total errors: {len(errors)}")
    
    return req_df, cpu_df, hit_df, errors
