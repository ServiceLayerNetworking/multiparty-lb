package main

import (
	"encoding/json"
	"errors"
	"math"
	"strconv"
	"time"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

// called in OnHttpRequestHeaders
func shouldDropRequest(currentTimeMs int64, dstSvc string) (bool, error) {

	// if LOAD_BALANCING_STRATEGY is not cluster-based i.e. minimize_diff or nodal_request,
	// don't do rate limiting and return false

	// get recently sent request timestamp list

	// start from beginning of the list
	// until we find a timestamp that is greater than or equal to currentTime - 1
	// remove all timestamps before that
	// get length of the list
	// if length is greater than or equal to MAX_RPS_GIVEN_THE_CPU_ALLOCATED
	// to_return = true
	// else
	// add currentTime to the list
	// to_return = false

	// set the list back
	// if list can't be set back, return error
	// if the error is CASMismatch, call shouldDropRequest again with updated currTime

	if !(LOAD_BALANCING_STRATEGY == "minimize_diff" ||
		LOAD_BALANCING_STRATEGY == "nodal_leastrequest" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_rl" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rl") {
		return false, nil
	}

	recentlySentReqTimestamps, cas := getRecentlySentRequestTimeStamps(dstSvc)

	// remove timestamps that are older than 1 second
	truncatingIndex := len(recentlySentReqTimestamps)
	for i, ts := range recentlySentReqTimestamps {
		if ts >= currentTimeMs-1000 {
			truncatingIndex = i
			break
		}
	}
	recentlySentReqTimestamps = recentlySentReqTimestamps[truncatingIndex:]

	numReqInPastSec := len(recentlySentReqTimestamps)

	var toReturn bool
	if numReqInPastSec >= getMaxRPSGivenTheCPUAllocated(dstSvc) {
		proxywasm.LogCriticalf(
			"Rate limiting request to %s: %d requests in the last second", dstSvc, numReqInPastSec)

		toReturn = true
	} else {
		recentlySentReqTimestamps = append(recentlySentReqTimestamps, currentTimeMs)
		toReturn = false
	}

	err := setRecentlySentRequestTimeStamps(cas, dstSvc, recentlySentReqTimestamps)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't set recently sent requests: %v", err)
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			// try again, another thread has changed the list since we last read it
			return shouldDropRequest(time.Now().UnixMilli(), dstSvc)
		}
		return false, err
	}

	return toReturn, nil
}

func getMaxRPSGivenTheCPUAllocated(dstSvc string) int {

	if USE_DEFAULT_MAX_RPS_ALLOWED {
		return DEFAULT_MAX_RPS_ALLOWED
	}

	// get the CPU allocated to the service (CPU weight of the service)
	// get the CPU consumed per request for the service
	// then return max requests in a second allowed = CPUAllocated for the past sec / CPUConsumedPerRequest
	// if any of these are not set, return infinity

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

	buf, _, err = proxywasm.GetSharedData(svcCPUAllocatedKey(dstSvc))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get CPU allocated for %s: %v", dstSvc, err)
		return math.MaxInt
	}
	cpuAllocated, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse CPU allocated for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	if cpuConsumption == -1.0 {
		proxywasm.LogCriticalf("CPU consumption per request not set for %s", dstSvc)
		return math.MaxInt
	}

	return int(cpuAllocated/cpuConsumption) + RATE_LIMITER_NUM_OF_REQ_ALLOWED_OVER_CPU_ALLOCATED
}

func getRecentlySentRequestTimeStamps(dstSvc string) ([]int64, uint32) {
	// get the list
	// if it doesn't exist, create it
	// if it can't be created, return error
	// return the list

	val, cas, err := proxywasm.GetSharedData(recentlySentRequestsKey(dstSvc))
	if err != nil {

		// initialize the list
		proxywasm.LogCriticalf("Initializing recently sent requests list for %s", dstSvc)
		err = setRecentlySentRequestTimeStamps(cas, dstSvc, []int64{})
		if err != nil {
			// this could be CASMismatch or some other error, in any case, we have to retry
			proxywasm.LogCriticalf(
				"Couldn't initialize recently sent requests list: %v", err)
		}

		// restart function to get the updated value
		return getRecentlySentRequestTimeStamps(dstSvc)
	}

	var timestamps []int64
	err = json.Unmarshal(val, &timestamps)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't unmarshal timestamps: %v", err)
		panic(err)
	}

	return timestamps, cas
}

func setRecentlySentRequestTimeStamps(cas uint32, dstSvc string, timestamps []int64) error {
	// marshal the list
	// set the list
	// if it can't be set, return error
	// if the error is CASMismatch, call setRecentlySentRequestTimeStamps again with updated cas

	buf, err := json.Marshal(timestamps)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't marshal timestamps: %v", err)
		panic(err)
	}

	err = proxywasm.SetSharedData(recentlySentRequestsKey(dstSvc), buf, cas)
	return err
}

func recentlySentRequestsKey(dstSvc string) string {
	return "rs-req-" + dstSvc
}
