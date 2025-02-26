package main

import (
	"errors"
	"strconv"
	"strings"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
)

/*
MPLB

This function implements the load balancing strategy used to select the next
endpoint to send the request to.
WARNING: This func can only be called in OnHttpRequestHeaders.

dst: the destination service name.
weights: a list of weights for each endpoint of the dst.

	The sum of the weights should be 100.
	Example: [50, 50] means 50% of the requests will go to the first endpoint
		and 50% to the second.
*/
func getNextDstEndpoint(dst string, weights []float64) (int, error) {

	// proxywasm.LogCriticalf("MPLB: getNextDstEndpoint called for %s with %v", dst, weights)

	// // for debgging:
	// if dst == "app1" {
	// 	weights = []float64{50, 50}
	// 	proxywasm.LogCriticalf("Setting Fixed Weights for %s: %v", dst, weights)
	// } else if dst == "app2" {
	// 	weights = []float64{10, 90}
	// 	proxywasm.LogCriticalf("Setting Fixed Weights for %s: %v", dst, weights)
	// } else if dst == "app3" {
	// 	weights = []float64{100}
	// 	proxywasm.LogCriticalf("Setting Fixed Weights for %s: %v", dst, weights)
	// } else {
	// 	weights = []float64{10, 90}
	// 	proxywasm.LogCriticalf("Wth is this dst: %s", dst)
	// 	proxywasm.LogCriticalf("Setting Fixed Weights anyways %s: %v", dst, weights)
	// }

	if len(weights) == 0 {
		return -1, errors.New("No weights provided")
	}

	if LOAD_BALANCING_STRATEGY == "weighted_random" {
		return getNextDstEndpointWeightedRandom(weights)

	} else if LOAD_BALANCING_STRATEGY == "weighted_roundrobin" {
		return getNextDstEndpointWeightedRoundRobin(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "weighted_leastrequest" {
		return getNextDstEndpointWeightedLeastRequest(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "leastrequest" {
		return getNextDstEndpointLeastRequest(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "locality_aware_weighted_random" {
		return getNextDstEndpointLocalityAwareWeightedRandom(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "minimize_diff" {
		return getNextDstEndpointMinimizeDiff(dst, weights)

	} else {
		return -1, errors.New("Invalid load balancing strategy")

	}
}

func notifyRequestCompletedToLB(dstPod string) {

	parts := strings.Split(dstPod, "-")
	endpointNumStr := parts[len(parts)-1]
	endpointNum, err := strconv.Atoi(endpointNumStr)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse endpoint number from %s: %v",
			dstPod, err)
		return
	}
	dst := strings.Join(parts[:len(parts)-1], "-")

	if LOAD_BALANCING_STRATEGY == "weighted_random" {
	} else if LOAD_BALANCING_STRATEGY == "weighted_roundrobin" {
	} else if LOAD_BALANCING_STRATEGY == "weighted_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "leastrequest" ||
		LOAD_BALANCING_STRATEGY == "minimize_diff" {

		// get the outstanding requests for all endpoints of the dst
		outstandingReqs, cas, err := getOutstandingRequests(dst, -1)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't get outstanding requests for endpoint %s: %v", dst, err)
			return
		}

		// decrement the active request count for the selected server
		if (*outstandingReqs)[endpointNum] > 0 {
			(*outstandingReqs)[endpointNum]--
		}

		// set the new outstanding requests
		err = setOutstandingReqs(cas, dst, outstandingReqs)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't set outstanding requests at notifyRequestCompletedToLB: %v", err)

			// try again, another thread has changed outstanding requests since
			// 	we last read them
			notifyRequestCompletedToLB(dstPod)
		}

	} else if LOAD_BALANCING_STRATEGY == "locality_aware_weighted_random" {

		// get the outstanding requests for all endpoints of the dst
		stats, cas, err := getLocalityAwareStats(dst, -1)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't get laStats for endpoint %s: %v", dst, err)
			return
		}

		// decrement the active request count for the selected server
		if stats.outstandingReqsAtEndpoint[endpointNum] > 0 {
			stats.outstandingReqsAtEndpoint[endpointNum]--
		}

		// set the new laStats
		err = setLocalityAwareStats(cas, dst, stats)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't set lastats at notifyRequestCompletedToLB: %v", err)

			// try again, another thread has changed laStats since
			// 	we last read them
			notifyRequestCompletedToLB(dstPod)
		}
	}
}
