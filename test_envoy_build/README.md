# Test Envoy builds here

## Change 1:

###  Change made:
envoy/source/extensions/load_balancing_policies/least_request/least_request_lb.cc
changed `unweightedHostPick()` to the following:
```
HostConstSharedPtr LeastRequestLoadBalancer::unweightedHostPick(const HostVector& hosts_to_use,
                                                                const HostsSource&) {
  HostSharedPtr candidate_host = nullptr;

  candidate_host = unweightedHostPickFullScan(hosts_to_use);

  // switch (selection_method_) {
  // case envoy::extensions::load_balancing_policies::least_request::v3::LeastRequest::FULL_SCAN:
  //   candidate_host = unweightedHostPickFullScan(hosts_to_use);
  //   break;
  // case envoy::extensions::load_balancing_policies::least_request::v3::LeastRequest::N_CHOICES:
  //   candidate_host = unweightedHostPickNChoices(hosts_to_use);
  //   break;
  // default:
  //   IS_ENVOY_BUG("unknown selection method specified for least request load balancer");
  // }

  return candidate_host;
}
```
### Compilation process:

Run the following in the Envoy directory
```
bazel build //:envoy
```
(Compilation took 2940.143s with a 32-core machine on CloudLab)

### Verifying the build works correctly

Exp: Run two instances of generic_app. One with a latency of 100ms, and the other with a latency of 50ms. Send requests to both these replicase every 60ms. There should be an approximately 2:1 split between the two instances in Envoy.

To run the two instances:
```
generic-app/generic_app -l 50 -e app_50ms -p 4444
```
```
generic-app/generic_app -l 100 -e app_100ms -p 4445
```

To run the Envoy build (assuming you're in ./multiparty-lb directory):
```
sudo ../envoy/bazel-bin/source/exe/envoy-static -c /users/twaheed/multiparty-lb/test_envoy_build/config.yaml --concurrency 2 --log-level critical
```

To test whether Envoy is working:
```
curl localhost:10099
```
This should return `Processed at app_50ms w/ latency=50ms` and `Processed at app_100ms w/ latency=100ms` on multiple runs

Now, applying a workload (assuming you're in ./multiparty-lb directory):
```
hit/hit -d 15 -rps 17 -l "test_envoy_build/log" -url "http://127.0.0.1:10099"
```

To check the number of times:
```
echo "app_50ms: $(grep -o "app_50ms" test_envoy_build/log | wc -l)" && echo "app_100ms: $(grep -o "app_100ms" test_envoy_build/log | wc -l)"
```
The output was:
```
app_50ms: 170
app_100ms: 87
```
This means that the split was about 2:1 (1:1.95)

Now, let's rebuild Envoy without the change and see results:
```
app_50ms: 151
app_100ms: 105
```
This means the split was 3:2 (2.88:2)

Clearly, these results are worse.

Let's do some more runs:
With OG Envoy:
```
app_50ms: 188
app_1000ms: 69
---
app_50ms: 189
app_10000ms: 68
---
app_50ms: 183
app_100000ms: 73
```
With Modified Envoy:
```
app_50ms: 243
app_1000ms: 14
---
app_50ms: 255
app_10000ms: 2
---
app_50ms: 256
app_100000ms: 1
```