package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"math/rand"
	"strconv"
	"strings"
	"time"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

// implemntation uses outstandingRequests from functions implemented for
// 	weighted least request (in lb_weighted_least_request.go)

func getNextDstEndpointNodalLeastRequest(
	dst string, podNodes []int, weights []float64) (int, error) {

	outstandingReqs, _, err := getOutstandingRequests(dst, len(weights))
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	// Choose nodes by outstanding CPU work rather than treating every request
	// as equally expensive. Keep this local switch so the request-count behavior
	// remains available for controlled comparisons.
	leastLoad := true
	selectedEndpoint := doNodalLR(dst, outstandingReqs, leastLoad)

	// // Increment the active request count for the selected server
	// (*outstandingReqs)[selectedEndpoint]++
	// // set the new outstanding requests
	// err = setOutstandingReqs(cas, dst, outstandingReqs)
	// if err != nil {
	// 	proxywasm.LogCriticalf("Couldn't set outstanding requests: %v", err)

	// 	// try again, another thread has changed outstanding requests since we
	// 	// 	last read them
	// 	return getNextDstEndpointLeastRequest(dst, weights)
	// }

	// instead of incrementing directly, we will issue a request to the CC t
	// send this to all the LBs
	sendEchoRequestToCC(dst, selectedEndpoint, "++", -1)

	return selectedEndpoint, nil
}

func sendEchoRequestToCC(dst string, selectedEndpoint int, op string, latencyMs int64) {

	dstURL := "echo-server.default.svc.cluster.local"
	port := 5656
	authority := dstURL + ":" + strconv.Itoa(port)
	reqDest := fmt.Sprintf("outbound|%d||%s", port, dstURL)

	timeout := uint32(5000) // 5s

	controllerHeaders := [][2]string{
		{":method", "POST"},
		{":path", "/"},
		{":authority", authority},
	}

	// request body format: <timestamp>|<dst>|<selectedEndpoint>|<op>|<latencyMs>
	// e.g. 1745477992498147000|svc0|0|++|23
	reqBody := fmt.Sprintf(
		"%d|%s|%d|%s|%d", getCurrUnixTimeNs(), dst, selectedEndpoint, op, latencyMs)

	proxywasm.LogCriticalf("Sending echo request to CC: %s", reqBody)

	calloutID, err := proxywasm.DispatchHttpCall(reqDest, controllerHeaders,
		[]byte(reqBody), make([][2]string, 0), timeout, OnEchoServerResponse)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't dispatch http call to echo server: %v", err)
		return
	}

	proxywasm.LogCriticalf("Dispatched http call to echo server: %d", calloutID)
}

func getCurrUnixTimeNs() uint64 {
	// Get current time
	now := time.Now()

	// Convert to Unix time in nanoseconds
	unixNano := now.Unix()*1e9 + int64(now.Nanosecond())

	return uint64(unixNano)
}

func OnEchoServerResponse(numHeaders, bodySize, numTrailers int) {

	defer proxywasm.LogCriticalf("OnEchoServerResponse done")
	proxywasm.LogCriticalf("OnEchoServerResponse entered")

	// check that the request was successful
	hdrs, err := proxywasm.GetHttpCallResponseHeaders()
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get http call response headers for echo server: %v", err)
		return
	}
	status := 200
	for _, hdr := range hdrs {
		if hdr[0] == ":status" {
			status, err = strconv.Atoi(hdr[1])
			if err != nil {
				proxywasm.LogCriticalf("Couldn't parse :status header for echo server: %v", err)
				return
			}
		}
	}
	if status >= 400 {
		proxywasm.LogCriticalf("received ERROR http call response for echo server, status %v body size: %d", hdrs, bodySize)
		return
	}
	if bodySize == 0 {
		proxywasm.LogCriticalf("received empty body for echo server response")
		return
	}

	// // get the response body
	// body, err := proxywasm.GetHttpCallResponseBody(0, bodySize)
	// if err != nil {
	// 	proxywasm.LogCriticalf("Couldn't get http call response body for echo server: %v", err)
	// 	return
	// }

	// processEchoBody(string(body))
}

func processEchoBody(body string, selfSvcName string) {

	// parse the response body
	respBody := strings.TrimSpace(string(body))
	proxywasm.LogCriticalf("Received echo response from CC: %s", respBody)

	// parse the response body
	// format: <timestamp>|<dst>|<selectedEndpoint>|<op>|<latencyMs>
	respParts := strings.Split(respBody, "|")
	if len(respParts) != 5 {
		proxywasm.LogCriticalf("Invalid response body format from echo server: %s", respBody)
		return
	}

	// get the response parts
	timestamp, err := strconv.ParseUint(respParts[0], 10, 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse timestamp from echo server response: %v", err)
		return
	}
	dst := respParts[1]
	selectedEndpoint, err := strconv.Atoi(respParts[2])
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse selectedEndpoint from echo server response: %v", err)
		return
	}
	op := respParts[3]

	// get the current time
	currTime := getCurrUnixTimeNs()

	// calculate the round trip time
	rtt := currTime - timestamp
	proxywasm.LogCriticalf("Round trip time from echo server: %dus", rtt/1e3)

	currTime = getCurrUnixTimeNs()
	// perform the operation
	updateOutstandingReqs(dst, selectedEndpoint, op, selfSvcName)
	timeTaken := getCurrUnixTimeNs() - currTime
	proxywasm.LogCriticalf("Time taken to update outstanding requests: %dus", timeTaken/1e3)
}

func updateOutstandingReqs(dst string, selectedEndpoint int, op string, selfSvcName string) {
	// get the outstanding requests for all endpoints of the dst
	outstandingReqs, cas, err := getOutstandingRequests(dst, selectedEndpoint+1)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v", dst, err)
		return
	}

	if op == "++" {
		proxywasm.LogCriticalf("Incrementing outstanding requests for %s: %v", dst, *outstandingReqs)
		(*outstandingReqs)[selectedEndpoint]++
		// Append timestamp for rate limiter tracking only for this service's incoming requests
		if strings.HasSuffix(selfSvcName, dst) {
			appendRateLimiterTimestamp(time.Now().UnixMilli())
		}
	} else if op == "--" {
		proxywasm.LogCriticalf("Decrementing outstanding requests for %s: %v", dst, *outstandingReqs)
		if (*outstandingReqs)[selectedEndpoint] <= 0 {
			proxywasm.LogCriticalf(
				"ERROR: ATTEMPTING TO DECREMENT <= 0 OUTSTANDING REQS %d: %d",
				selectedEndpoint, (*outstandingReqs)[selectedEndpoint])
		} else {
			(*outstandingReqs)[selectedEndpoint]--
		}
	} else if op == "DR" {
		// information that a request is dropped, do nothing
		proxywasm.LogCriticalf(
			"CC informed us that request has been dropped at %s %d %s",
			dst, selectedEndpoint, op)
	} else {
		proxywasm.LogCriticalf("Invalid operation %s", op)
	}

	// set the new outstanding requests
	err = setOutstandingReqs(cas, dst, outstandingReqs)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't set outstanding requests at updateOutstandingReqs: %v", err)

		// try again, another thread has changed outstanding requests since
		// 	we last read them
		updateOutstandingReqs(dst, selectedEndpoint, op, selfSvcName)
	} else {
		proxywasm.LogCriticalf("Updated outstanding requests for %s: %v", dst, *outstandingReqs)
	}
}

func getTopology() (map[string][]int, error) {
	// fixed topology like:
	// topo := map[string][]int{
	// 	"app1": {1, 2},
	// 	"app2": {2, 3},
	// 	"app3": {3},
	// }
	// essentially a map of svc to list of ordered node IDs where its endpoints are
	// e.g. in the example above, app1 has endpoint 0 (app1-0) on node 1 and endpoint 1 (app1-1) on node 2

	valBytes, _, err := proxywasm.GetSharedData(topoKey())

	if err != nil {
		proxywasm.LogCriticalf("Couldn't get shared data for topo %s: %v", topoKey(), err)
		return nil, err
	}

	topo := make(map[string][]int)
	err = json.Unmarshal(valBytes, &topo)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't unmarshal for topo: %v", err)
		return nil, err
	}

	return topo, nil
}

func doNodalLR(dst string, outstandingReqs *[]int, leastLoad bool) int {

	// get the topology from wasm shared data
	svcNodes, err := getTopology()
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get topology: %v", err)
		// select default endpoint -- 0
		return 0
	}

	svcOutstandingReqs := make(map[string]*[]int)
	for service := range svcNodes {
		if service == dst {
			svcOutstandingReqs[service] = outstandingReqs
			proxywasm.LogCriticalf("[%s:%d] Outstanding requests for svc %s: %v",
				dst, -1, service, *outstandingReqs)
		} else {
			n_endpoints := len(svcNodes[service])
			currSvcOutstandingReqs, _, err := getOutstandingRequests(service, n_endpoints)
			if err != nil {
				proxywasm.LogCriticalf(
					"Couldn't get outstanding requests for endpoint %s: %v",
					service, err)
				return 0
			}
			proxywasm.LogCriticalf("[%s:%d] Outstanding requests for svc %s: %v",
				dst, n_endpoints, service, *currSvcOutstandingReqs)
			svcOutstandingReqs[service] = currSvcOutstandingReqs
		}
	}

	requestWeights := make(map[string]float64, len(svcNodes))
	for service := range svcNodes {
		requestWeights[service] = 1.0
	}

	mode := "requests"
	if leastLoad {
		mode = "load"
		for service := range svcNodes {
			cpuConsumptionPerReq, err := readCPUConsumptionPerReq(service)
			if err != nil {
				// Do not mix CPU-weighted and unit-weighted services in the same
				// node score. During controller startup, fall back consistently to
				// request counts until every service has a valid CPU estimate.
				proxywasm.LogCriticalf(
					"Couldn't use least outstanding load because service %s has no valid CPU-per-request estimate: %v; falling back to request counts",
					service, err)
				mode = "requests-fallback"
				for fallbackService := range requestWeights {
					requestWeights[fallbackService] = 1.0
				}
				break
			}
			requestWeights[service] = cpuConsumptionPerReq
		}
	}

	nodeOutstandingLoads, err := aggregateNodeOutstandingLoads(
		svcNodes, svcOutstandingReqs, requestWeights)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't calculate node outstanding loads for %s: %v", dst, err)
		return 0
	}

	proxywasm.LogCriticalf("[%s] Node outstanding %s: %v", dst, mode, nodeOutstandingLoads)

	dstNodes, ok := svcNodes[dst]
	if !ok || len(dstNodes) == 0 {
		proxywasm.LogCriticalf("No topology endpoints found for destination %s", dst)
		return 0
	}

	dstNodeOutstandingLoads := make([]float64, len(dstNodes))
	for i, nodeID := range dstNodes {
		dstNodeOutstandingLoads[i] = nodeOutstandingLoads[nodeID]
	}

	proxywasm.LogCriticalf("[%s] Dst node outstanding %s: %v", dst, mode, dstNodeOutstandingLoads)

	selectedEndpoint := getNodalLeastLoadedEndpoint(&dstNodeOutstandingLoads)

	proxywasm.LogCriticalf("[%s] Selected endpoint: %d", dst, selectedEndpoint)

	return selectedEndpoint

	// nodeOutstandingReqs[1] = (*svcOutstandingReqs["app1"])[1] + (*svcOutstandingReqs["app3"])[0]
	// nodeOutstandingReqs[2] = (*svcOutstandingReqs["app1"])[0] + (*svcOutstandingReqs["app2"])[1]
	// nodeOutstandingReqs[3] = (*svcOutstandingReqs["app2"])[0]

	// proxywasm.LogCriticalf("[%s] Node outstanding requests: %v", dst, nodeOutstandingReqs)
	// defer proxywasm.LogCriticalf("[%s] Node outstanding requests: %v", dst, nodeOutstandingReqs)

	// selectedEndpoint := 0

	// if dst == "app1" {
	// 	if nodeOutstandingReqs[1] < nodeOutstandingReqs[2] {
	// 		// if or(node 1) < or(node 2), select app1-1
	// 		selectedEndpoint = 1
	// 	} else if nodeOutstandingReqs[2] < nodeOutstandingReqs[1] {
	// 		// if or(node 2) < or(node 1), select app1-2
	// 		selectedEndpoint = 0
	// 	} else {
	// 		// if or(node 1) == or(node 2), select app1-0 or app1-1 randomly
	// 		selectedEndpoint = rand.Intn(2)
	// 	}
	// } else if dst == "app2" {
	// 	if nodeOutstandingReqs[2] < nodeOutstandingReqs[3] {
	// 		// if or(node 2) < or(node 3), select app2-0
	// 		selectedEndpoint = 1
	// 	} else if nodeOutstandingReqs[3] < nodeOutstandingReqs[2] {
	// 		// if or(node 3) < or(node 2), select app2-1
	// 		selectedEndpoint = 0
	// 	} else {
	// 		// if or(node 2) == or(node 3), select app2-0 or app2-1 randomly
	// 		selectedEndpoint = rand.Intn(2)
	// 	}
	// } else if dst == "app3" {
	// 	selectedEndpoint = 0
	// } else {
	// 	proxywasm.LogCriticalf("Unknown service %s", dst)
	// }

	// proxywasm.LogCriticalf("[%s] Selected endpoint: %d", dst, selectedEndpoint)

	// return selectedEndpoint
}

// aggregateNodeOutstandingLoads sums outstanding work in one pass over all
// service endpoints. requestWeights contains either 1.0 for request-count mode
// or the service's estimated CPU consumption per request for load mode.
func aggregateNodeOutstandingLoads(
	svcNodes map[string][]int,
	svcOutstandingReqs map[string]*[]int,
	requestWeights map[string]float64) (map[int]float64, error) {

	nodeOutstandingLoads := make(map[int]float64)

	for service, nodes := range svcNodes {
		outstandingReqs, ok := svcOutstandingReqs[service]
		if !ok || outstandingReqs == nil {
			return nil, fmt.Errorf("missing outstanding requests for service %s", service)
		}
		if len(*outstandingReqs) != len(nodes) {
			return nil, fmt.Errorf(
				"service %s has %d outstanding-request entries for %d endpoints",
				service, len(*outstandingReqs), len(nodes))
		}

		requestWeight, ok := requestWeights[service]
		if !ok || requestWeight <= 0 || math.IsNaN(requestWeight) || math.IsInf(requestWeight, 0) {
			return nil, fmt.Errorf("invalid request weight for service %s: %f", service, requestWeight)
		}

		for endpointID, nodeID := range nodes {
			nodeOutstandingLoads[nodeID] += float64((*outstandingReqs)[endpointID]) * requestWeight
		}
	}

	return nodeOutstandingLoads, nil
}

func getNodalLeastLoadedEndpoint(outstandingLoads *[]float64) int {

	var selectedEndpoint int
	minLoad := math.MaxFloat64
	candidates := []int{}

	for endpointNum, outstandingLoad := range *outstandingLoads {
		if outstandingLoad < minLoad {
			minLoad = outstandingLoad
			candidates = []int{endpointNum} // Start a new list of candidates
		} else if outstandingLoad == minLoad {
			candidates = append(candidates, endpointNum) // Add to candidates
		}
	}

	// Randomly select a endpoint from the candidates
	selectedEndpoint = candidates[rand.Intn(len(candidates))]

	return selectedEndpoint
}

func readCPUConsumptionPerReq(dstSvc string) (float64, error) {
	buf, _, err := proxywasm.GetSharedData(svcCPUConsumptionPerReqKey(dstSvc))
	if err != nil {
		return 0, fmt.Errorf("get CPU consumption per request for %s: %w", dstSvc, err)
	}
	cpuConsumption, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		return 0, fmt.Errorf("parse CPU consumption per request for %s: %w", dstSvc, err)
	}
	if cpuConsumption <= 0 || math.IsNaN(cpuConsumption) || math.IsInf(cpuConsumption, 0) {
		return 0, fmt.Errorf("invalid CPU consumption per request for %s: %f", dstSvc, cpuConsumption)
	}

	return cpuConsumption, nil
}

func getCPUConsumptionPerReq(dstSvc string) float64 {
	cpuConsumption, err := readCPUConsumptionPerReq(dstSvc)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get CPU consumption per request for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	return cpuConsumption
}

func getNodalOutstandingLoad() (map[string]float64, uint32, error) {

	// get outstanding load for all nodes in the cluster (so far that we've seen)
	valBytes, cas, err := proxywasm.GetSharedData(outstandingLoadAtNodesKey())

	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get shared data for nodes in cluster: %v", err)

		// initialize outstanding requests
		outstandingLoads := make(map[string]float64)

		// set the initial state
		err = setNodalOutstandingLoad(cas, outstandingLoads)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't initialize outstanding load: %v", err)
		}

		// try again
		return getNodalOutstandingLoad()
	}

	// we have the value, unmarshal it
	outstandingLoads := map[string]float64{}
	err = json.Unmarshal(valBytes, &outstandingLoads)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't unmarshal outstandingLoads: %v", err)
		return nil, 0, err
	}

	return outstandingLoads, cas, nil
}

func setNodalOutstandingLoad(cas uint32, outstandingLoads map[string]float64) error {

	// marshal the outstanding requests
	buf, err := json.Marshal(outstandingLoads)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't marshal outstandingLoads: %v", err)
		panic(err)
	}

	// set the new initial value
	err = proxywasm.SetSharedData(outstandingLoadAtNodesKey(), buf, cas)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set shared data for key %s: %v",
			outstandingLoadAtNodesKey(), err)

		// if cas mismatch, it means some other Envoy thread has set the value,
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			proxywasm.LogCriticalf(
				"CAS Mismatch on OutstandingLoads, failing: %v", err)
		}
	} else {
		proxywasm.LogCriticalf("Set outstanding load for nodes in cluster: %v",
			outstandingLoads)
	}

	return err
}
