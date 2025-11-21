package main

import (
	"fmt"
	"math"
	"sort"
	"time"
)

/*
Demand Estimator class logic

We essentially want to determine how much CPUUtil per unit time does a request for each service in our cluster requires.

On every telemetry update to the central controller from update state. State should contain
- Timestamps of requests processed by each service
- CPU Utilizations and their calculation timestamps of each service
- Time of the telemetry update
- Keep this information upto 5 minutes in the past (5 minutes to 5 minutes + ~700ms to be precise)

*/

type CPUUtilState struct {
	EndTime int64
	CpuUtil float64
}

type DemandEstimator struct {
	CPUUtilizationTimestamps map[string][]CPUUtilState
	ProcessedReqTimestamps   map[string][]int64
	HeadRoomPct              map[string]float64
	PerfBasedAllowedRPS      map[string]float64
	PerfBasedAllowedRPSPct   map[string]float64
	Counter                  int
}

func (de *DemandEstimator) Initialize() {
	// Initialize the DemandEstimator
	de.CPUUtilizationTimestamps = make(map[string][]CPUUtilState)
	de.ProcessedReqTimestamps = make(map[string][]int64)
	de.HeadRoomPct = make(map[string]float64)
	de.PerfBasedAllowedRPS = make(map[string]float64)
	de.PerfBasedAllowedRPSPct = make(map[string]float64)
	de.Counter = -1
}

func (de *DemandEstimator) UpdateState(
	appUtils map[string]float64,
	reqStats []ReqStat) {

	currUnixTimeMs := time.Now().UnixMilli()

	// Add the current telemetry to the state
	for svcName, util := range appUtils {
		if _, ok := de.CPUUtilizationTimestamps[svcName]; !ok {
			de.CPUUtilizationTimestamps[svcName] = make([]CPUUtilState, 0)
		}
		de.CPUUtilizationTimestamps[svcName] = append(
			de.CPUUtilizationTimestamps[svcName], CPUUtilState{
				EndTime: currUnixTimeMs,
				CpuUtil: util * SVC_UTIL_SCALE_FACTOR,
			})
	}

	// Sorting req stats in ascending order based on endtimems
	sort.Slice(reqStats, func(i, j int) bool {
		return reqStats[i].EndTimeMs < reqStats[j].EndTimeMs
	})

	// appending all the processed requests to the state
	for _, reqStat := range reqStats {
		// if ".mplb.com" is in the service name, we need to remove it
		// the service name should be like "svc0", "svc1", etc.
		// but it comes as "svc0.mplb.com"
		// so we need to remove the ".mplb.com" part very efficiently
		// check if the last 9 characters are ".mplb.com"
		if len(reqStat.DstSvc) > 9 && reqStat.DstSvc[len(reqStat.DstSvc)-9:] == ".mplb.com" {
			reqStat.DstSvc = reqStat.DstSvc[:len(reqStat.DstSvc)-9]
		}

		if _, ok := de.ProcessedReqTimestamps[reqStat.DstSvc]; !ok {
			de.ProcessedReqTimestamps[reqStat.DstSvc] = make([]int64, 0)
		}
		de.ProcessedReqTimestamps[reqStat.DstSvc] = append(
			de.ProcessedReqTimestamps[reqStat.DstSvc], reqStat.EndTimeMs)
	}
	// fmt.Printf("ProcessedReqTimestamps: %v\n", de.ProcessedReqTimestamps)

	// Remove the telemetry older than 5 minutes

	earlistCPUTimeStampMs := currUnixTimeMs

	// first remove the cpu intervals older than 5 minutes
	for svcName, cpuUtilStates := range de.CPUUtilizationTimestamps {
		for len(cpuUtilStates) > 0 && currUnixTimeMs-cpuUtilStates[0].EndTime > (5*60*1000) {
			cpuUtilStates = cpuUtilStates[1:]
		}
		de.CPUUtilizationTimestamps[svcName] = cpuUtilStates
		earlistCPUTimeStampMs = min(earlistCPUTimeStampMs, cpuUtilStates[0].EndTime)
	}

	// then remove the processed requests older than the last CPU timestamp-700ms
	for svcName, reqTimestamps := range de.ProcessedReqTimestamps {
		if len(reqTimestamps) == 0 {
			continue
		}
		truncateIndex := len(reqTimestamps)
		// sort the timestamps in ascending order
		sort.Slice(reqTimestamps, func(i, j int) bool {
			return reqTimestamps[i] < reqTimestamps[j]
		})
		for i, reqTimestamp := range reqTimestamps {
			if reqTimestamp >= earlistCPUTimeStampMs-700 {
				truncateIndex = i
				break
			}
		}
		de.ProcessedReqTimestamps[svcName] = de.ProcessedReqTimestamps[svcName][truncateIndex:]
	}

}

func (de *DemandEstimator) GetDemandEstimates(
	reqStatsServer *ReqStatsServer) (map[string]float64, map[string]float64) {

	// Get the demand estimates for each service
	cpuConsumptionsPerReq := make(map[string]float64)
	perfBasedAllowedRPS := make(map[string]float64)

	for svcName := range de.CPUUtilizationTimestamps {

		// sum up the cpu utilizations and multiply by the time
		// time is the difference between the first and (last-700ms) cpu utilization timestamp
		// multiply the sum by the time to get the cpu consumption

		cpuUtilStates := de.CPUUtilizationTimestamps[svcName]

		sumCPUUtil := 0.0
		for _, cpuUtilState := range cpuUtilStates {
			sumCPUUtil += cpuUtilState.CpuUtil
		}

		// THIS IS BUGGY
		timeTakenMs := int64(700)
		if len(cpuUtilStates) > 1 {
			timeTakenMs += cpuUtilStates[len(cpuUtilStates)-1].EndTime - cpuUtilStates[0].EndTime
		}

		timeTakenSec := (float64(timeTakenMs) / 1000.0) / float64(len(cpuUtilStates))

		cpuConsumption := sumCPUUtil * timeTakenSec
		// cpu consumption is in percentag of core seconds

		// now get the number of requests processed in the last timeTakenMs
		numReqs := len(de.ProcessedReqTimestamps[svcName])

		// // get the number of requests in the service outstanding and add
		// svcOutstandingReqs.mu.Lock()
		// outstandingReqs := svcOutstandingReqs.numOutstandingReq[svcName]
		// svcOutstandingReqs.mu.Unlock()

		cpuConsumptionPerReq := cpuConsumption / float64(numReqs)
		cpuConsumptionCoreSecPerReq := cpuConsumptionPerReq / 100.0
		cpuConsumptionCoreMsPerReq := cpuConsumptionCoreSecPerReq * 1000.0

		fmt.Println("CPU Consumption per req for service", svcName, "is", cpuConsumptionCoreMsPerReq, "coreMs with", numReqs, "requests completed")
		if (numReqs) == 0 {
			cpuConsumptionPerReq = CPU_CONSUMPTION_PER_REQ
		}
		if USE_OFFLINE_DEMAND_ESTIMATE {
			if svcName == "svc0" {
				cpuConsumptionPerReq = CPU_CONSUMPTION_PER_REQ
			} else if svcName == "svc1" {
				cpuConsumptionPerReq = CPU_CONSUMPTION_PER_REQ
			} else {
				cpuConsumptionPerReq = CPU_CONSUMPTION_PER_REQ
			}
		}

		cpuConsumptionsPerReq[svcName] = cpuConsumptionPerReq * CPU_PER_REQ_SCALE_FACTOR

		// add in the headroom
		headroomPct, svcPerfBasedAllowedRPS := de.getHeadRoomPctAndPerfBasedAllowedRPS(svcName, reqStatsServer)
		cpuConsumptionsPerReq[svcName] += cpuConsumptionsPerReq[svcName] * (headroomPct / 100.0)

		// add the allowed rps
		perfBasedAllowedRPS[svcName] = svcPerfBasedAllowedRPS

	}

	return cpuConsumptionsPerReq, perfBasedAllowedRPS
}

func (de *DemandEstimator) getHeadRoomPctAndPerfBasedAllowedRPS(
	svcName string,
	reqStatsServer *ReqStatsServer) (float64, float64) {

	latencyMeanMs := float64(reqStatsServer.serviceLatencyStats.GetMean(svcName))
	targetMeanMs := 140.0
	isPerformanceIdeal := latencyMeanMs < targetMeanMs
	errFromTarget := latencyMeanMs - targetMeanMs

	// calculate headroom pct
	headroomPct, ok := de.HeadRoomPct[svcName]
	if !ok {
		headroomPct = 10.0
	}

	if isPerformanceIdeal {
		headroomPct -= 5.0
	} else {
		headroomPct += 5.0
	}
	headroomPct = clampFloat(headroomPct, 0.0, 50.0)

	de.HeadRoomPct[svcName] = headroomPct

	// -------------------------------------------------------------------------

	if USE_CONCURENT_CONNECTIONS_FOR_RATE_LIMITER {

		// Netflix Gradient algorithm from
		// Note: This is how the algorithm below is different from the implementation in Netflix code:
		// 	(i) rttTolerance multiplier is not used to adjust the rttNoLoad
		// 	(ii) in netflix, they use backoffRatio to reduce the allowed rif when there is a request drop
		// 	(iii) in netflix do not grow the allowed rif when the current rif < half of the previous allowed rif
		//  (iv) Netflix has a new algorithm version of the algorithm now too
		// 			called Gradient2: https://github.com/Netflix/concurrency-limits/blob/main/concurrency-limits-core/src/main/java/com/netflix/concurrency/limits/limit/Gradient2Limit.java
		//			where they attempt to address bias and drift when using
		// 			minimum latency measurements. To do this the algorithm
		// 			tracks uses the measure of divergence between two exponential
		// 			averages over a long and short time time window. Using averages
		// 			the algorithm can smooth out the impact of outliers for bursty
		// 			traffic. Divergence duration is used as a proxy to identify a
		// 			queueing trend at which point the algorithm aggresively reduces
		// 			the limit. We acheive this instead by taking the mean over an interval
		//			instead of the per request rtt observed.

		INIT_ALLOWED_RIF := 5.0
		MIN_ALLOWED_RIF := 1.0
		MAX_ALLOWED_RIF := 50.0

		// calculate perf based allowed rps
		// if no rps cap, initialize it to the current arriving rps
		currentLimit, ok := de.PerfBasedAllowedRPSPct[svcName]
		if !ok {
			de.PerfBasedAllowedRPSPct[svcName] = INIT_ALLOWED_RIF
		} else {
			gradient := targetMeanMs / latencyMeanMs
			gradient = clampFloat(gradient, 0.5, 1.0)

			queueSize := math.Sqrt(currentLimit)

			newLimit := currentLimit*gradient + queueSize

			newLimit = clampFloat(newLimit, MIN_ALLOWED_RIF, MAX_ALLOWED_RIF)

			de.PerfBasedAllowedRPS[svcName] = newLimit
		}

	} else {

		MIN_ALLOWED_RPS := 5.0
		MAX_ALLOWED_RPS := 1000.0

		// calculate perf based allowed rps
		// if no rps cap, initialize it to the current arriving rps
		rpsCap, ok := de.PerfBasedAllowedRPS[svcName]
		if !ok {
			rpsCap = MAX_ALLOWED_RPS
		}

		if errFromTarget > 0 {

			if rpsCap == MAX_ALLOWED_RPS {
				currentRPS := reqStatsServer.serviceArrivingRPS.GetRPS(svcName)
				rpsCap = currentRPS
			}

			rpsCap *= 1.0 - (5.0 / 100.0)

			// rpsCap = maxFloat(MIN_ALLOWED_RPS, rpsCap*(1.0-clampFloat(absFloat(errFromTarget)/targetLatency95pMs, 0.01, 0.50)))
		} else {

			rpsCap += 5.0

			// rpsCap = minFloat(MAX_ALLOWED_RPS, rpsCap*(1.0+clampFloat(absFloat(errFromTarget)/targetLatency95pMs, 0.01, 0.20)))
		}

		rpsCap = clampFloat(rpsCap, MIN_ALLOWED_RPS, MAX_ALLOWED_RPS)

		de.PerfBasedAllowedRPS[svcName] = rpsCap

	}

	return de.HeadRoomPct[svcName], de.PerfBasedAllowedRPS[svcName]
}

func clampFloat(val, minVal, maxVal float64) float64 {
	if val < minVal {
		return minVal
	}
	if val > maxVal {
		return maxVal
	}
	return val
}

func absFloat(val float64) float64 {
	if val < 0 {
		return -val
	}
	return val
}

func minFloat(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}

func maxFloat(a, b float64) float64 {
	if a > b {
		return a
	}
	return b
}
