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