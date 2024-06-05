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
