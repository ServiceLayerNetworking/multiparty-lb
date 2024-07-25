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
istio-configs/istio
```
k apply -Rf istio-configs/hotelReservation.yaml
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
```
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

error_count=0; for i in {1..25}; do echo "Running attempt $i..."; curl http://$CLUSTER_IP:$INGRESS_PORT/recommendations\?require\=rate\&lat\=37.804\&lon\=-122.099 || ((error_count++)); done; echo "The command failed $error_count times out of 25."


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
