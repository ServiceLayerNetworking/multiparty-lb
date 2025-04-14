package main

import (
	"math"
	"math/rand"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
)

// implemntation uses outstandingRequests from functions implemented for
// 	weighted least request (in lb_weighted_least_request.go)

func getNextDstEndpointLeastRequest(
	dst string, weights []float64) (int, error) {

	outstandingReqs, cas, err := getOutstandingRequests(dst, len(weights))
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	// perform least request
	selectedEndpoint := doLR(outstandingReqs)

	if LOAD_BALANCING_STRATEGY == "tmp_nodal_leastrequest" {
		selectedEndpoint = doNodalLeastRequestWithFixedTopo(dst, outstandingReqs)
	}

	if LOAD_BALANCING_STRATEGY == "leastrequest" {
		// Increment the active request count for the selected server
		(*outstandingReqs)[selectedEndpoint]++

		// set the new outstanding requests
		err = setOutstandingReqs(cas, dst, outstandingReqs)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't set outstanding requests: %v", err)

			// try again, another thread has changed outstanding requests since we
			// 	last read them
			return getNextDstEndpointLeastRequest(dst, weights)
		}
	} else {
		// if the load balancing strategy is leastrequest_plus, we will
		// instead of incrementing directly, we will issue a request to the CC t
		// send this to all the LBs
		sendEchoRequestToCC(dst, selectedEndpoint, "++")
	}

	return selectedEndpoint, nil
}

func doLR(outstandingReqs *[]int) int {

	var selectedEndpoint int
	minLoad := math.MaxFloat64
	candidates := []int{}

	for endpointNum, outstandingReqs := range *outstandingReqs {
		effectiveLoad := float64(outstandingReqs) * 1.0
		if effectiveLoad < minLoad {
			minLoad = effectiveLoad
			candidates = []int{endpointNum} // Start a new list of candidates
		} else if effectiveLoad == minLoad {
			candidates = append(candidates, endpointNum) // Add to candidates
		}
	}

	// Randomly select a endpoint from the candidates
	selectedEndpoint = candidates[rand.Intn(len(candidates))]

	return selectedEndpoint
}

func doNodalLeastRequestWithFixedTopo(dst string, outstandingReqs *[]int) int {

	// fixed topology:
	svcNodes := map[string][]int{
		"app1": {2, 1},
		"app2": {2, 3},
		"app3": {3},
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
			proxywasm.LogCriticalf("[%s:%d] Outstanding requests for svc %s: %v",
				dst, n_endpoints, service, *currSvcOutstandingReqs)
			if err != nil {
				proxywasm.LogCriticalf(
					"Couldn't get outstanding requests for endpoint %s: %v",
					dst, err)
				return 0
			}
			svcOutstandingReqs[service] = currSvcOutstandingReqs
		}
	}

	nodeOutstandingReqs := make(map[int]int)
	nodeOutstandingReqs[1] = (*svcOutstandingReqs["app1"])[0] + (*svcOutstandingReqs["app3"])[0]
	nodeOutstandingReqs[2] = (*svcOutstandingReqs["app1"])[1] + (*svcOutstandingReqs["app2"])[0]
	nodeOutstandingReqs[3] = (*svcOutstandingReqs["app2"])[1]

	proxywasm.LogCriticalf("[%s] Node outstanding requests: %v", dst, nodeOutstandingReqs)
	defer proxywasm.LogCriticalf("[%s] Node outstanding requests: %v", dst, nodeOutstandingReqs)

	selectedEndpoint := 0

	if dst == "app1" {
		if nodeOutstandingReqs[1] < nodeOutstandingReqs[2] {
			// if or(node 1) < or(node 2), select app1-1
			selectedEndpoint = 0
		} else if nodeOutstandingReqs[2] < nodeOutstandingReqs[1] {
			// if or(node 2) < or(node 1), select app1-2
			selectedEndpoint = 1
		} else {
			// if or(node 1) == or(node 2), select app1-0 or app1-1 randomly
			selectedEndpoint = rand.Intn(2)
		}
	} else if dst == "app2" {
		if nodeOutstandingReqs[2] < nodeOutstandingReqs[3] {
			// if or(node 2) < or(node 3), select app2-0
			selectedEndpoint = 0
		} else if nodeOutstandingReqs[3] < nodeOutstandingReqs[2] {
			// if or(node 3) < or(node 2), select app2-1
			selectedEndpoint = 1
		} else {
			// if or(node 2) == or(node 3), select app2-0 or app2-1 randomly
			selectedEndpoint = rand.Intn(2)
		}
	} else if dst == "app3" {
		selectedEndpoint = 0
	} else {
		proxywasm.LogCriticalf("Unknown service %s", dst)
	}

	proxywasm.LogCriticalf("[%s] Selected endpoint: %d", dst, selectedEndpoint)

	return selectedEndpoint
}
