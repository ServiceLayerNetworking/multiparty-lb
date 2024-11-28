package main

import (
	"encoding/json"
	"errors"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

type WeightedRoundRobin struct {
	Weights        []int `json:"weights"`         // Weights of each endpoint
	CurrentIndex   int   `json:"current_index"`   // The index of the last selected endpoint
	CurrentWeight  int   `json:"current_weight"`  // The current running weight
	GCDWeight      int   `json:"gcd_weight"`      // GCD of all weights (helps with the step size in round-robin)
	MaxWeight      int   `json:"max_weight"`      // Maximum weight among all endpoints
	TotalEndpoints int   `json:"total_endpoints"` // Total number of endpoints
}

// Helper function to find the greatest common divisor (GCD)
func gcd(a, b int) int {
	for b != 0 {
		a, b = b, a%b
	}
	return a
}

// Helper function to find GCD of a slice of numbers
func gcdSlice(weights []int) int {
	if len(weights) == 0 {
		return 1
	}
	g := weights[0]
	for _, w := range weights[1:] {
		g = gcd(g, w)
		if g == 1 {
			break
		}
	}
	return g
}

func getInitialWRRStats(weights []float64) *WeightedRoundRobin {
	weightsInt := make([]int, len(weights))
	for i, w := range weights {
		weightsInt[i] = int(w)
	}

	wrr := &WeightedRoundRobin{
		Weights:        weightsInt,
		CurrentIndex:   -1,
		CurrentWeight:  0,
		GCDWeight:      gcdSlice(weightsInt),
		MaxWeight:      maxIntArray(weightsInt),
		TotalEndpoints: len(weightsInt),
	}
	return wrr
}

// Function that sets a value for the WeightedRoundRobin obj only if the input cas matches
func setWeightedRoundRobinStats(
	cas uint32, dst string, wrr *WeightedRoundRobin) error {

	// get new WeightedRoundRobin stats
	buf, err := json.Marshal(wrr)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't marshal WeightedRoundRobin: %v", err)
		panic(err)
	}

	// set the new initial value
	err = proxywasm.SetSharedData(weightedRoundRobinStatsKey(dst), buf, cas)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set shared data for key %s: %v",
			weightedRoundRobinStatsKey(dst), err)

		// if cas mismatch, it means some other Envoy thread has set the value,
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			proxywasm.LogCriticalf(
				"CAS Mismatch on WeightedRoundRobin, failing: %v", err)
		}
	}

	return err
}
func areWeightsEqual(a []float64, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i, v := range a {
		if int(v) != b[i] {
			return false
		}
	}
	return true
}
func getWeightedRoundRobinStats(
	dst string, weights []float64) (*WeightedRoundRobin, uint32, error) {

	val, cas, err := proxywasm.GetSharedData(weightedRoundRobinStatsKey(dst))

	if err != nil {
		// this means it has not been initialized yet
		proxywasm.LogCriticalf("Couldn't get shared data for key %s: %v",
			weightedRoundRobinStatsKey(dst), err)

		// initialize the WeightedRoundRobin Stats
		proxywasm.LogCriticalf("Initializing WeightedRoundRobin for %s", dst)
		err = setWeightedRoundRobinStats(cas, dst, getInitialWRRStats(weights))
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't initialize WeightedRoundRobin: %v", err)
		}

		// restart function to get the updated value
		return getWeightedRoundRobinStats(dst, weights)
	}

	wrr := &WeightedRoundRobin{}
	err = json.Unmarshal(val, wrr)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't unmarshal WeightedRoundRobin: %v", err)
		return nil, 0, err
	}

	// if weights have changed, reinitialize the WeightedRoundRobin
	if !areWeightsEqual(weights, wrr.Weights) {

		// reinitialize the WeightedRoundRobin Stats
		proxywasm.LogCriticalf("Reinitializing WeightedRoundRobin for %s", dst)
		err = setWeightedRoundRobinStats(cas, dst, getInitialWRRStats(weights))
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't initialize WeightedRoundRobin: %v", err)
		}

		// restart function to get the updated value
		return getWeightedRoundRobinStats(dst, weights)
	}

	return wrr, cas, nil
}

func getNextDstEndpointWeightedRoundRobin(
	dst string, weights []float64) (int, error) {

	// return -1, errors.New("Not implemented")

	wrr, cas, err := getWeightedRoundRobinStats(dst, weights)
	if err != nil {
		return -1, errors.New("Couldn't get WeightedRoundRobin stats")
	}

	var selectedEndpoint int

	for {
		wrr.CurrentIndex = (wrr.CurrentIndex + 1) % wrr.TotalEndpoints
		if wrr.CurrentIndex == 0 {
			wrr.CurrentWeight -= wrr.GCDWeight
			if wrr.CurrentWeight <= 0 {
				wrr.CurrentWeight = wrr.MaxWeight
				if wrr.CurrentWeight == 0 {
					return -1, errors.New(
						"invalid weights: all weights are zero")
				}
			}
		}

		if wrr.Weights[wrr.CurrentIndex] >= wrr.CurrentWeight {
			selectedEndpoint = wrr.CurrentIndex
			break
		}
	}

	// set the new WeightedRoundRobin Stats
	err = setWeightedRoundRobinStats(cas, dst, wrr)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set WeightedRoundRobin stats: %v", err)

		// try again, another thread has changed wrr stats since we last read
		// 	them
		return getNextDstEndpointWeightedRoundRobin(dst, weights)
	}

	return selectedEndpoint, nil
}
