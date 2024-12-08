package main

import (
	"encoding/json"
	"errors"
	"math"
	"math/rand"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

// Function that sets a value for outstanding requests obj only when obj only if the input cas matches
func setOutstandingReqs(
	cas uint32, dst string, outstandingReqs *[]int) error {

	// get new WeightedRoundRobin stats
	buf, err := json.Marshal(outstandingReqs)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't marshal outstandingReqs: %v", err)
		panic(err)
	}

	// set the new initial value
	err = proxywasm.SetSharedData(outstandingReqsKey(dst), buf, cas)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set shared data for key %s: %v",
			outstandingReqsKey(dst), err)

		// if cas mismatch, it means some other Envoy thread has set the value,
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			proxywasm.LogCriticalf(
				"CAS Mismatch on OutstandingReqs, failing: %v", err)
		}
	} else {
		proxywasm.LogCriticalf("Set outstanding requests for %s: %v", dst,
			*outstandingReqs)
	}

	return err
}

func getOutstandingRequests(
	dst string, numEndpoints int) (*[]int, uint32, error) {

	isNumEndpointsValid := numEndpoints != -1

	// get outstanding requests for all endpoints of the dst
	valBytes, cas, err := proxywasm.GetSharedData(outstandingReqsKey(dst))

	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get shared data for endpoint %s: %v", dst, err)

		// initialize outstanding requests
		if !isNumEndpointsValid {
			// we don't know the number of endpoints, so we can't initialize
			return nil, 0, errors.New("OR not yet initialized for " + dst)
		}
		// we know the number of endpoints, so we can initialize
		outstandingReqs := make([]int, numEndpoints)
		err = setOutstandingReqs(cas, dst, &outstandingReqs)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't initialize outstanding requests: %v", err)
		}

		// try again
		return getOutstandingRequests(dst, numEndpoints)
	}

	outstandingReqs := []int{}
	err = json.Unmarshal(valBytes, &outstandingReqs)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't unmarshal outstandingReqs: %v", err)
		return nil, 0, err
	}

	// if numofEndpoints have increased, add state for new endpoints
	if isNumEndpointsValid && numEndpoints > len(outstandingReqs) {

		// add state for new endpoints
		proxywasm.LogCriticalf(
			"Adding outstanding request state for new endpoints of %s", dst)
		outstandingReqs = append(outstandingReqs,
			make([]int, numEndpoints-len(outstandingReqs))...)
		err = setOutstandingReqs(cas, dst, &outstandingReqs)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't set the new outstanding requests: %v", err)
		}

		// restart function to get the updated value
		return getOutstandingRequests(dst, numEndpoints)
	}

	return &outstandingReqs, cas, nil
}

func getNextDstEndpointWeightedLeastRequest(
	dst string, weights []float64) (int, error) {

	outstandingReqs, cas, err := getOutstandingRequests(dst, len(weights))
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	// perform least request
	selectedEndpoint, outstandingReqs :=
		doEffectiveLoadWLR(weights, outstandingReqs)

	// set the new outstanding requests
	err = setOutstandingReqs(cas, dst, outstandingReqs)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set outstanding requests: %v", err)

		// try again, another thread has changed outstanding requests since we
		// 	last read them
		return getNextDstEndpointWeightedLeastRequest(dst, weights)
	}

	return selectedEndpoint, nil
}

func doEffectiveLoadWLR(
	weights []float64, outstandingReqs *[]int) (int, *[]int) {

	var selectedEndpoint int
	minLoad := math.MaxFloat64
	candidates := []int{}

	for endpointNum, weight := range weights {
		effectiveLoad :=
			float64((*outstandingReqs)[endpointNum]) / (weight / 100.0)
		if effectiveLoad < minLoad {
			minLoad = effectiveLoad
			candidates = []int{endpointNum} // Start a new list of candidates
		} else if effectiveLoad == minLoad {
			candidates = append(candidates, endpointNum) // Add to candidates
		}
	}

	// Randomly select a endpoint from the candidates
	selectedEndpoint = candidates[rand.Intn(len(candidates))]

	// Increment the active request count for the selected server
	(*outstandingReqs)[selectedEndpoint]++

	return selectedEndpoint, outstandingReqs
}
