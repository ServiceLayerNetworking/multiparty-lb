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
