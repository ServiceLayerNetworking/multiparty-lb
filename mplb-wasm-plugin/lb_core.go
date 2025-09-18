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
func getNextDstEndpoint(dst string, weights []float64, podNodes []int) (int, error) {

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

	} else if LOAD_BALANCING_STRATEGY == "leastrequest" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_rl" ||
		LOAD_BALANCING_STRATEGY == "tmp_nodal_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rl" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" {
		return getNextDstEndpointLeastRequest(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "locality_aware_weighted_random" {
		return getNextDstEndpointLocalityAwareWeightedRandom(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "minimize_diff" {
		return getNextDstEndpointMinimizeDiff(dst, weights)

	} else if LOAD_BALANCING_STRATEGY == "nodal_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "only_nodal_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb" {
		return getNextDstEndpointNodalLeastRequest(dst, podNodes, weights)

	} else {
		return -1, errors.New("Invalid load balancing strategy")

	}
}

func informCCofDroppedReq(dst string) {
	// send a request to the CC to inform it of the dropped request
	// so that it can update its stats
	sendEchoRequestToCC(dst, -1, "DR", -1)
}

func notifyRequestCompletedToLB(dstPod string, latencyMs int64) {

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
		LOAD_BALANCING_STRATEGY == "leastrequest_rl" ||
		LOAD_BALANCING_STRATEGY == "tmp_nodal_leastrequest" {

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
			notifyRequestCompletedToLB(dstPod, latencyMs)
		}

	} else if LOAD_BALANCING_STRATEGY == "nodal_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rl" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" ||
		LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb" ||
		LOAD_BALANCING_STRATEGY == "minimize_diff" ||
		LOAD_BALANCING_STRATEGY == "only_nodal_leastrequest" {

		informReqCompletedToSvcBasedNodalLR(dst, endpointNum, latencyMs)

		// informReqCompletedToNodalLR(dstPod, dst, endpointNum, latencyMs)

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
			notifyRequestCompletedToLB(dstPod, latencyMs)
		}
	}
}

func informReqCompletedToSvcBasedNodalLR(dst string, endpointNum int, latencyMs int64) {
	sendEchoRequestToCC(dst, endpointNum, "--", latencyMs)

	// currTime := getCurrUnixTimeNs()
	// // sleep for 2ms
	// time.Sleep(2 * time.Millisecond)
	// // perform the operation
	// updateOutstandingReqs(dst, endpointNum, "--")
	// timeTaken := getCurrUnixTimeNs() - currTime
	// proxywasm.LogCriticalf("Time taken to update outstanding requests: %dus", timeTaken/1e3)
}

func informReqCompletedToNodalLR(dstPod string, dst string, endpointNum int, latencyMs int64) {
	// get the outstanding loads for all cluster
	outstandingLoads, cas, err := getNodalOutstandingLoad()
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding load for endpoint %s: %v",
			dst, err)
		return
	}

	// get the podnames for dst
	weightsBStr, _, err := proxywasm.GetSharedData(dst)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get podnames for %s: %v", dst, err)
		return
	}
	weightsStr := string(weightsBStr)
	if weightsStr == "nil" {
		proxywasm.LogCriticalf("Nil weights available for %s", dst)
		return
	}
	_, podNodes, err := parseLBWeights(weightsStr)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't parse podnames for %s: %v", dst, err)
		return
	}
	nodeNum := podNodes[endpointNum]
	nodeNumStr := strconv.Itoa(nodeNum)

	// get the cpu consumption per req for the dst
	cpuConsumptionPerReq := getCPUConsumptionPerReq(dst)

	// Decrement the active request count for the selected server
	outstandingLoads[nodeNumStr] -= 1 * cpuConsumptionPerReq

	// set the new outstanding requests
	err = setNodalOutstandingLoad(cas, outstandingLoads)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't set outstanding requests: %v, trying again", err)

		// try again, another thread has changed outstanding requests since
		// we last read them
		notifyRequestCompletedToLB(dstPod, latencyMs)
	}
}
