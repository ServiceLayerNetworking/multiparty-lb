package main

import "github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"

type LocalityAwareStats struct {
	outstandingReqsAtEndpoint []int
	outstandingReqHistory     []int
}

func getNextDstEndpointLocalityAwareWeightedRandom(dst string, weights []float64) (int, error) {

	stats, cas, err := getLocalityAwareStats(dst, len(weights))
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get locality aware stats for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	selectedEndpoint := -1

	if shouldFailOverToLeastRequest(stats) {
		selectedEndpoint = doLR(&stats.outstandingReqsAtEndpoint)
	} else {
		selectedEndpoint, err = getNextDstEndpointWeightedRandom(weights)
		if err != nil {
			proxywasm.LogCriticalf("err from weighted random: %v", err)
			return -1, err
		}
	}

	// Increment the active request count for the selected server
	stats.outstandingReqsAtEndpoint[selectedEndpoint]++

	// Set new outstanding req history
	stats.outstandingReqHistory = getNewHistory(
		stats.outstandingReqsAtEndpoint, stats.outstandingReqHistory)

	// set the new outstanding requests
	err = setLocalityAwareStats(cas, dst, stats)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get locality aware stats for endpoint %s: %v",
			dst, err)

		// try again, another thread has changed stats since we
		// 	last read them
		return getNextDstEndpointLocalityAwareWeightedRandom(dst, weights)
	}

	return selectedEndpoint, nil
}
