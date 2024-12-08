package main

import (
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

const (
	// number of history to keep atm
	LOCALITY_AWARE_HISTORY_SIZE = 5
)

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

func shouldFailOverToLeastRequest(stats LocalityAwareStats) bool {

	// if history is not full, don't failover
	// get curr sum of outstanding requests
	// if the curr sum is less than the oldest entry in history,
	// 	use MPLB (don't failover), else failover to least request

	// proxywasm.LogCriticalf("Using MPLB weighted random")

	if len(stats.outstandingReqHistory) < LOCALITY_AWARE_HISTORY_SIZE {
		proxywasm.LogCriticalf("Using MPLB as history is not full")
		return false
	}

	currSum := 0
	for _, or := range stats.outstandingReqsAtEndpoint {
		currSum += or
	}

	if currSum < stats.outstandingReqHistory[0] {
		proxywasm.LogCriticalf(
			"Using MPLB as currOR < OR after we added n-%dth request",
			LOCALITY_AWARE_HISTORY_SIZE)
		return false
	}

	proxywasm.LogCriticalf(
		"Using LR as currOR >= OR after we added n-%dth request",
		LOCALITY_AWARE_HISTORY_SIZE)
	return true
}

func getNewHistory(orAtEndpoints, orHistory []int) []int {

	// Algorithm:
	// sum current outstanding requests
	// append this sum of outstanding requests to the history
	// if history size exceeds, remove the oldest entry

	orSum := 0
	for _, or := range orAtEndpoints {
		orSum += or
	}

	orHistory = append(orHistory, orSum)
	if len(orHistory) > LOCALITY_AWARE_HISTORY_SIZE {
		orHistory = orHistory[1:]
	}

	return orHistory
}

func setLocalityAwareStats(
	cas uint32, dst string, stats LocalityAwareStats) error {

	// get new WeightedRoundRobin stats
	statsBytes := []byte(laStatsToString(stats))

	// set the new initial value
	err := proxywasm.SetSharedData(localityAwareStatsKey(dst), statsBytes, cas)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set shared data for key %s: %v",
			localityAwareStatsKey(dst), err)

		// if cas mismatch, it means some other Envoy thread has set the value,
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			proxywasm.LogCriticalf(
				"CAS Mismatch on localityAwareStats, failing: %v", err)
		}
	} else {
		proxywasm.LogCriticalf("Set  LAstats for %s: %v, %v", dst,
			stats.outstandingReqsAtEndpoint, stats.outstandingReqHistory)
	}

	return err
}

func getLocalityAwareStats(
	dst string, numEndpoints int) (LocalityAwareStats, uint32, error) {

	isNumEndpointsValid := numEndpoints > 0

	// get outstanding requests for all endpoints of the dst
	valBytes, cas, err := proxywasm.GetSharedData(localityAwareStatsKey(dst))

	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get shared data for endpoint %s: %v", dst, err)

		// initialize stats
		if !isNumEndpointsValid {
			// we don't know the number of endpoints, so we can't initialize
			return LocalityAwareStats{}, 0,
				errors.New("OR not yet initialized for " + dst)
		}
		// we know the number of endpoints, so we can initialize
		stats := LocalityAwareStats{
			outstandingReqsAtEndpoint: make([]int, numEndpoints),
			outstandingReqHistory:     []int{},
		}
		err = setLocalityAwareStats(cas, dst, stats)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't initialize outstanding requests: %v", err)
		}

		// try again
		return getLocalityAwareStats(dst, numEndpoints)
	}

	stats, err := parseLAStats(string(valBytes))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse lastats: %v", err)
		return LocalityAwareStats{}, 0, err
	}

	proxywasm.LogCriticalf("Got LAstats for %s: %v, %v", dst,
		stats.outstandingReqsAtEndpoint, stats.outstandingReqHistory)

	proxywasm.LogCriticalf("NumEndpoints: %d, isNumEndpointValid %t, len(stats.outstandingReqsAtEndpoint): %d",
		numEndpoints, isNumEndpointsValid, len(stats.outstandingReqsAtEndpoint))

	// if numofEndpoints have increased, add state for new endpoints
	if isNumEndpointsValid &&
		numEndpoints > len(stats.outstandingReqsAtEndpoint) {

		// add state for new endpoints
		proxywasm.LogCriticalf(
			"Adding lastat state for new endpoints of %s", dst)
		stats.outstandingReqsAtEndpoint = append(stats.outstandingReqsAtEndpoint,
			make([]int, numEndpoints-len(stats.outstandingReqsAtEndpoint))...)
		err = setLocalityAwareStats(cas, dst, stats)
		if err != nil {
			proxywasm.LogCriticalf(
				"Couldn't set the new lastats: %v", err)
		}

		// restart function to get the updated value
		return getLocalityAwareStats(dst, numEndpoints)
	}

	return stats, cas, nil
}

func laStatsToString(stats LocalityAwareStats) string {

	// exampleStr: "2,2,4|6,6,7,4,7"

	// make a comma-seperated string of outstandingReqsAtEndpoint
	orStr := ""
	for _, or := range stats.outstandingReqsAtEndpoint {
		orStr += fmt.Sprintf(",%d", or)
	}
	if len(orStr) > 0 {
		orStr = orStr[1:]
	}

	// make a comma-seperated string of outstandingReqHistory
	orhStr := ""
	for _, orh := range stats.outstandingReqHistory {
		orhStr += fmt.Sprintf(",%d", orh)
	}
	if len(orhStr) > 0 {
		orhStr = orhStr[1:]
	}

	return orStr + "|" + orhStr
}

func parseLAStats(valStr string) (LocalityAwareStats, error) {

	// exampleStr: "2,2,4|6,6,7,4,7"

	// split the string into outstandingReqsAtEndpoint and outstandingReqHistory
	parts := strings.Split(valStr, "|")
	if len(parts) != 2 {
		return LocalityAwareStats{}, errors.New("Invalid LAStats format")
	}

	// parse outstandingReqsAtEndpoint
	orStr := parts[0]
	orAtEndpoint := []int{}
	if len(orStr) > 0 {
		orParts := strings.Split(orStr, ",")
		orAtEndpoint = make([]int, len(orParts))
		for i, orStr := range orParts {
			or, err := strconv.Atoi(orStr)
			if err != nil {
				return LocalityAwareStats{}, err
			}
			orAtEndpoint[i] = or
		}
	}

	// parse outstandingReqHistory
	orhStr := parts[1]
	orHistory := []int{}
	if len(orhStr) > 0 {
		orhParts := strings.Split(orhStr, ",")
		orHistory = make([]int, len(orhParts))
		for i, orhStr := range orhParts {
			orh, err := strconv.Atoi(orhStr)
			if err != nil {
				return LocalityAwareStats{}, err
			}
			orHistory[i] = orh
		}
	}

	return LocalityAwareStats{
		outstandingReqsAtEndpoint: orAtEndpoint,
		outstandingReqHistory:     orHistory,
	}, nil
}
