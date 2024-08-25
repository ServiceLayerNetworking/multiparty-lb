# multiparty-lb


Generated 3-node minikube cluster with the following command (Minikube v1.32.0):
```
minikube start --nodes 4 --cpus 2 --memory 4096 --driver=virtualbox --kubernetes-version=v1.27.0 --feature-gates=InPlacePodVerticalScaling=true
```

Kubernetes Version: 
```
Client Version: v1.28.4
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
Server Version: v1.27.0
```

For Istio installation:
```
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.22.0 TARGET_ARCH=x86_64 sh -
cd istio-1.22.0
export PATH=$PATH:$PWD/bin
echo 'export PATH=$PATH:'$PWD/bin >> ~/.bashrc
istioctl install
```

Start microserviced application (HotelReservation):
```
cd hotelReservation
# sudo usermod -a -G docker twaheed2
# newgrp docker
# bash -x kubernetes/scripts/build-docker-images.sh
kubectl apply -Rf kubernetes/
```
Problem:
```
twaheed2@ocean3:~/go/src/multiparty-lb/hotelReservation$ k get pods
NAME                                      READY   STATUS              RESTARTS      AGE
consul-56f5cf4f78-mn6p7                   1/1     Running             0             33s
frontend-66895d79c-pbk7f                  0/1     RunContainerError   2 (14s ago)   33s
geo-db99d4944-46dvt                       0/1     ContainerCreating   0             32s
jaeger-65f6b96558-56kdk                   1/1     Running             0             32s
memcached-profile-7d6fcb6b8-jjqrt         0/1     ContainerCreating   0             32s
memcached-rate-bcc5c97f8-6rcrx            0/1     ContainerCreating   0             32s
memcached-reserve-bdcb467b4-2fq8l         0/1     ContainerCreating   0             31s
mongodb-geo-7fbbd9c9c5-hj4xq              1/1     Running             0             32s
mongodb-profile-6bb85f4df7-p497m          1/1     Running             0             32s
mongodb-rate-6d6d667b6-psgzf              1/1     Running             0             32s
mongodb-recommendation-59d6b7ccf9-lkqfv   1/1     Running             0             31s
mongodb-reservation-7b474745f-z7l6s       1/1     Running             0             31s
mongodb-user-6d96648ddc-mwsbk             1/1     Running             0             30s
profile-7fd495b998-xf95m                  0/1     ContainerCreating   0             32s
rate-c986dfd8-hwrrt                       0/1     ContainerCreating   0             31s
recommendation-cfd7f8854-mhwtp            0/1     ContainerCreating   0             31s
reservation-556c4b6db9-m8nkh              0/1     ContainerCreating   0             31s
search-6fb9485964-hzqj7                   0/1     ContainerCreating   0             30s
user-7554f887f-9v9n2                      0/1     ContainerCreating   0             30s
```
```
twaheed2@ocean3:~/go/src/multiparty-lb/hotelReservation$ k describe pod frontend-66895d79c-pbk7f
Name:             frontend-66895d79c-pbk7f
Namespace:        default
Priority:         0
Service Account:  default
Node:             minikube-m02/192.168.59.101
Start Time:       Wed, 22 May 2024 00:58:54 -0500
Labels:           io.kompose.service=frontend
                  pod-template-hash=66895d79c
Annotations:      kompose.cmd: kompose convert
                  kompose.version: 1.22.0 (955b78124)
                  sidecar.istio.io/statsInclusionPrefixes:
                    cluster.outbound,cluster_manager,listener_manager,http_mixer_filter,tcp_mixer_filter,server,cluster.xds-grp,listener,connection_manager
                  sidecar.istio.io/statsInclusionRegexps: http.*
Status:           Running
IP:               10.244.1.17
IPs:
  IP:           10.244.1.17
Controlled By:  ReplicaSet/frontend-66895d79c
Containers:
  hotel-reserv-frontend:
    Container ID:  docker://b6001a9f04a488e95bb821d622ce2d52bb66065a79412272621b78d85ecc5caa
    Image:         deathstarbench/hotel-reservation:0.0.11
    Image ID:      docker-pullable://deathstarbench/hotel-reservation@sha256:5aff98a0383048020c9a7cb73eea8642f3cfa8b9270227c47df8eef1f3a261e0
    Port:          5000/TCP
    Host Port:     0/TCP
    Command:
      ./frontend
    State:          Waiting
      Reason:       RunContainerError
    Last State:     Terminated
      Reason:       ContainerCannotRun
      Message:      failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: exec: "./frontend": stat ./frontend: no such file or directory: unknown
      Exit Code:    127
      Started:      Wed, 22 May 2024 00:59:32 -0500
      Finished:     Wed, 22 May 2024 00:59:32 -0500
    Ready:          False
    Restart Count:  3
    Limits:
      cpu:  1
    Requests:
      cpu:        100m
    Environment:  <none>
    Mounts:
      /var/run/secrets/kubernetes.io/serviceaccount from kube-api-access-gsvcq (ro)
Conditions:
  Type              Status
  Initialized       True 
  Ready             False 
  ContainersReady   False 
  PodScheduled      True 
Volumes:
  kube-api-access-gsvcq:
    Type:                    Projected (a volume that contains injected data from multiple sources)
    TokenExpirationSeconds:  3607
    ConfigMapName:           kube-root-ca.crt
    ConfigMapOptional:       <nil>
    DownwardAPI:             true
QoS Class:                   Burstable
Node-Selectors:              <none>
Tolerations:                 node.kubernetes.io/not-ready:NoExecute op=Exists for 300s
                             node.kubernetes.io/unreachable:NoExecute op=Exists for 300s
Events:
  Type     Reason     Age                From               Message
  ----     ------     ----               ----               -------
  Normal   Scheduled  56s                default-scheduler  Successfully assigned default/frontend-66895d79c-pbk7f to minikube-m02
  Normal   Pulled     18s (x4 over 55s)  kubelet            Container image "deathstarbench/hotel-reservation:0.0.11" already present on machine
  Normal   Created    12s (x4 over 55s)  kubelet            Created container hotel-reserv-frontend
  Warning  Failed     12s (x4 over 55s)  kubelet            Error: failed to start container "hotel-reserv-frontend": Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: runc create failed: unable to start container process: exec: "./frontend": stat ./frontend: no such file or directory: unknown
  Warning  BackOff    0s (x3 over 49s)   kubelet            Back-off restarting failed container hotel-reserv-frontend in pod frontend-66895d79c-pbk7f_default(8c052610-c224-4449-93e9-6594b9885dad)
```

By now, the Minikube (v1.32.0) cluster was made by this command:
```
$ minikube start --nodes 4 --cpus 2 --memory 4096 --driver=virtualbox
$ kubectl version
Client Version: v1.28.4
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
Server Version: v1.28.3
```


I tried to debug the HotelReservation issue, but to no success yet. I will now move to another application -- [Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) (by Google). I again moved to hotelReservation. hotelReservation works with this commit of DeathStarBench: f971f0ed687ce2403437dd97302029d1ed391c2c
```
# we are in the main directory of the repo
kubectl label namespace default istio-injection=enabled
kubectl apply -Rf hotelReservation/kubernetes/
```

To build the host agent docker image:
```
cd host_agent
docker build . -t talhawaheed/hostagent:latest --push
```

To build and run the central controller:
```
cd centralcontroller
go build -o ./centralcontroller .
./centralcontroller 
```

Next, I've used a gateway called istio-ingress applied through
dst-rules_virtual-svcs/istio
```
k apply -Rf dst-rules_virtual-svcs/hotelReservation.yaml
```

Apply the addons in the istio cluster through:
```
kubectl apply -f ~/go/src/istio-1.22.0/samples/addons
kubectl port-forward svc/kiali -n istio-system 20001
```

Now we are going to run the wrk2 to see if we get the changes in the CPU
utilizations
```
cd ./hotelReservation/wrk2/scripts/hotel-reservation/
wrk -D exp -t 2 -c 2 -d 15 -L -s ./wrk2_lua_scripts/mixed-workload_type_1.lua 192.168.59.103:31449 -R 2 
```

```
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.22/samples/addons/jaeger.yaml
istioctl install --set meshConfig.defaultConfig.tracing.zipkin.address=$(kubectl get svc jaeger-collector -n istio-system -o jsonpath='{.spec.clusterIP}'):9411
```

```
hit/hit -d 10 -rps 400 -url http://192.168.59.103:30767/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -l "logs/hit_12"
```

```
wrk -c 30 -t 10 -d 10 -L http://192.168.59.103:30767/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 400
```

```
./wrk -c 500 -t 15 -d 10 -L http://192.168.59.103:30767/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 5000
```

```
./wrk -c 700 -t 15 -d 10 -L http://192.168.59.103:30767/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 5000
```

```
./wrk -c 100 -t 15 -d 30 -L http://192.168.59.103:30767/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 4000
```

```
./wrk -c 100 -t 15 -d 30 -L http://192.168.59.103:31368/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 4000
```

## Towards a working LB solution:

I made the following changes to deployments in `hotelReservation/kubernetes/`:
- `kind: Deployment` -> `kind: StatefulSet`
- `status: <something>` -> `<nothing>`

Everything is working... yayy!

Now we need to write the virtual service and destination rules for the service

### Plan of action:

First, begin by setting virtual service and destination rules yourself for a service through yaml, and then ensuring that the request reaches the particular replica you want.

To do this we will apply dstrules/vsvsc for the profile service repicas and send which hits the svcs frontend, profile, recommendation, and some mongodb/memcached svc
```q
./centralcontroller/centralcontroller
```
```
FRONTEND_IP=$(kubectl get svc frontend -o jsonpath='{.spec.ports[?(@.nodePort)].nodePort}')
./wrk -c 100 -t 15 -d 30 -L http://192.168.59.103:$FRONTEND_IP/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 4000 <add headers here>
```

Modified the hotelReservation.yaml to have an istio ingress that points to the frontend service and then have dst rules and virt svcs to direct it based on the podname provided in the header `x-lb-endpt`:
./wrk -c 100 -t 15 -d 30 -L 
```
INGRESS_PORT=$(kubectl get svc istio-ingressgateway -n istio-system -o=jsonpath='{.spec.ports[?(@.name=="http2")].nodePort}')
CLUSTER_IP=$(minikube ip)
curl --header "x-lb-endpt: frontend-1" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099

error_count=0; for i in {1..100}; do echo "Running attempt $i..."; curl --header "x-lb-endpt: frontend-0" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 100."
error_count=0; for i in {1..100}; do echo "Running attempt $i..."; curl --header "x-lb-endpt: frontend-1" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 100."
error_count=0; for i in {1..100}; do echo "Running attempt $i..."; curl --header "x-lb-endpt: frontend-2" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 100."
error_count=0; for i in {1..100}; do echo "Running attempt $i..."; curl --header "x-lb-endpt: frontend-3" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 100."

error_count=0; for i in {1..100}; do echo "Running attempt $i..."; curl --header "x-lb-endpt: frontend-0" http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 100."

error_count=0; for i in {1..25}; do echo "Running attempt $i..."; curl http://10.99.109.32:80/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 25."


wrk2/wrk -H "x-lb-endpt: frontend-0" -c 100 -t 15 -d 30 -L http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 -R 2000
```
Everything works as expected! Yayy! Only frontend-0 was being utilized. Frontend-1 was not being utilized

_Ensure that only the replica you specified in the header was utilizing CPU_

Write the dstrule/vscv for each svc in hotelreservation <br>
Done
_Ensure everything is working by doing the validation check above, but with a different svc_
Turns out, headers are not propogated to the subsequent sevices, so profile, a different svc, did not follow the header specified in the original request

Once this is done, write the WASM proxy to put in headers for each request according to some predefined weights <br>
_Ensure everything is working by doing the validation check above, but by not assigning headers explicitly in the workload generator_

What am I doing to do this:
- I've changed the code of wasm proxy used for slate (essentially )
- To build, I used build-and-push.sh
- I used instructions from [here](https://tinygo.org/getting-started/install/linux/) to get tinygo:
  ```
  wget https://github.com/tinygo-org/tinygo/releases/download/v0.32.0/tinygo_0.32.0_amd64.deb
  sudo dpkg -i tinygo_0.32.0_amd64.deb
  ```
- There were a syntax errors in hostcall_utils_tinygo.go:
  ```
  twaheed2@ocean3:~/go/src/multiparty-lb/slate-wasm-plugin$ bash build-and-push.sh 
  # github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/internal
  ../../../pkg/mod/github.com/tetratelabs/proxy-wasm-go-sdk@v0.18.0/proxywasm/internal/hostcall_utils_tinygo.go:31:9: cannot use uintptr(size) (value of type uintptr) as int value in struct literal
  ../../../pkg/mod/github.com/tetratelabs/proxy-wasm-go-sdk@v0.18.0/proxywasm/internal/hostcall_utils_tinygo.go:32:9: cannot use uintptr(size) (value of type uintptr) as int value in struct literal
  ../../../pkg/mod/github.com/tetratelabs/proxy-wasm-go-sdk@v0.18.0/proxywasm/internal/hostcall_utils_tinygo.go:39:9: cannot use uintptr(size) (value of type uintptr) as int value in struct literal
  ../../../pkg/mod/github.com/tetratelabs/proxy-wasm-go-sdk@v0.18.0/proxywasm/internal/hostcall_utils_tinygo.go:40:9: cannot use uintptr(size) (value of type uintptr) as int value in struct literal
  ```
  I fixed these by changing `uintptr(size)` to `size` 

- I generated a PAT from github, set it equal to PAT, and ran `echo $PAT | docker login ghcr.io -u talha-waheed --password-stdin` to login to ghcr for docker.
(I had to do this because I hit the limit of pulls from DockerHub)

Then modify the proxy to get the weights from an external controller <br>
_Ensure everything is working by doing the validation check above_
Done
Ran it, two problems:
1. CPU usage stats for recommendation are not coming in logs -- problem diagnosed: the svc is on master node whose node agent is not being called
2. The 

Modify the controller to give weights based on the CPU usages and topology of svc replicas <br>
_Ensure our system is working_

distribution=[exp|norm]
    thread=50
    connection=50
    duration=60


    cluster=$1
    req_type=$2
    RPS=$3
wrk2/wrk -D exp -t50 -c50 -d30s -L -S -s wrk2/mixed_workload_hotel_reservation.lua http://$CLUSTER_IP:$INGRESS_PORT -R4000

wrk2/wrk -D exp -t50 -c50 -d30s -L -S -s wrk2/mixed_workload_hotel_reservation.lua http://$CLUSTER_IP:$INGRESS_PORT -R8000


wrk2/wrk -D exp -t50 -c50 -d30s -L -S -s wrk2/mixed_workload_hotel_reservation.lua http://10.108.145.100:80 -R4000

twaheed2@ocean3:~/go/src/multiparty-lb$ wrk2/wrk -D exp -t50 -c50 -d30s -L -S -s wrk2/mixed_workload_hotel_reservation.lua http://$CLUSTER_IP:$INGRESS_PORT -R8000
Running 30s test @ http://192.168.59.100:32094
  50 threads and 50 connections

  Thread calibration: mean lat.: 5009.760ms, rate sampling interval: 16924ms
  Thread calibration: mean lat.: 4781.920ms, rate sampling interval: 17088ms
  Thread calibration: mean lat.: 5143.834ms, rate sampling interval: 17842ms
  Thread calibration: mean lat.: 4827.302ms, rate sampling interval: 18153ms
  Thread calibration: mean lat.: 5173.137ms, rate sampling interval: 17907ms
  Thread calibration: mean lat.: 5411.131ms, rate sampling interval: 18300ms
  Thread calibration: mean lat.: 5700.598ms, rate sampling interval: 18857ms
  Thread calibration: mean lat.: 5083.370ms, rate sampling interval: 17481ms
  Thread calibration: mean lat.: 4862.555ms, rate sampling interval: 17924ms
  Thread calibration: mean lat.: 4828.560ms, rate sampling interval: 15753ms
  Thread calibration: mean lat.: 5078.712ms, rate sampling interval: 17022ms
  Thread calibration: mean lat.: 5258.565ms, rate sampling interval: 16744ms
  Thread calibration: mean lat.: 4964.001ms, rate sampling interval: 15491ms
  Thread calibration: mean lat.: 5235.803ms, rate sampling interval: 16285ms
  Thread calibration: mean lat.: 4979.968ms, rate sampling interval: 16719ms
  Thread calibration: mean lat.: 5310.904ms, rate sampling interval: 17629ms
  Thread calibration: mean lat.: 5909.344ms, rate sampling interval: 17694ms
  Thread calibration: mean lat.: 5189.410ms, rate sampling interval: 18006ms
  Thread calibration: mean lat.: 5657.825ms, rate sampling interval: 17743ms
  Thread calibration: mean lat.: 4718.098ms, rate sampling interval: 17432ms
  Thread calibration: mean lat.: 5210.934ms, rate sampling interval: 17498ms
  Thread calibration: mean lat.: 5181.781ms, rate sampling interval: 17858ms
  Thread calibration: mean lat.: 5288.210ms, rate sampling interval: 17399ms
  Thread calibration: mean lat.: 4943.143ms, rate sampling interval: 16777ms
  Thread calibration: mean lat.: 5163.460ms, rate sampling interval: 17432ms
  Thread calibration: mean lat.: 4689.060ms, rate sampling interval: 16752ms
  Thread calibration: mean lat.: 5562.258ms, rate sampling interval: 18644ms
  Thread calibration: mean lat.: 5396.992ms, rate sampling interval: 17907ms
  Thread calibration: mean lat.: 5022.286ms, rate sampling interval: 17383ms
  Thread calibration: mean lat.: 4631.330ms, rate sampling interval: 17580ms
  Thread calibration: mean lat.: 5278.400ms, rate sampling interval: 17268ms
  Thread calibration: mean lat.: 5452.307ms, rate sampling interval: 18038ms
  Thread calibration: mean lat.: 5695.378ms, rate sampling interval: 18448ms
  Thread calibration: mean lat.: 5014.784ms, rate sampling interval: 16908ms
  Thread calibration: mean lat.: 5139.108ms, rate sampling interval: 17760ms
  Thread calibration: mean lat.: 5746.115ms, rate sampling interval: 17006ms
  Thread calibration: mean lat.: 4423.560ms, rate sampling interval: 17383ms
  Thread calibration: mean lat.: 5883.101ms, rate sampling interval: 18153ms
  Thread calibration: mean lat.: 5418.837ms, rate sampling interval: 17563ms
  Thread calibration: mean lat.: 5775.402ms, rate sampling interval: 17661ms
  Thread calibration: mean lat.: 5376.694ms, rate sampling interval: 17973ms
  Thread calibration: mean lat.: 5750.052ms, rate sampling interval: 17924ms
  Thread calibration: mean lat.: 5315.163ms, rate sampling interval: 18612ms
  Thread calibration: mean lat.: 5767.133ms, rate sampling interval: 18661ms
  Thread calibration: mean lat.: 5498.325ms, rate sampling interval: 17580ms
  Thread calibration: mean lat.: 5740.680ms, rate sampling interval: 18726ms
  Thread calibration: mean lat.: 5187.118ms, rate sampling interval: 17465ms
  Thread calibration: mean lat.: 5298.901ms, rate sampling interval: 17416ms
  Thread calibration: mean lat.: 5282.816ms, rate sampling interval: 18513ms
  Thread calibration: mean lat.: 5143.570ms, rate sampling interval: 16293ms

-----------------------------------------------------------------------
Test Results @ http://192.168.59.100:32094 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency    19.81s     5.55s   29.33s    57.95%
    Req/Sec     1.00      0.00     1.00    100.00%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%   19.74s 
 75.000%   24.61s 
 90.000%   27.54s 
 99.000%   29.33s 
 99.900%   29.54s 
 99.990%   29.57s 
 99.999%   29.57s 
100.000%   29.57s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

    9232.383     0.000000            1         1.00
   12148.735     0.100000          166         1.11
   14245.887     0.200000          333         1.25
   16056.319     0.300000          499         1.43
   17940.479     0.400000          667         1.67
   19742.719     0.500000          831         2.00
   20578.303     0.550000          913         2.22
   21463.039     0.600000          996         2.50
   22544.383     0.650000         1080         2.86
   23609.343     0.700000         1162         3.33
   24608.767     0.750000         1245         4.00
   25214.975     0.775000         1287         4.44
   25640.959     0.800000         1330         5.00
   26083.327     0.825000         1370         5.71
   26542.079     0.850000         1411         6.67
   27049.983     0.875000         1454         8.00
   27328.511     0.887500         1475         8.89
   27541.503     0.900000         1495        10.00
   27721.727     0.912500         1515        11.43
   28049.407     0.925000         1536        13.33
   28344.319     0.937500         1559        16.00
   28393.471     0.943750         1568        17.78
   28639.231     0.950000         1577        20.00
   28721.151     0.956250         1588        22.86
   28819.455     0.962500         1598        26.67
   28983.295     0.968750         1609        32.00
   29016.063     0.971875         1616        35.56
   29048.831     0.975000         1621        40.00
   29065.215     0.978125         1624        45.71
   29114.367     0.981250         1631        53.33
   29245.439     0.984375         1638        64.00
   29245.439     0.985938         1638        71.11
   29278.207     0.987500         1640        80.00
   29327.359     0.989062         1645        91.43
   29327.359     0.990625         1645       106.67
   29376.511     0.992188         1649       128.00
   29376.511     0.992969         1649       142.22
   29392.895     0.993750         1651       160.00
   29392.895     0.994531         1651       182.86
   29442.047     0.995313         1654       213.33
   29442.047     0.996094         1654       256.00
   29458.431     0.996484         1656       284.44
   29458.431     0.996875         1656       320.00
   29458.431     0.997266         1656       365.71
   29523.967     0.997656         1657       426.67
   29523.967     0.998047         1657       512.00
   29540.351     0.998242         1658       568.89
   29540.351     0.998437         1658       640.00
   29540.351     0.998633         1658       731.43
   29573.119     0.998828         1660       853.33
   29573.119     1.000000         1660          inf
#[Mean    =    19814.385, StdDeviation   =     5545.858]
#[Max     =    29556.736, Total count    =         1660]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  2368 requests in 30.00s, 0.91MB read
Requests/sec:     78.94  
Transfer/sec:     31.15KB
twaheed2@ocean3:~/go/src/multiparty-lb$ wrk2/wrk -D exp -t50 -c50 -d30s -L -S -s wrk2/mixed_workload_hotel_reservation.lua http://$CLUSTER_IP:$INGRESS_PORT -R8000
Running 30s test @ http://192.168.59.100:32094
  50 threads and 50 connections

  Thread calibration: mean lat.: 4967.222ms, rate sampling interval: 17989ms
  Thread calibration: mean lat.: 4924.160ms, rate sampling interval: 16293ms
  Thread calibration: mean lat.: 5732.761ms, rate sampling interval: 18268ms
  Thread calibration: mean lat.: 4291.879ms, rate sampling interval: 16654ms
  Thread calibration: mean lat.: 5153.160ms, rate sampling interval: 18382ms
  Thread calibration: mean lat.: 4517.905ms, rate sampling interval: 16261ms
  Thread calibration: mean lat.: 4795.155ms, rate sampling interval: 16080ms
  Thread calibration: mean lat.: 4339.760ms, rate sampling interval: 16072ms
  Thread calibration: mean lat.: 4461.385ms, rate sampling interval: 16072ms
  Thread calibration: mean lat.: 4346.861ms, rate sampling interval: 16064ms
  Thread calibration: mean lat.: 4280.206ms, rate sampling interval: 16220ms
  Thread calibration: mean lat.: 4817.353ms, rate sampling interval: 17432ms
  Thread calibration: mean lat.: 5209.916ms, rate sampling interval: 16187ms
  Thread calibration: mean lat.: 4116.753ms, rate sampling interval: 15482ms
  Thread calibration: mean lat.: 5604.915ms, rate sampling interval: 18366ms
  Thread calibration: mean lat.: 5308.842ms, rate sampling interval: 18169ms
  Thread calibration: mean lat.: 4743.150ms, rate sampling interval: 18038ms
  Thread calibration: mean lat.: 5010.653ms, rate sampling interval: 18169ms
  Thread calibration: mean lat.: 5348.416ms, rate sampling interval: 17399ms
  Thread calibration: mean lat.: 5597.379ms, rate sampling interval: 17711ms
  Thread calibration: mean lat.: 4979.651ms, rate sampling interval: 16662ms
  Thread calibration: mean lat.: 5053.824ms, rate sampling interval: 17956ms
  Thread calibration: mean lat.: 5589.504ms, rate sampling interval: 18087ms
  Thread calibration: mean lat.: 5221.840ms, rate sampling interval: 17022ms
  Thread calibration: mean lat.: 5447.364ms, rate sampling interval: 18513ms
  Thread calibration: mean lat.: 5330.447ms, rate sampling interval: 17268ms
  Thread calibration: mean lat.: 5877.504ms, rate sampling interval: 17956ms
  Thread calibration: mean lat.: 5790.301ms, rate sampling interval: 17825ms
  Thread calibration: mean lat.: 5168.836ms, rate sampling interval: 17989ms
  Thread calibration: mean lat.: 6104.762ms, rate sampling interval: 17645ms
  Thread calibration: mean lat.: 5266.471ms, rate sampling interval: 18235ms
  Thread calibration: mean lat.: 4749.961ms, rate sampling interval: 16424ms
  Thread calibration: mean lat.: 5010.152ms, rate sampling interval: 16138ms
  Thread calibration: mean lat.: 4876.168ms, rate sampling interval: 17350ms
  Thread calibration: mean lat.: 5785.929ms, rate sampling interval: 18382ms
  Thread calibration: mean lat.: 5937.850ms, rate sampling interval: 18563ms
  Thread calibration: mean lat.: 5820.555ms, rate sampling interval: 17973ms
  Thread calibration: mean lat.: 4854.764ms, rate sampling interval: 15745ms
  Thread calibration: mean lat.: 5136.738ms, rate sampling interval: 17399ms
  Thread calibration: mean lat.: 5204.288ms, rate sampling interval: 17760ms
  Thread calibration: mean lat.: 5153.554ms, rate sampling interval: 16588ms
  Thread calibration: mean lat.: 4571.178ms, rate sampling interval: 16383ms
  Thread calibration: mean lat.: 5409.956ms, rate sampling interval: 17940ms
  Thread calibration: mean lat.: 5566.929ms, rate sampling interval: 18071ms
  Thread calibration: mean lat.: 5574.880ms, rate sampling interval: 18186ms
  Thread calibration: mean lat.: 5734.414ms, rate sampling interval: 17678ms
  Thread calibration: mean lat.: 5559.586ms, rate sampling interval: 18235ms
  Thread calibration: mean lat.: 6021.159ms, rate sampling interval: 19152ms
  Thread calibration: mean lat.: 5301.664ms, rate sampling interval: 16744ms
  Thread calibration: mean lat.: 5489.152ms, rate sampling interval: 18137ms

-----------------------------------------------------------------------
Test Results @ http://192.168.59.100:32094 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency    19.56s     5.81s   29.57s    58.53%
    Req/Sec     1.14      0.35     2.00    100.00%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%   19.43s 
 75.000%   24.74s 
 90.000%   27.66s 
 99.000%   29.57s 
 99.900%   29.67s 
 99.990%   29.69s 
 99.999%   29.69s 
100.000%   29.69s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

    9887.743     0.000000            1         1.00
   11583.487     0.100000          179         1.11
   13737.983     0.200000          356         1.25
   15433.727     0.300000          534         1.43
   17301.503     0.400000          711         1.67
   19431.423     0.500000          890         2.00
   20594.687     0.550000          978         2.22
   21594.111     0.600000         1068         2.50
   22708.223     0.650000         1157         2.86
   23642.111     0.700000         1244         3.33
   24739.839     0.750000         1337         4.00
   25182.207     0.775000         1378         4.44
   25559.039     0.800000         1422         5.00
   26116.095     0.825000         1469         5.71
   26607.615     0.850000         1511         6.67
   27148.287     0.875000         1555         8.00
   27410.431     0.887500         1578         8.89
   27656.191     0.900000         1600        10.00
   27951.103     0.912500         1624        11.43
   28213.247     0.925000         1645        13.33
   28475.391     0.937500         1667        16.00
   28590.079     0.943750         1679        17.78
   28721.151     0.950000         1691        20.00
   28786.687     0.956250         1700        22.86
   28950.527     0.962500         1711        26.67
   29065.215     0.968750         1724        32.00
   29114.367     0.971875         1728        35.56
   29278.207     0.975000         1734        40.00
   29360.127     0.978125         1739        45.71
   29474.815     0.981250         1744        53.33
   29523.967     0.984375         1750        64.00
   29556.735     0.985938         1756        71.11
   29556.735     0.987500         1756        80.00
   29573.119     0.989062         1760        91.43
   29589.503     0.990625         1765       106.67
   29589.503     0.992188         1765       128.00
   29589.503     0.992969         1765       142.22
   29605.887     0.993750         1766       160.00
   29622.271     0.994531         1768       182.86
   29638.655     0.995313         1772       213.33
   29638.655     0.996094         1772       256.00
   29638.655     0.996484         1772       284.44
   29638.655     0.996875         1772       320.00
   29655.039     0.997266         1774       365.71
   29655.039     0.997656         1774       426.67
   29655.039     0.998047         1774       512.00
   29655.039     0.998242         1774       568.89
   29671.423     0.998437         1775       640.00
   29671.423     0.998633         1775       731.43
   29671.423     0.998828         1775       853.33
   29687.807     0.999023         1777      1024.00
   29687.807     1.000000         1777          inf
#[Mean    =    19561.131, StdDeviation   =     5805.623]
#[Max     =    29671.424, Total count    =         1777]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  2478 requests in 30.00s, 0.99MB read
  Non-2xx or 3xx responses: 1
Requests/sec:     82.60  
Transfer/sec:     33.81KB

300005 -> -R8000 without LB enforcement
300006 -> -R8000 with LB enforcement

30007 -> -R4000 with LB enforcement
30008 -> -R4000 without LB enforcement

30009 -> -R4000 without LB enforcement
30010 -> -R4000 with LB enforcement

Todo: make hostagents a statefulset

To only have reserve, rate, search services on the worker nodes:
```
kubectl taint nodes minikube-m02 node=node1:NoSchedule
kubectl taint nodes minikube-m03 node=node2:NoSchedule
kubectl taint nodes minikube-m04 node=node3:NoSchedule
```

- Added tolerations to rate, search and worker

https://github.com/kubernetes/kubernetes/issues/77508

exec sudo su -l $USER

checking to see if pushes from cloudlab node work



It is 3 dp off

FRONTEND_IP=$(kubectl get svc frontend -n default -o jsonpath='{.spec.clusterIP}')
GATEWAY_IP=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath='{.spec.clusterIP}')

curl http://$FRONTEND_IP:5000/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099
curl http://$GATEWAY_IP:80/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099

wrk2/wrk -c 100 -t 15 -d 30 -L -R4000 http://$GATEWAY_IP:80/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099

wrk2/wrk -D exp -t 25 -c 25 -d 15 -L -s wrk2/wrk2_lua_scripts/mixed-workload_type_1.lua $GATEWAY_IP:80 -R500 

wrk2/wrk -D exp -t 25 -c 25 -d 30 -L -s wrk2/recommend.lua $GATEWAY_IP:80 -R500

wrk2/wrk -D exp -t 25 -c 25 -d 30 -L -s wrk2/recommend.lua http://$GATEWAY_IP:80 -R500


wrk2/wrk -D exp -t 25 -c 25 -d 30 -L -s wrk2/scripts/reserve.lua http://$GATEWAY_IP:80 -R500


To saturate the CPU 50% from user, use
wrk2/wrk -D exp -t 25 -c 25 -d 30 -L -s wrk2/scripts/user_login.lua http://$GATEWAY_IP:80 -R300

To saturate the CPU 50% from reservation, use
wrk2/wrk -D exp -t 25 -c 25 -d 30 -L -s wrk2/scripts/search_hotel.lua http://$GATEWAY_IP:80 -R50


-- Why is user-0 not using CPU available?

1. Istio might have some concurrency constraints -- not the reason
2. GPRC might have a max concurrent streams -- not the reason (changed defaultMaxConcurrentStreams from 1000 to 10000 in transport.go, but still the cap was 136%)
3. GRPC might have a max on thread pool size -- 

Steps to repeat the experiment I showed in the slides
This is a redo of the 3-node experiment with the current setup and hotelreservation

1. Ensure that liveCPUStats is working with latency information (Done)
2. Check the difference between liveCPUStats and central controller and try to make a single file from them that does both the tasks
3. Run the experiment

Step 1:
1. Edit liveCPUStats to also log the request latencies
2. Do curls to the Gateway and check if latency data is logged in the liveCPUStats program
3. If not, debug where the issue is
Done scene,


But there is some problem due to which the lges

Side work: Why is there a frontend-0 to frontend-0


To cap a nodes's k8s resources by 1 CPU, run this command on that node:
`sudo su -c "echo '100000 100000' > /sys/fs/cgroup/kubepods.slice/cpu.max"`


PODNAME                        CPU (%)            PODNAME                        CPU (%)                  
frontend-0                     136.86             frontend-0                     195.09                
reservation-0                  69.12              reservation-1                  92.95                
reservation-1                  65.68              reservation-0                  91.75                
search-0                       50.34              user-0                         74.11                
user-0                         49.54              search-0                       70.56                
rate-0                         36.53              rate-1                         48.64                
rate-1                         32.93              rate-0                         43.52                
geo-0                          18.08              geo-0                          25.85                
mongodb-rate-0                 16.66              mongodb-rate-0                 25.20                
profile-0                      15.48              profile-0                      20.78                
jaeger-0                       5.15               jaeger-0                       5.51              
hostagent-node0-0              4.44               hostagent-node0-0              4.41              
consul-0                       2.21               consul-0                       1.90              
mongodb-reservation-0          1.53               mongodb-recommendation-0       1.84              
hostagent-node4-0              1.51               hostagent-node4-0              1.55              
hostagent-node5-0              1.11               memcached-profile-0            1.42              
memcached-reserve-0            1.03               mongodb-user-0                 1.20              
mongodb-geo-0                  0.94               mongodb-profile-0              1.16              
mongodb-profile-0              0.88               mongodb-geo-0                  1.13              
mongodb-recommendation-0       0.86               hostagent-node5-0              1.04              
mongodb-user-0                 0.86               hostagent-node1-0              0.97              
memcached-rate-0               0.79               mongodb-reservation-0          0.92              
hostagent-node2-0              0.72               hostagent-node2-0              0.90              
memcached-profile-0            0.70               hostagent-node3-0              0.83              
hostagent-node1-0              0.68               memcached-rate-0               0.44              
hostagent-node3-0              0.68               recommendation-0               0.37              
recommendation-0               0.39               memcached-reserve-0            0.36              

---


PODNAME                        CPU (%)
frontend-0                     135.60
reservation-0                  77.80
reservation-1                  68.12
search-0                       54.09
user-0                         49.02
rate-0                         36.84
rate-1                         29.38
geo-0                          20.07
mongodb-rate-0                 18.42
profile-0                      16.79
memcached-profile-0            5.28
jaeger-0                       5.27
hostagent-node0-0              4.44
consul-0                       2.26
mongodb-profile-0              1.61
mongodb-user-0                 1.57
hostagent-node5-0              1.46
mongodb-recommendation-0       1.32
mongodb-reservation-0          1.03
hostagent-node2-0              0.90
mongodb-geo-0                  0.88
hostagent-node4-0              0.80
hostagent-node3-0              0.76
hostagent-node1-0              0.67
recommendation-0               0.49
memcached-rate-0               0.47
memcached-reserve-0            0.40



wrk2/wrk -t 50 -c 50 -d 15 -L -s wrk2/scripts/3_node_scenario.lua http://$GATEWAY_IP:80/ -R650
Running 15s test @ http://10.103.140.24:80/
  50 threads and 50 connections

reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
reconnect_socket
  Thread calibration: mean lat.: 1694.915ms, rate sampling interval: 5677ms
  Thread calibration: mean lat.: 1985.732ms, rate sampling interval: 6696ms
  Thread calibration: mean lat.: 1592.020ms, rate sampling interval: 6275ms
  Thread calibration: mean lat.: 1404.657ms, rate sampling interval: 5791ms
  Thread calibration: mean lat.: 1433.573ms, rate sampling interval: 4800ms
  Thread calibration: mean lat.: 1525.846ms, rate sampling interval: 5681ms
  Thread calibration: mean lat.: 1712.958ms, rate sampling interval: 6021ms
  Thread calibration: mean lat.: 1733.370ms, rate sampling interval: 5373ms
  Thread calibration: mean lat.: 1893.917ms, rate sampling interval: 7032ms
  Thread calibration: mean lat.: 1196.801ms, rate sampling interval: 3885ms
  Thread calibration: mean lat.: 1533.571ms, rate sampling interval: 5603ms
  Thread calibration: mean lat.: 1371.008ms, rate sampling interval: 5099ms
  Thread calibration: mean lat.: 1854.054ms, rate sampling interval: 6287ms
  Thread calibration: mean lat.: 1442.344ms, rate sampling interval: 5509ms
  Thread calibration: mean lat.: 1405.525ms, rate sampling interval: 5136ms
  Thread calibration: mean lat.: 1356.470ms, rate sampling interval: 4935ms
  Thread calibration: mean lat.: 1556.934ms, rate sampling interval: 5914ms
  Thread calibration: mean lat.: 1540.527ms, rate sampling interval: 5910ms
  Thread calibration: mean lat.: 1604.831ms, rate sampling interval: 5312ms
  Thread calibration: mean lat.: 1267.506ms, rate sampling interval: 5337ms
  Thread calibration: mean lat.: 1885.601ms, rate sampling interval: 6168ms
  Thread calibration: mean lat.: 899.740ms, rate sampling interval: 3860ms
  Thread calibration: mean lat.: 1898.728ms, rate sampling interval: 6578ms
  Thread calibration: mean lat.: 1636.264ms, rate sampling interval: 6000ms
  Thread calibration: mean lat.: 1728.991ms, rate sampling interval: 6246ms
  Thread calibration: mean lat.: 1440.300ms, rate sampling interval: 5140ms
  Thread calibration: mean lat.: 1528.906ms, rate sampling interval: 5423ms
  Thread calibration: mean lat.: 1727.716ms, rate sampling interval: 6029ms
  Thread calibration: mean lat.: 1587.126ms, rate sampling interval: 5939ms
  Thread calibration: mean lat.: 1898.281ms, rate sampling interval: 6770ms
  Thread calibration: mean lat.: 1474.675ms, rate sampling interval: 5226ms
  Thread calibration: mean lat.: 1502.548ms, rate sampling interval: 5541ms
  Thread calibration: mean lat.: 1769.445ms, rate sampling interval: 6729ms
  Thread calibration: mean lat.: 1408.154ms, rate sampling interval: 5312ms
  Thread calibration: mean lat.: 1603.224ms, rate sampling interval: 5890ms
  Thread calibration: mean lat.: 1794.038ms, rate sampling interval: 6500ms
  Thread calibration: mean lat.: 1337.749ms, rate sampling interval: 5267ms
  Thread calibration: mean lat.: 1300.169ms, rate sampling interval: 4993ms
  Thread calibration: mean lat.: 1773.015ms, rate sampling interval: 6512ms
  Thread calibration: mean lat.: 1080.287ms, rate sampling interval: 4175ms
  Thread calibration: mean lat.: 1848.905ms, rate sampling interval: 6246ms
  Thread calibration: mean lat.: 1733.965ms, rate sampling interval: 6049ms
  Thread calibration: mean lat.: 965.857ms, rate sampling interval: 4042ms
  Thread calibration: mean lat.: 1725.507ms, rate sampling interval: 6230ms
  Thread calibration: mean lat.: 2005.973ms, rate sampling interval: 6635ms
  Thread calibration: mean lat.: 1494.865ms, rate sampling interval: 4825ms
  Thread calibration: mean lat.: 1789.334ms, rate sampling interval: 6676ms
  Thread calibration: mean lat.: 1840.736ms, rate sampling interval: 6676ms
  Thread calibration: mean lat.: 1450.268ms, rate sampling interval: 5558ms
  Thread calibration: mean lat.: 1075.813ms, rate sampling interval: 4280ms

-----------------------------------------------------------------------
Test Results @ http://10.103.140.24:80/ 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency     3.93s   603.54ms   5.17s    66.88%
    Req/Sec     8.00      0.67     9.00    100.00%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    3.92s 
 75.000%    4.37s 
 90.000%    4.70s 
 99.000%    5.17s 
 99.900%    5.35s 
 99.990%    5.49s 
 99.999%    5.49s 
100.000%    5.49s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

    2055.167     0.000000            1         1.00
    3158.015     0.100000          224         1.11
    3409.919     0.200000          448         1.25
    3600.383     0.300000          672         1.43
    3772.415     0.400000          899         1.67
    3921.919     0.500000         1119         2.00
    4005.887     0.550000         1232         2.22
    4089.855     0.600000         1344         2.50
    4177.919     0.650000         1455         2.86
    4284.415     0.700000         1570         3.33
    4366.335     0.750000         1681         4.00
    4427.775     0.775000         1735         4.44
    4472.831     0.800000         1793         5.00
    4521.983     0.825000         1850         5.71
    4583.423     0.850000         1903         6.67
    4640.767     0.875000         1961         8.00
    4673.535     0.887500         1986         8.89
    4706.303     0.900000         2017        10.00
    4751.359     0.912500         2043        11.43
    4800.511     0.925000         2075        13.33
    4845.567     0.937500         2100        16.00
    4874.239     0.943750         2112        17.78
    4915.199     0.950000         2127        20.00
    4943.871     0.956250         2141        22.86
    4980.735     0.962500         2156        26.67
    5009.407     0.968750         2169        32.00
    5025.791     0.971875         2176        35.56
    5054.463     0.975000         2182        40.00
    5087.231     0.978125         2192        45.71
    5115.903     0.981250         2199        53.33
    5136.383     0.984375         2205        64.00
    5140.479     0.985938         2206        71.11
    5148.671     0.987500         2210        80.00
    5160.959     0.989062         2214        91.43
    5173.247     0.990625         2217       106.67
    5193.727     0.992188         2220       128.00
    5210.111     0.992969         2222       142.22
    5226.495     0.993750         2225       160.00
    5226.495     0.994531         2225       182.86
    5246.975     0.995313         2227       213.33
    5271.551     0.996094         2229       256.00
    5292.031     0.996484         2230       284.44
    5300.223     0.996875         2231       320.00
    5300.223     0.997266         2231       365.71
    5312.511     0.997656         2232       426.67
    5337.087     0.998047         2233       512.00
    5345.279     0.998242         2234       568.89
    5345.279     0.998437         2234       640.00
    5345.279     0.998633         2234       731.43
    5349.375     0.998828         2235       853.33
    5349.375     0.999023         2235      1024.00
    5459.967     0.999121         2236      1137.78
    5459.967     0.999219         2236      1280.00
    5459.967     0.999316         2236      1462.86
    5459.967     0.999414         2236      1706.67
    5459.967     0.999512         2236      2048.00
    5488.639     0.999561         2237      2275.56
    5488.639     1.000000         2237          inf
#[Mean    =     3925.397, StdDeviation   =      603.537]
#[Max     =     5484.544, Total count    =         2237]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  6712 requests in 15.10s, 1.85MB read
Requests/sec:    444.60  
Transfer/sec:    125.19KB

twaheed@node0:~/multiparty-lb$ wrk2/wrk -t 50 -c 50 -d 15 -L -s wrk2/scripts/3_node_scenario.lua http://$GATEWAY_IP:80/ -R650
Running 15s test @ http://10.103.140.24:80/
  50 threads and 50 connections

  Thread calibration: mean lat.: 1311.496ms, rate sampling interval: 6037ms
  Thread calibration: mean lat.: 1083.323ms, rate sampling interval: 3631ms
  Thread calibration: mean lat.: 1890.292ms, rate sampling interval: 6049ms
  Thread calibration: mean lat.: 662.248ms, rate sampling interval: 2643ms
  Thread calibration: mean lat.: 939.338ms, rate sampling interval: 3160ms
  Thread calibration: mean lat.: 1680.161ms, rate sampling interval: 6066ms
  Thread calibration: mean lat.: 1570.248ms, rate sampling interval: 4812ms
  Thread calibration: mean lat.: 1592.563ms, rate sampling interval: 4159ms
  Thread calibration: mean lat.: 1950.524ms, rate sampling interval: 7139ms
  Thread calibration: mean lat.: 2040.910ms, rate sampling interval: 6705ms
  Thread calibration: mean lat.: 1625.858ms, rate sampling interval: 6295ms
  Thread calibration: mean lat.: 1740.438ms, rate sampling interval: 5967ms
  Thread calibration: mean lat.: 939.768ms, rate sampling interval: 3057ms
  Thread calibration: mean lat.: 1190.864ms, rate sampling interval: 4048ms
  Thread calibration: mean lat.: 1351.220ms, rate sampling interval: 4157ms
  Thread calibration: mean lat.: 900.630ms, rate sampling interval: 2787ms
  Thread calibration: mean lat.: 1433.311ms, rate sampling interval: 4956ms
  Thread calibration: mean lat.: 1625.588ms, rate sampling interval: 4808ms
  Thread calibration: mean lat.: 1845.793ms, rate sampling interval: 5963ms
  Thread calibration: mean lat.: 2144.462ms, rate sampling interval: 7081ms
  Thread calibration: mean lat.: 2475.244ms, rate sampling interval: 7401ms
  Thread calibration: mean lat.: 1339.866ms, rate sampling interval: 4771ms
  Thread calibration: mean lat.: 2212.423ms, rate sampling interval: 6651ms
  Thread calibration: mean lat.: 2234.113ms, rate sampling interval: 7819ms
  Thread calibration: mean lat.: 1177.909ms, rate sampling interval: 3293ms
  Thread calibration: mean lat.: 809.068ms, rate sampling interval: 3356ms
  Thread calibration: mean lat.: 651.072ms, rate sampling interval: 2201ms
  Thread calibration: mean lat.: 1800.806ms, rate sampling interval: 6213ms
  Thread calibration: mean lat.: 1557.824ms, rate sampling interval: 5079ms
  Thread calibration: mean lat.: 1534.516ms, rate sampling interval: 4943ms
  Thread calibration: mean lat.: 1322.686ms, rate sampling interval: 4993ms
  Thread calibration: mean lat.: 1667.658ms, rate sampling interval: 4960ms
  Thread calibration: mean lat.: 1688.554ms, rate sampling interval: 4739ms
  Thread calibration: mean lat.: 1238.894ms, rate sampling interval: 4521ms
  Thread calibration: mean lat.: 1470.936ms, rate sampling interval: 4139ms
  Thread calibration: mean lat.: 1077.796ms, rate sampling interval: 4296ms
  Thread calibration: mean lat.: 1141.974ms, rate sampling interval: 4493ms
  Thread calibration: mean lat.: 1833.471ms, rate sampling interval: 6549ms
  Thread calibration: mean lat.: 2174.794ms, rate sampling interval: 7159ms
  Thread calibration: mean lat.: 1996.977ms, rate sampling interval: 8359ms
  Thread calibration: mean lat.: 1900.681ms, rate sampling interval: 6545ms
  Thread calibration: mean lat.: 614.560ms, rate sampling interval: 2056ms
  Thread calibration: mean lat.: 1631.218ms, rate sampling interval: 5464ms
  Thread calibration: mean lat.: 1738.039ms, rate sampling interval: 4857ms
  Thread calibration: mean lat.: 1385.756ms, rate sampling interval: 5201ms
  Thread calibration: mean lat.: 1819.869ms, rate sampling interval: 6496ms
  Thread calibration: mean lat.: 845.102ms, rate sampling interval: 3170ms
  Thread calibration: mean lat.: 1706.465ms, rate sampling interval: 5459ms
  Thread calibration: mean lat.: 1587.078ms, rate sampling interval: 6320ms
  Thread calibration: mean lat.: 1887.718ms, rate sampling interval: 5464ms

-----------------------------------------------------------------------
Test Results @ http://10.103.140.24:80/ 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency     3.59s     1.08s    6.12s    67.21%
    Req/Sec     8.72      0.94    11.00     96.55%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    3.69s 
 75.000%    4.29s 
 90.000%    4.94s 
 99.000%    6.12s 
 99.900%    6.98s 
 99.990%    7.04s 
 99.999%    7.04s 
100.000%    7.04s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

     836.607     0.000000            1         1.00
    2072.575     0.100000          230         1.11
    2668.543     0.200000          459         1.25
    3065.855     0.300000          689         1.43
    3356.671     0.400000          916         1.67
    3686.399     0.500000         1147         2.00
    3827.711     0.550000         1260         2.22
    3942.399     0.600000         1374         2.50
    4036.607     0.650000         1489         2.86
    4167.679     0.700000         1606         3.33
    4288.511     0.750000         1719         4.00
    4358.143     0.775000         1775         4.44
    4468.735     0.800000         1833         5.00
    4583.423     0.825000         1893         5.71
    4689.919     0.850000         1948         6.67
    4849.663     0.875000         2005         8.00
    4894.719     0.887500         2036         8.89
    4943.871     0.900000         2061        10.00
    5001.215     0.912500         2092        11.43
    5066.751     0.925000         2119        13.33
    5140.479     0.937500         2148        16.00
    5185.535     0.943750         2162        17.78
    5251.071     0.950000         2176        20.00
    5283.839     0.956250         2190        22.86
    5328.895     0.962500         2205        26.67
    5423.103     0.968750         2219        32.00
    5464.063     0.971875         2226        35.56
    5550.079     0.975000         2233        40.00
    5627.903     0.978125         2240        45.71
    5685.247     0.981250         2248        53.33
    5742.591     0.984375         2255        64.00
    5791.743     0.985938         2258        71.11
    5820.415     0.987500         2262        80.00
    6029.311     0.989062         2265        91.43
    6266.879     0.990625         2269       106.67
    6549.503     0.992188         2273       128.00
    6590.463     0.992969         2274       142.22
    6619.135     0.993750         2276       160.00
    6623.231     0.994531         2278       182.86
    6631.423     0.995313         2280       213.33
    6664.191     0.996094         2282       256.00
    6664.191     0.996484         2282       284.44
    6688.767     0.996875         2283       320.00
    6774.783     0.997266         2284       365.71
    6803.455     0.997656         2285       426.67
    6950.911     0.998047         2286       512.00
    6950.911     0.998242         2286       568.89
    6955.007     0.998437         2287       640.00
    6955.007     0.998633         2287       731.43
    6979.583     0.998828         2288       853.33
    6979.583     0.999023         2288      1024.00
    6979.583     0.999121         2288      1137.78
    7020.543     0.999219         2289      1280.00
    7020.543     0.999316         2289      1462.86
    7020.543     0.999414         2289      1706.67
    7020.543     0.999512         2289      2048.00
    7020.543     0.999561         2289      2275.56
    7041.023     0.999609         2290      2560.00
    7041.023     1.000000         2290          inf
#[Mean    =     3591.613, StdDeviation   =     1081.140]
#[Max     =     7036.928, Total count    =         2290]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  6999 requests in 15.08s, 1.92MB read
Requests/sec:    464.15  
Transfer/sec:    130.64KB


twaheed@node0:~/multiparty-lb$ wrk2/wrk -t 50 -c 50 -d 15 -L -s wrk2/scripts/3_node_scenario.lua http://$GATEWAY_IP:80/ -R700 
Running 15s test @ http://10.103.140.24:80/
  50 threads and 50 connections

  Thread calibration: mean lat.: 1362.019ms, rate sampling interval: 4259ms
  Thread calibration: mean lat.: 1718.827ms, rate sampling interval: 5857ms
  Thread calibration: mean lat.: 1635.798ms, rate sampling interval: 4763ms
  Thread calibration: mean lat.: 1561.421ms, rate sampling interval: 5857ms
  Thread calibration: mean lat.: 1383.994ms, rate sampling interval: 4833ms
  Thread calibration: mean lat.: 1956.459ms, rate sampling interval: 6795ms
  Thread calibration: mean lat.: 1931.025ms, rate sampling interval: 6365ms
  Thread calibration: mean lat.: 1445.130ms, rate sampling interval: 4661ms
  Thread calibration: mean lat.: 1942.378ms, rate sampling interval: 6275ms
  Thread calibration: mean lat.: 1930.143ms, rate sampling interval: 6545ms
  Thread calibration: mean lat.: 1584.337ms, rate sampling interval: 5029ms
  Thread calibration: mean lat.: 1392.561ms, rate sampling interval: 4231ms
  Thread calibration: mean lat.: 1808.038ms, rate sampling interval: 5988ms
  Thread calibration: mean lat.: 2103.943ms, rate sampling interval: 7163ms
  Thread calibration: mean lat.: 1873.644ms, rate sampling interval: 6262ms
  Thread calibration: mean lat.: 1857.563ms, rate sampling interval: 6119ms
  Thread calibration: mean lat.: 1663.032ms, rate sampling interval: 5038ms
  Thread calibration: mean lat.: 1617.058ms, rate sampling interval: 4960ms
  Thread calibration: mean lat.: 1958.619ms, rate sampling interval: 6262ms
  Thread calibration: mean lat.: 1588.599ms, rate sampling interval: 5042ms
  Thread calibration: mean lat.: 1760.535ms, rate sampling interval: 6098ms
  Thread calibration: mean lat.: 1798.209ms, rate sampling interval: 5681ms
  Thread calibration: mean lat.: 1920.257ms, rate sampling interval: 6025ms
  Thread calibration: mean lat.: 1954.902ms, rate sampling interval: 5984ms
  Thread calibration: mean lat.: 1336.569ms, rate sampling interval: 3962ms
  Thread calibration: mean lat.: 1743.484ms, rate sampling interval: 5287ms
  Thread calibration: mean lat.: 1729.738ms, rate sampling interval: 5275ms
  Thread calibration: mean lat.: 1830.699ms, rate sampling interval: 6094ms
  Thread calibration: mean lat.: 1216.551ms, rate sampling interval: 3811ms
  Thread calibration: mean lat.: 1923.801ms, rate sampling interval: 6377ms
  Thread calibration: mean lat.: 1648.803ms, rate sampling interval: 5087ms
  Thread calibration: mean lat.: 1583.029ms, rate sampling interval: 5386ms
  Thread calibration: mean lat.: 1899.519ms, rate sampling interval: 6295ms
  Thread calibration: mean lat.: 1694.083ms, rate sampling interval: 5394ms
  Thread calibration: mean lat.: 1087.747ms, rate sampling interval: 3805ms
  Thread calibration: mean lat.: 1922.699ms, rate sampling interval: 6664ms
  Thread calibration: mean lat.: 1896.615ms, rate sampling interval: 6655ms
  Thread calibration: mean lat.: 1979.598ms, rate sampling interval: 6389ms
  Thread calibration: mean lat.: 1527.929ms, rate sampling interval: 4800ms
  Thread calibration: mean lat.: 1771.581ms, rate sampling interval: 5943ms
  Thread calibration: mean lat.: 1644.655ms, rate sampling interval: 5713ms
  Thread calibration: mean lat.: 1950.680ms, rate sampling interval: 6135ms
  Thread calibration: mean lat.: 1805.591ms, rate sampling interval: 5107ms
  Thread calibration: mean lat.: 1496.674ms, rate sampling interval: 4272ms
  Thread calibration: mean lat.: 1883.115ms, rate sampling interval: 6176ms
  Thread calibration: mean lat.: 1927.813ms, rate sampling interval: 6639ms
  Thread calibration: mean lat.: 1834.249ms, rate sampling interval: 5693ms
  Thread calibration: mean lat.: 1465.506ms, rate sampling interval: 4157ms
  Thread calibration: mean lat.: 1964.781ms, rate sampling interval: 6361ms
  Thread calibration: mean lat.: 1549.961ms, rate sampling interval: 4829ms

-----------------------------------------------------------------------
Test Results @ http://10.103.140.24:80/ 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency     3.50s   730.44ms   5.23s    63.04%
    Req/Sec    10.83      1.38    14.00     94.44%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    3.56s 
 75.000%    3.99s 
 90.000%    4.44s 
 99.000%    5.23s 
 99.900%    5.58s 
 99.990%    5.71s 
 99.999%    5.71s 
100.000%    5.71s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

    1978.367     0.000000            2         1.00
    2488.319     0.100000          267         1.11
    2738.175     0.200000          534         1.25
    3043.327     0.300000          802         1.43
    3332.095     0.400000         1067         1.67
    3559.423     0.500000         1333         2.00
    3663.871     0.550000         1469         2.22
    3745.791     0.600000         1599         2.50
    3819.519     0.650000         1734         2.86
    3905.535     0.700000         1867         3.33
    3991.551     0.750000         2000         4.00
    4046.847     0.775000         2067         4.44
    4122.623     0.800000         2132         5.00
    4177.919     0.825000         2199         5.71
    4255.743     0.850000         2267         6.67
    4341.759     0.875000         2334         8.00
    4390.911     0.887500         2369         8.89
    4440.063     0.900000         2399        10.00
    4505.599     0.912500         2435        11.43
    4571.135     0.925000         2470        13.33
    4603.903     0.937500         2499        16.00
    4657.151     0.943750         2518        17.78
    4689.919     0.950000         2534        20.00
    4722.687     0.956250         2549        22.86
    4784.127     0.962500         2567        26.67
    4841.471     0.968750         2582        32.00
    4866.047     0.971875         2591        35.56
    4898.815     0.975000         2600        40.00
    4935.679     0.978125         2607        45.71
    4988.927     0.981250         2616        53.33
    5058.559     0.984375         2624        64.00
    5136.383     0.985938         2628        71.11
    5173.247     0.987500         2632        80.00
    5206.015     0.989062         2637        91.43
    5292.031     0.990625         2642       106.67
    5312.511     0.992188         2645       128.00
    5320.703     0.992969         2647       142.22
    5361.663     0.993750         2650       160.00
    5373.951     0.994531         2651       182.86
    5390.335     0.995313         2653       213.33
    5410.815     0.996094         2655       256.00
    5427.199     0.996484         2656       284.44
    5431.295     0.996875         2657       320.00
    5451.775     0.997266         2658       365.71
    5455.871     0.997656         2659       426.67
    5541.887     0.998047         2660       512.00
    5570.559     0.998242         2661       568.89
    5570.559     0.998437         2661       640.00
    5582.847     0.998633         2662       731.43
    5582.847     0.998828         2662       853.33
    5619.711     0.999023         2663      1024.00
    5619.711     0.999121         2663      1137.78
    5619.711     0.999219         2663      1280.00
    5672.959     0.999316         2664      1462.86
    5672.959     0.999414         2664      1706.67
    5672.959     0.999512         2664      2048.00
    5672.959     0.999561         2664      2275.56
    5672.959     0.999609         2664      2560.00
    5713.919     0.999658         2665      2925.71
    5713.919     1.000000         2665          inf
#[Mean    =     3498.561, StdDeviation   =      730.444]
#[Max     =     5709.824, Total count    =         2665]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  7616 requests in 15.30s, 2.09MB read
Requests/sec:    497.76  
Transfer/sec:    140.04KB


twaheed@node0:~/multiparty-lb$ wrk2/wrk -t 50 -c 50 -d 15 -L -s wrk2/scripts/3_node_scenario.lua http://$GATEWAY_IP:80/ -R700 
Running 15s test @ http://10.103.140.24:80/
  50 threads and 50 connections

  Thread calibration: mean lat.: 970.300ms, rate sampling interval: 4227ms
  Thread calibration: mean lat.: 1747.864ms, rate sampling interval: 5763ms
  Thread calibration: mean lat.: 2497.915ms, rate sampling interval: 8269ms
  Thread calibration: mean lat.: 1373.330ms, rate sampling interval: 4509ms
  Thread calibration: mean lat.: 1490.027ms, rate sampling interval: 4046ms
  Thread calibration: mean lat.: 1190.309ms, rate sampling interval: 5652ms
  Thread calibration: mean lat.: 1050.772ms, rate sampling interval: 3080ms
  Thread calibration: mean lat.: 1187.024ms, rate sampling interval: 4206ms
  Thread calibration: mean lat.: 834.007ms, rate sampling interval: 3268ms
  Thread calibration: mean lat.: 1620.303ms, rate sampling interval: 5062ms
  Thread calibration: mean lat.: 1319.941ms, rate sampling interval: 3842ms
  Thread calibration: mean lat.: 1215.522ms, rate sampling interval: 4163ms
  Thread calibration: mean lat.: 1315.387ms, rate sampling interval: 5398ms
  Thread calibration: mean lat.: 2367.811ms, rate sampling interval: 8863ms
  Thread calibration: mean lat.: 1575.776ms, rate sampling interval: 5750ms
  Thread calibration: mean lat.: 1149.851ms, rate sampling interval: 3385ms
  Thread calibration: mean lat.: 482.098ms, rate sampling interval: 2676ms
  Thread calibration: mean lat.: 1206.992ms, rate sampling interval: 3467ms
  Thread calibration: mean lat.: 685.487ms, rate sampling interval: 2484ms
  Thread calibration: mean lat.: 1924.843ms, rate sampling interval: 5693ms
  Thread calibration: mean lat.: 1574.679ms, rate sampling interval: 5251ms
  Thread calibration: mean lat.: 1106.380ms, rate sampling interval: 4505ms
  Thread calibration: mean lat.: 610.911ms, rate sampling interval: 1935ms
  Thread calibration: mean lat.: 919.348ms, rate sampling interval: 2953ms
  Thread calibration: mean lat.: 2027.796ms, rate sampling interval: 6860ms
  Thread calibration: mean lat.: 1485.751ms, rate sampling interval: 4530ms
  Thread calibration: mean lat.: 1330.345ms, rate sampling interval: 4395ms
  Thread calibration: mean lat.: 1499.611ms, rate sampling interval: 5181ms
  Thread calibration: mean lat.: 1217.724ms, rate sampling interval: 5251ms
  Thread calibration: mean lat.: 463.823ms, rate sampling interval: 1685ms
  Thread calibration: mean lat.: 411.917ms, rate sampling interval: 1301ms
  Thread calibration: mean lat.: 1960.833ms, rate sampling interval: 6934ms
  Thread calibration: mean lat.: 1526.905ms, rate sampling interval: 6262ms
  Thread calibration: mean lat.: 1029.511ms, rate sampling interval: 4329ms
  Thread calibration: mean lat.: 1201.290ms, rate sampling interval: 4329ms
  Thread calibration: mean lat.: 1341.992ms, rate sampling interval: 4003ms
  Thread calibration: mean lat.: 1406.406ms, rate sampling interval: 5173ms
  Thread calibration: mean lat.: 1873.691ms, rate sampling interval: 6209ms
  Thread calibration: mean lat.: 1106.227ms, rate sampling interval: 4288ms
  Thread calibration: mean lat.: 1329.728ms, rate sampling interval: 4923ms
  Thread calibration: mean lat.: 504.962ms, rate sampling interval: 1565ms
  Thread calibration: mean lat.: 1439.461ms, rate sampling interval: 6778ms
  Thread calibration: mean lat.: 1127.308ms, rate sampling interval: 4870ms
  Thread calibration: mean lat.: 1035.091ms, rate sampling interval: 3764ms
  Thread calibration: mean lat.: 1594.371ms, rate sampling interval: 4759ms
  Thread calibration: mean lat.: 262.118ms, rate sampling interval: 925ms
  Thread calibration: mean lat.: 2558.132ms, rate sampling interval: 8085ms
  Thread calibration: mean lat.: 702.388ms, rate sampling interval: 2783ms
  Thread calibration: mean lat.: 816.795ms, rate sampling interval: 2519ms
  Thread calibration: mean lat.: 764.788ms, rate sampling interval: 3227ms

-----------------------------------------------------------------------
Test Results @ http://10.103.140.24:80/ 
  Thread Stats   Avg      Stdev     99%   +/- Stdev
    Latency     2.84s     1.10s    5.45s    68.21%
    Req/Sec    10.27      2.68    18.00     84.09%
  Latency Distribution (HdrHistogram - Recorded Latency)
 50.000%    2.94s 
 75.000%    3.53s 
 90.000%    4.19s 
 99.000%    5.45s 
 99.900%    5.91s 
 99.990%    5.92s 
 99.999%    5.92s 
100.000%    5.92s 

  Detailed Percentile spectrum:
       Value   Percentile   TotalCount 1/(1-Percentile)

      11.679     0.000000            1         1.00
    1307.647     0.100000          279         1.11
    1973.247     0.200000          557         1.25
    2338.815     0.300000          835         1.43
    2654.207     0.400000         1113         1.67
    2938.879     0.500000         1393         2.00
    3092.479     0.550000         1531         2.22
    3219.455     0.600000         1670         2.50
    3332.095     0.650000         1808         2.86
    3420.159     0.700000         1948         3.33
    3532.799     0.750000         2087         4.00
    3608.575     0.775000         2156         4.44
    3692.543     0.800000         2227         5.00
    3815.423     0.825000         2295         5.71
    3938.303     0.850000         2364         6.67
    4093.951     0.875000         2434         8.00
    4151.295     0.887500         2469         8.89
    4188.159     0.900000         2505        10.00
    4247.551     0.912500         2539        11.43
    4325.375     0.925000         2575        13.33
    4395.007     0.937500         2609        16.00
    4444.159     0.943750         2625        17.78
    4489.215     0.950000         2644        20.00
    4526.079     0.956250         2661        22.86
    4567.039     0.962500         2677        26.67
    4636.671     0.968750         2696        32.00
    4681.727     0.971875         2703        35.56
    4767.743     0.975000         2712        40.00
    4939.775     0.978125         2721        45.71
    5152.767     0.981250         2729        53.33
    5283.839     0.984375         2738        64.00
    5337.087     0.985938         2742        71.11
    5402.623     0.987500         2747        80.00
    5439.487     0.989062         2752        91.43
    5455.871     0.990625         2755       106.67
    5484.543     0.992188         2760       128.00
    5492.735     0.992969         2762       142.22
    5517.311     0.993750         2764       160.00
    5623.807     0.994531         2766       182.86
    5754.879     0.995313         2768       213.33
    5824.511     0.996094         2771       256.00
    5832.703     0.996484         2772       284.44
    5857.279     0.996875         2773       320.00
    5861.375     0.997266         2774       365.71
    5869.567     0.997656         2775       426.67
    5890.047     0.998047         2777       512.00
    5890.047     0.998242         2777       568.89
    5890.047     0.998437         2777       640.00
    5906.431     0.998633         2778       731.43
    5906.431     0.998828         2778       853.33
    5914.623     0.999023         2780      1024.00
    5914.623     0.999121         2780      1137.78
    5914.623     0.999219         2780      1280.00
    5914.623     0.999316         2780      1462.86
    5914.623     0.999414         2780      1706.67
    5914.623     0.999512         2780      2048.00
    5914.623     0.999561         2780      2275.56
    5914.623     0.999609         2780      2560.00
    5922.815     0.999658         2781      2925.71
    5922.815     1.000000         2781          inf
#[Mean    =     2839.972, StdDeviation   =     1100.148]
#[Max     =     5918.720, Total count    =         2781]
#[Buckets =           27, SubBuckets     =         2048]
-----------------------------------------------------------------------
  8160 requests in 15.17s, 2.24MB read
Requests/sec:    537.85  
Transfer/sec:    151.26KB