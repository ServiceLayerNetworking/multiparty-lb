package main

import (
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
	if sumOutstandingReqs == 0 {
		selectedEndpoint, _ := getNextDstEndpointWeightedRandom(weights)
		return selectedEndpoint
	}

	// calculate the current outstanding req ratios
	outstandingReqsRatios := make([]float64, len(*outstandingReqs))
	for i, reqs := range *outstandingReqs {
		outstandingReqsRatios[i] = (float64(reqs) / float64(sumOutstandingReqs)) * float64(100)
	}

	// calculate the diff
	diff := make([]float64, len(*outstandingReqs))
	for i := range *outstandingReqs {
		diff[i] = outstandingReqsRatios[i] - weights[i]
	}

	// fmt.Printf("\nOutstanding reqs: %v\n", *outstandingReqs)
	// fmt.Printf("Outstanding reqs ratios: %v\n", outstandingReqsRatios)
	// fmt.Printf("Weights: %v\n", weights)
	// fmt.Printf("Diff: %v\n", diff)

	newWeights := make([]float64, len(weights))
	for i := range weights {
		newWeights[i] = weights[i] - diff[i]
		if newWeights[i] < 0 {
			newWeights[i] = 0
		}
	}
	newWeightsSum := 0.0
	for _, w := range newWeights {
		newWeightsSum += w
	}
	for i := range newWeights {
		newWeights[i] = (newWeights[i] / newWeightsSum) * 100
	}

	// fmt.Printf("New weights: %v\n", newWeights)

	selectedEndpoint, _ := getNextDstEndpointWeightedRandom(newWeights)

	return selectedEndpoint

	// // get the min diff
	// minDiff := diff[0]
	// endpointsWithMinDiff := []int{0}
	// selectedEndpoint := 0
	// for i := 1; i < len(diff); i++ {
	// 	if diff[i] < minDiff {
	// 		minDiff = diff[i]
	// 		endpointsWithMinDiff = []int{i}
	// 		selectedEndpoint = i
	// 	} else if diff[i] == minDiff {
	// 		endpointsWithMinDiff = append(endpointsWithMinDiff, i)
	// 	}
	// }

	// // if there are multiple endpoints with the same min diff, select one randomly
	// if len(endpointsWithMinDiff) > 1 {
	// 	selectedEndpoint = endpointsWithMinDiff[rand.Intn(len(endpointsWithMinDiff))]
	// }

	// // // if there are multiple endpoints with the same min diff, select one through their original weights randomly
	// // if len(endpointsWithMinDiff) > 1 {
	// // 	newWeights := make([]float64, len(endpointsWithMinDiff))
	// // 	for i, endpoint := range endpointsWithMinDiff {
	// // 		newWeights[i] = weights[endpoint]
	// // 	}
	// // 	sum := 0.0
	// // 	for _, w := range newWeights {
	// // 		sum += w
	// // 	}
	// // 	for i := range newWeights {
	// // 		newWeights[i] = (newWeights[i] / sum) * 100
	// // 	}

	// // 	randWeightBasedSelection, _ := getNextDstEndpointWeightedRandom(newWeights)

	// // 	selectedEndpoint = endpointsWithMinDiff[randWeightBasedSelection]
	// // }

	// return selectedEndpoint
}
