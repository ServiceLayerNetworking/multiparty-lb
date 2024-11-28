# [Istio] Build

## Build Istio Proxy / Envoy

This section is following instructions from [repo issue](https://github.com/istio/istio/issues/36354). You are expected to be working from within the [istio proxy repository](https://github.com/istio/proxy) in the following steps.

<!-- Then inside container, run make build_envoy under /work docker run -u <your-user-id> -it -v $(pwd):/work gcr.io/istio-testing/build-tools-proxy:master-2021-11-22T20-08-26 -- bash -->

Create the build container mounting the current root directory of the proxy to `/work` within the container
```bash
docker run -it -v $(pwd):/work gcr.io/istio-testing/build-tools-proxy:master-latest -- bash
```

Set the override repository arguments 
```bash
export BAZEL_BUILD_ARGS="--override_repository=envoy=/work/envoy"
```

Take a look at the Makefile.core.mk

```bash
make build_envoy
```
> **Note**

> If there's any issue related to `The current user is root, please run as non-root when using the hermetic Python interpreter`, then refer to the steps listed on  [this comment](https://github.com/envoyproxy/envoy/issues/23065#issuecomment-1256659666). Add ` ignore_root_user_error = True, ` to the envoy/bazel/repositories_extra.bzl file.

This will build the envoy binary which will be in the `bazel-out` directory

Then, copy the bazel-out content into `build-output` folder from within the container. Crete the `build-output` folder outside of the container in the same root folder, if it does not exist.

```
cp -Rf bazel-out/k8-opt/* build-output/envoy-with-pqueue/
```

## Build Istio

This section is expecting you make changes within the [istio repository](https://github.com/istio/istio)

First, create the `.istiorc.mk` file in the root of the repository to include the following. Then uncomment reference to `istiorc.mk` in the `Makefile.core.mk` so that it’s included. This will allow for pushing build images to docker hub

```bash
export HUB=docker.io/YOUR_NAME
export TAG=latest
```

then `make docker` will pull all the docker binaries in the `/out/linux_FOO/` folder which will contain envoy. 

> Still need to determine how to download the envoy from the local build or copy the local build envoy here to be used when copying into docker. One idea: rename the sidecar binary pulled from local and copy the local build envoy as envoy_local, but when used in the docker file it will source envoy_local but in the container will be in `/usr/bin/local/envoyyx`


```bash
sudo make docker
```

then

```bash
sudo make build
```

then copy the ENVOY_PATH from the Proxy build step earlier to `out/linux_FOO/release` folder. This release folder is where the envoy binary gets copied from into the `dockerx/…/amd` folder

```bash
sudo cp /home/ubuntu/proxy/build-output/bazel-out-release-with-priority/k8-opt/bin/envoy out/linux_amd64/release/
```

then dockerize

```bash
sudo make docker.proxyv2
sudo make push.docker.proxyv2
```


# [Istio] Install 
This  is on the machine that is running Kubernetes cluster. This can be done using the pre-compiled istio version as well. 

```bash
go run ./istioctl/cmd/istioctl uninstall --purge
go run ./istioctl/cmd/istioctl install --set hub=docker.io/YOUR_NAME  --set tag=latest
```

If you want to set the [concurrency of the proxy](https://www.envoyproxy.io/docs/envoy/latest/operations/cli#cmdoption-concurrency), then use the following command to set the mesh config. Additional context available on [this github post](https://github.com/istio/istio/issues/35751#issuecomment-961490137)

```bash
./istioctl install --set meshConfig.defaultConfig.concurrency=1 --set hub=docker.io/YOUR_NAME  --set tag=latest
```

Add a namespace label to instruct Istio to automatically inject Envoy sidecar proxies when you deploy your application later:

```bash
kubectl label namespace default istio-injection=enabled
```