package main

import (
	"encoding/json"
	"errors"
	"math"
	"math/rand"
	"strconv"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

// implemntation uses outstandingRequests from functions implemented for
// 	weighted least request (in lb_weighted_least_request.go)

func getNextDstEndpointNodalLeastRequest(
	dst string, podNodes []int) (int, error) {

	outstandingLoads, cas, err := getNodalOutstandingLoad()
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding load for endpoint %s: %v",
			dst, err)
		return -1, err
	}

	// get the outstanding loads for the dst pod nodes
	outstandingNodalLoadsForEndpoints := make([]float64, len(podNodes))
	for i, node := range podNodes {
		nodeStr := strconv.Itoa(node)
		outstandingNodalLoadsForEndpoints[i] = outstandingLoads[nodeStr]
	}

	// perform JSQ
	selectedEndpoint := getNodalLeastLoadedEndpoint(&outstandingNodalLoadsForEndpoints)
	selectedNode := podNodes[selectedEndpoint]

	// get the cpu consumption per req for the dst
	cpuConsumptionPerReq := getCPUConsumptionPerReq(dst)

	// Increment the active request count for the selected server
	selectedNodeStr := strconv.Itoa(selectedNode)
	outstandingLoads[selectedNodeStr] += 1 * cpuConsumptionPerReq

	// set the new outstanding requests
	err = setNodalOutstandingLoad(cas, outstandingLoads)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set outstanding requests: %v", err)

		// try again, another thread has changed outstanding requests since we
		// 	last read them
		return getNextDstEndpointNodalLeastRequest(dst, podNodes)
	}

	return selectedEndpoint, nil
}

func getCPUConsumptionPerReq(dstSvc string) float64 {
	buf, _, err := proxywasm.GetSharedData(svcCPUConsumptionPerReqKey(dstSvc))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get CPU consumption per request for %s: %v", dstSvc, err)
		return math.MaxInt
	}
	cpuConsumption, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse CPU consumption per request for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	return cpuConsumption
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
