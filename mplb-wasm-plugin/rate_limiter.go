package main

import (
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
)

const CPU_DEMAND_VS_ALLOCATED_TOLERANCE = 5.0

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
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rl" ||
		LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" ||
		LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb") {
		// if the load balancing strategy is not cluster-based, don't do rate limiting
		return false, nil
	}

	if (LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" || LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb") &&
		USE_CONCURRENT_CONNECTIONS_IN_RATE_LIMITER {
		// if we are using performance based rate liming and concurrent connections in rate limit

		toDrop, err := shouldDropRequestConcurrencyBased(dstSvc)
		return toDrop, err

	} else {

		var toReturn bool
		var maxRPSAllowed int
		if LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" ||
			LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb" {
			maxRPSAllowed = getPerfBasedAllowedRPS(dstSvc)
		} else {
			maxRPSAllowed = getMaxRPSGivenTheCPUAllocated(dstSvc)
		}

		// Count timestamps within the enforcement interval (read-only, no modification)
		numReqInPastInterval := getRecentlySentRequestTimeStampsReadOnly(currentTimeMs)

		maxReqInPastIntervalAllowed := int(math.Ceil(float64(maxRPSAllowed) * (float64(RATE_LIMITER_ENFORCEMENT_INTERVAL_MS) / 1000.0)))
		// maxReqInPastIntervalAllowed := maxRPSAllowed * (RATE_LIMITER_ENFORCEMENT_INTERVAL_MS / 1000)
		// maxReqInPastIntervalAllowed := (maxRPSAllowed*RATE_LIMITER_ENFORCEMENT_INTERVAL_MS + 999) / 1000
		if numReqInPastInterval >= maxReqInPastIntervalAllowed {
			proxywasm.LogCriticalf(
				"Rate limiting request to %s: %d requests in the last %d interval [%d {%d} allowed]", dstSvc, numReqInPastInterval, RATE_LIMITER_ENFORCEMENT_INTERVAL_MS, maxReqInPastIntervalAllowed, maxRPSAllowed)
			toReturn = true
		} else {
			proxywasm.LogCriticalf(
				"Not rate limiting request to %s: %d requests in the last %d interval [%d {%d} allowed]", dstSvc, numReqInPastInterval, RATE_LIMITER_ENFORCEMENT_INTERVAL_MS, maxReqInPastIntervalAllowed, maxRPSAllowed)
			toReturn = false
		}

		return toReturn, nil
	}
}

func shouldDropRequestConcurrencyBased(dstSvc string) (bool, error) {

	// get the current number of concurrent connections to the service
	outstandingReqs, _, err := getOutstandingRequests(dstSvc, -1)
	if err != nil {
		proxywasm.LogCriticalf(
			"Couldn't get outstanding requests for endpoint %s: %v",
			dstSvc, err)
		return false, err
	}

	requestsInFight := 0
	for _, numOutstandingReqs := range *outstandingReqs {
		requestsInFight += numOutstandingReqs
	}

	maxConcurrentRequestsAllowed := getAllowedConcurrencyLimit(dstSvc)

	if requestsInFight >= maxConcurrentRequestsAllowed {
		proxywasm.LogCriticalf(
			"Rate limiting request to %s: %d concurrent requests in flight [%d allowed]", dstSvc, requestsInFight, maxConcurrentRequestsAllowed)
		return true, nil
	}

	return false, nil
}

func getAllowedConcurrencyLimit(dstSvc string) int {

	if USE_DEFAULT_MAX_RPS_ALLOWED {
		return DEFAULT_MAX_RPS_ALLOWED
	}

	// get the perf based allowed RPS for the service
	// if it can't be found, return infinity

	buf, _, err := proxywasm.GetSharedData(svcPerfBasedAllowedRPSKey(dstSvc))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get perf based allowed RPS for %s: %v", dstSvc, err)
		return math.MaxInt
	}
	rpsAllowed, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse perf based allowed RPS for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	return int(rpsAllowed)
}

func getPerfBasedAllowedRPS(dstSvc string) int {

	if USE_DEFAULT_MAX_RPS_ALLOWED {
		return DEFAULT_MAX_RPS_ALLOWED
	}

	// get the perf based allowed RPS for the service
	// if it can't be found, return infinity

	buf, _, err := proxywasm.GetSharedData(svcPerfBasedAllowedRPSKey(dstSvc))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get perf based allowed RPS for %s: %v", dstSvc, err)
		return math.MaxInt
	}
	rpsAllowed, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse perf based allowed RPS for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	return int(rpsAllowed+RATE_LIMITER_NUM_OF_REQ_ALLOWED_OVER_CPU_ALLOCATED) / NUM_OF_LB_REPLICAS
}

func getMaxRPSGivenTheCPUAllocated(dstSvc string) int {

	if USE_DEFAULT_MAX_RPS_ALLOWED {
		// TEMP:
		if dstSvc == "svc0" {
			proxywasm.LogCriticalf("Using default max RPS allowed for %s", dstSvc)
			return 200
		} else if dstSvc == "svc1" {
			proxywasm.LogCriticalf("Using default max RPS allowed for %s", dstSvc)
			return 18
		} else {
			return DEFAULT_MAX_RPS_ALLOWED
		}
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

	buf, _, err = proxywasm.GetSharedData(svcCPUDemandKey(dstSvc))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get CPU Demand for %s: %v", dstSvc, err)
		return math.MaxInt
	}
	cpuDemand, err := strconv.ParseFloat(string(buf), 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse CPU Demand for %s: %v", dstSvc, err)
		return math.MaxInt
	}

	if cpuConsumption == -1.0 {
		proxywasm.LogCriticalf("CPU consumption per request not set for %s", dstSvc)
		return math.MaxInt
	}

	// if cpuAllocated >= cpuDemand, don't do rate limiting
	if cpuAllocated > cpuDemand || math.Abs(cpuDemand-cpuAllocated) <= CPU_DEMAND_VS_ALLOCATED_TOLERANCE {
		proxywasm.LogCriticalf("CPU demand (%f) >= CPU allocated (%f) for %s, not rate limiting", cpuDemand, cpuAllocated, dstSvc)
		return math.MaxInt
	}

	return (int(cpuAllocated/cpuConsumption) + RATE_LIMITER_NUM_OF_REQ_ALLOWED_OVER_CPU_ALLOCATED) / NUM_OF_LB_REPLICAS
}

// getRecentlySentRequestTimeStampsReadOnly returns the count of timestamps within the enforcement interval
// Format: "\n<ts1>\n<ts2>\n<ts3>..."
func getRecentlySentRequestTimeStampsReadOnly(currentTimeMs int64) int {
	val, _, err := proxywasm.GetSharedData(RATE_LIMITER_TIMESTAMPS_QUEUE)
	if err != nil {
		return 0
	}

	// Trim null bytes from initialization
	dataStr := strings.TrimLeft(string(val), "\x00")
	if dataStr == "" {
		return 0
	}

	// Count timestamps within the enforcement interval
	count := 0
	lines := strings.Split(dataStr, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		ts, err := strconv.ParseInt(line, 10, 64)
		if err != nil {
			continue
		}
		if ts >= currentTimeMs-RATE_LIMITER_ENFORCEMENT_INTERVAL_MS {
			count++
		}
	}

	return count
}

// appendRateLimiterTimestamp appends a timestamp to the rate limiter list with CAS retry
// Format: "\n<timestamp>"
func appendRateLimiterTimestamp(timestampMs int64) {
	tsStr := fmt.Sprintf("\n%d", timestampMs)

	for {
		data, cas, err := proxywasm.GetSharedData(RATE_LIMITER_TIMESTAMPS_QUEUE)
		if err != nil {
			// Key doesn't exist, initialize with empty
			data = make([]byte, 0)
			cas = 0
		}

		newData := append(data, []byte(tsStr)...)

		err = proxywasm.SetSharedData(RATE_LIMITER_TIMESTAMPS_QUEUE, newData, cas)
		if err != nil {
			if errors.Is(err, types.ErrorStatusCasMismatch) {
				continue
			}
			proxywasm.LogCriticalf("Couldn't append rate limiter timestamp: %v", err)
			return
		}
		return
	}
}

// cleanupRateLimiterTimestamps removes old timestamps (called from OnTick)
func cleanupRateLimiterTimestamps(currentTimeMs int64) {
	for {
		val, cas, err := proxywasm.GetSharedData(RATE_LIMITER_TIMESTAMPS_QUEUE)
		if err != nil {
			return
		}

		// Trim null bytes from initialization
		dataStr := strings.TrimLeft(string(val), "\x00")
		if dataStr == "" {
			return
		}

		// Keep only timestamps within the enforcement interval
		var kept []string
		lines := strings.Split(dataStr, "\n")
		for _, line := range lines {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			ts, err := strconv.ParseInt(line, 10, 64)
			if err != nil {
				continue
			}
			if ts >= currentTimeMs-RATE_LIMITER_ENFORCEMENT_INTERVAL_MS {
				kept = append(kept, line)
			}
		}

		// If nothing was removed, no need to update
		if len(kept) == len(lines)-1 { // -1 for potential leading empty string from split
			return
		}

		var newData []byte
		if len(kept) > 0 {
			newData = []byte("\n" + strings.Join(kept, "\n"))
		} else {
			newData = make([]byte, 0)
		}

		err = proxywasm.SetSharedData(RATE_LIMITER_TIMESTAMPS_QUEUE, newData, cas)
		if err != nil {
			if errors.Is(err, types.ErrorStatusCasMismatch) {
				continue
			}
			proxywasm.LogCriticalf("Couldn't cleanup rate limiter timestamps: %v", err)
			return
		}
		return
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
