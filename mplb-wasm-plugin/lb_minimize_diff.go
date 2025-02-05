package main

import (
	"math/rand"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
)

// implemntation uses outstandingRequests from functions implemented for
// 	weighted least request (in lb_weighted_least_request.go)

func getNextDstEndpointMinimizeDiff(
	dst string, weights []float64) (int, error) {

	outstandingReqs, cas, err := getOutstandingRequests(dst, len(weights))
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	// perform least request
	selectedEndpoint := doMinimizeDiff(outstandingReqs, weights)

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

func doMinimizeDiff(outstandingReqs *[]int, weights []float64) int {

	// Logic:
	// we will assume that all requests which are outstanding are
	// contributing to the utilization, as there is no concurrency bottleneck.
	// Then we assume that the weights are telling us the amount of utilization
	// we want to acheive at each endpoint. We will then calculate the difference
	// between the current utilization ratios among the endpoints (ratios of num
	// of outstanding reqs) and the ratios of weights). We will select the endpoint
	// with the least difference.
	// We are hopeful this will converge to the minimum difference in ratios of
	// utilizations and desired weights

	sumOutstandingReqs := 0
	for _, reqs := range *outstandingReqs {
		sumOutstandingReqs += reqs
	}

	// calculate the current outstanding req ratios
	outstandingReqsRatios := make([]float64, len(*outstandingReqs))
	for i, reqs := range *outstandingReqs {
		outstandingReqsRatios[i] = (float64(reqs) / float64(sumOutstandingReqs)) * float64(100)
	}

	// calculate the diff
	diff := make([]float64, len(*outstandingReqs))
	for i := range *outstandingReqs {
		diff[i] = weights[i] - outstandingReqsRatios[i]
	}

	// get the min diff
	minDiff := diff[0]
	endpointsWithMinDiff := []int{0}
	selectedEndpoint := 0
	for i := 1; i < len(diff); i++ {
		if diff[i] < minDiff {
			minDiff = diff[i]
			endpointsWithMinDiff = []int{i}
			selectedEndpoint = i
		} else if diff[i] == minDiff {
			endpointsWithMinDiff = append(endpointsWithMinDiff, i)
		}
	}

	// if there are multiple endpoints with the same min diff, select one randomly
	if len(endpointsWithMinDiff) > 1 {
		selectedEndpoint = endpointsWithMinDiff[rand.Intn(len(endpointsWithMinDiff))]
	}

	return selectedEndpoint
}
