import sys
import os
import time
from threading import Thread
from queue import Queue


def get_gateway_ip():
    """
    get gateway ip from this command
    GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath="{.spec.clusterIP}")
    """
    cmd = "kubectl get svc istio-ingressgateway -n istio-system -o jsonpath=\"{.spec.clusterIP}\""
    ip = os.popen(cmd).read().strip()
    return ip

IP = get_gateway_ip()

def run_wrk(q, variation, app_num, rps):
    
    c, t = (1, 1) if rps <= 25 else (5, 5)
    cmd = f"../wrk2/wrk -H \"Host: app{app_num}.mplb.com\" -t {t} -c {c} -d 60 -L \"http://{IP}/?loopCount=25&base=6&exp=6\" -R{rps} > logs/{variation}_app{app_num}_{rps}rps_wrk.log"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put((f"app{app_num}", start_time, end_time, 
           f"wrk for app{app_num} finished with exit status: {exit_status}"))

def run_cc(q, variation, enforcement):
    
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = f"../centralcontroller/centralcontroller -logfile {curr_dir}/logs/{variation}_cc.log -enforcement={enforcement} -d={70_000}"
    print(f"Command: {cmd}")
    
    start_time = time.time()
    exit_status = os.system(cmd)
    end_time = time.time()
    
    q.put(("cc", start_time, end_time, 
           f"CC finished with exit status: {exit_status}"))

def run_exp(variation, rpses, enforcement):
      
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    print(f"Running experiment with {variation} at {rpses} RPS")

    # run the wrk command in a separate thread
    qeues = []
    for i, rps in enumerate(rpses):
        if i+1 > 1:
            continue
        q = Queue()
        Thread(target=run_wrk, args=(q, variation, i+1, rps)).start()
        qeues.append(q)
        
    q = Queue()
    Thread(target=run_cc, args=(q, variation, enforcement)).start()
    qeues.append(q)
    
    times = []
    
    # wait for the wrk commands to finish
    for q in qeues:
        thread_name, start_time, end_time, finish_status = q.get()
        times.append((thread_name, start_time, end_time))
        print(finish_status)
        
    # print the times to file "logs/{variation}.times"
    with open(f"logs/{variation}.times", "w") as f:
        for thread_name, start_time, end_time in times:
            f.write(f"{thread_name} {start_time} {end_time}\n")
    
    print(f"Completed experiment with {variation} at {rpses} RPS")
    print(f"|||||||||||||||||||||||||||||||||||||||||||||||||||||")
    
    print("Sleeping for 5 seconds...")
    time.sleep(5)

def run():
    
    # change dir to previous directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../centralcontroller")
    os.system("go build .")
    os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/../exp_3_node")
    
    rpses = [75, 50, 25]
    
    run_exp(f"rr_{0}", rpses, "NONE")
    
    # for run in range(1, 5):
    #     run_exp(f"lr_{run}", rpses, "NONE")
    #     run_exp(f"mplb_{run}", rpses, "LB")

if __name__ == '__main__':
    # Run the experiment
    run()
