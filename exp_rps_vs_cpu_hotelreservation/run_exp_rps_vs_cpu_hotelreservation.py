import sys
import os
import time
from threading import Thread
from queue import Queue

IP = sys.argv[1]
SCRIPTS_DIR = "../wrk2/scripts/"

def run_wrk(q, variation, script_file, rps):
    cmd = f"../wrk2/wrk -t 50 -c 100 -d 20 -L -s {SCRIPTS_DIR + script_file} http://{IP} -R{rps} > {variation}{script_file}_{rps}_wrk.log"
    print(f"Command: {cmd}")
    exit_status = os.system(cmd)
    q.put(exit_status)

def run_exp(variation, script_file, rps):
    
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment for {script_file} at {rps} RPS")

    # run the wrk command in a separate thread
    q = Queue()
    Thread(target=run_wrk, args=(q, variation, script_file, rps)).start()
    
    # log CPUs
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../liveCPUStats/liveCPUStats -logfile {curr_dir}/{variation}{script_file}_{rps}_cpu.log"
    print(f"Command: {cmd}")
    os.system(cmd)
    
    # wait for the wrk command to finish
    q.get()
    
    print(f"Completed experiment for {script_file} at {rps} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")

    
def run_exp_rps_vs_cpu_hotelreservation():

    script_files = ["search_hotel.lua", "user_login.lua"]
    
    variation = "no_istio_grpc_maxconc_streams_10000_"
    
    script_file = "user_login.lua"
    
    # run_exp(script_file, 100)
    
    for rps in range(4500, 4600+1, 100):
        run_exp(variation, script_file, rps)
        time.sleep(5)



if __name__ == '__main__':
    # Run the experiment
    run_exp_rps_vs_cpu_hotelreservation()