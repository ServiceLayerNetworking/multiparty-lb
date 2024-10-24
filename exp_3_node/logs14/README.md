Evaluating if app3 still increases latency if cpu2 is used in run 7

run,iteration,description
7,1,baseline run with cpu limits == 2.1 CPUs
7,2,run with cpu limits on nodes 2 and 3 but not on node1. Only 2 cores at CPU 1 available for use
7,3,run with no cpu limits on any node. only 2 cores on nodes 1,2,3 available for use
7,4,repeat iter 3 but with increased rpses=[25 50 75]
7,5,repeat iter 4 but with increased rpses=[30 60 90]
7,6,repeat iter 5 but with increased rpses=[40 80 120]
7,7,repeat iter 6 but with increased rpses=[50 100 150]
9,1,repeat run 7 iter 5 with config of run 9
