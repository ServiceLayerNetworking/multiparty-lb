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
	HeadRoomFactor           map[string]float64
	PerfBasedAllowedRPS      map[string]float64
	PerfBasedAllowedRPSPct   map[string]float64
	Counter                  int
}

func (de *DemandEstimator) Initialize() {
	// Initialize the DemandEstimator
	de.CPUUtilizationTimestamps = make(map[string][]CPUUtilState)
	de.ProcessedReqTimestamps = make(map[string][]int64)
	de.HeadRoomFactor = make(map[string]float64)
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
	reqStatsServer *ReqStatsServer) (map[string]float64, map[string]float64, map[string]float64) {

	// Get the demand estimates for each service
	cpuConsumptionsPerReq := make(map[string]float64)
	headroomPerReq := make(map[string]float64)
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
			cpuConsumptionPerReq = INIT_CPU_CONSUMPTION_PER_REQ
		}
		if USE_OFFLINE_DEMAND_ESTIMATE {
			if svcName == "svc0" {
				cpuConsumptionPerReq = INIT_CPU_CONSUMPTION_PER_REQ
			} else if svcName == "svc1" {
				cpuConsumptionPerReq = INIT_CPU_CONSUMPTION_PER_REQ
			} else {
				cpuConsumptionPerReq = INIT_CPU_CONSUMPTION_PER_REQ
			}
		}

		cpuConsumptionsPerReq[svcName] = cpuConsumptionPerReq * CPU_PER_REQ_SCALE_FACTOR

		// add in the headroom
		headroomFactor, svcPerfBasedAllowedRPS := de.getHeadRoomPctAndPerfBasedAllowedRPS(svcName, reqStatsServer)
		cpuConsumptionsPerReq[svcName] *= headroomFactor

		headroomPerReq[svcName] = headroomFactor
		fmt.Printf("Headroom factor for service %s is %.2f %%\n", svcName, headroomFactor)

		// add the allowed rps
		perfBasedAllowedRPS[svcName] = svcPerfBasedAllowedRPS

	}

	return cpuConsumptionsPerReq, headroomPerReq, perfBasedAllowedRPS
}

func (de *DemandEstimator) getHeadRoomPctAndPerfBasedAllowedRPS(
	svcName string,
	reqStatsServer *ReqStatsServer) (float64, float64) {

	currLatencyMs := float64(reqStatsServer.serviceLatencyStats.GetMeanUnderPercentile(svcName, 90.0))
	// we are going to use median instead of mean now, because mean is affected by outliers, therefore if one of the
	// endpoints is slow, that reduces the latency for every other endpoint too much.
	// currLatencyMs := float64(reqStatsServer.serviceLatencyStats.GetPercentileLatency(svcName, 50.0))\
	// turns out median is not stable enough, so going back to mean with 90th percentile filter

	// target is 102ms mean latency calculated by 1 node cluster, with one service sending all load equal to the CPU capacity of the node.
	// 		Node CPU cap = 8 cores, CPU consumption per request = 80 coreMs
	targetLatencyMs := 250.0
	// target is 68 ms median with the above setup
	// targetLatencyMs := 68.0

	isPerformanceIdeal := currLatencyMs <= targetLatencyMs

	INIT_HR_FACTOR := 1.10 // +10% headroom
	MIN_HR_FACTOR := 1.00  // allow up to 0% increase
	MAX_HR_FACTOR := 1.50  // allow up to 50% increase

	REDUCE_HR_FACTOR := 0.75

	// calculate headroom pct
	headroomFactor, ok := de.HeadRoomFactor[svcName]
	if !ok {
		headroomFactor = INIT_HR_FACTOR
	}

	// gradient is <= 1.0 if currLatencyMs <= targetLatencyMs,
	// 		i.e. performance is ideal -> should reduce headroom
	//		this can't happen through the gradient because currLatencyMs will
	// 		not fall below targetLatencyMs. Therefore, we need an another explicit
	//		factor to reduce headroom when performance is ideal. We keep this
	//		constant for now as REDUCE_FACTOR = 0.75 because we allow increase
	// 		in headroom factor to be between 1 and 1.5, so we take the middle of
	// 		that range to reduce headroom.
	// gradient is > 1.0 if currLatencyMs > targetLatencyMs,
	// 		i.e. performance is not ideal -> need more headroom
	if isPerformanceIdeal {
		headroomFactor *= REDUCE_HR_FACTOR
	} else {
		gradient := currLatencyMs / targetLatencyMs
		gradient = clampFloat(gradient, 1.0, 1.5)
		headroomFactor *= gradient
	}

	// if isPerformanceIdeal {
	// 	headroomFactor -= 5.0
	// } else {
	// 	headroomFactor += 5.0
	// }
	headroomFactor = clampFloat(headroomFactor, MIN_HR_FACTOR, MAX_HR_FACTOR)

	updatedHeadroomPct := headroomFactor

	de.HeadRoomFactor[svcName] = updatedHeadroomPct

	// -------------------------------------------------------------------------

	updatedPerfBasedCap := 0.0

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

		INIT_ALLOWED_RIF := 50.0
		MIN_ALLOWED_RIF := 1.0
		MAX_ALLOWED_RIF := 500.0

		// calculate perf based allowed rps
		// if no rps cap, initialize it to the current arriving rps
		currentLimit, ok := de.PerfBasedAllowedRPS[svcName]
		if !ok {
			updatedPerfBasedCap = INIT_ALLOWED_RIF
		} else {
			gradient := targetLatencyMs / currLatencyMs
			gradient = clampFloat(gradient, 0.5, 1.0)

			queueSize := math.Sqrt(currentLimit)

			newLimit := currentLimit*gradient + queueSize

			newLimit = clampFloat(newLimit, MIN_ALLOWED_RIF, MAX_ALLOWED_RIF)

			updatedPerfBasedCap = newLimit

		}

	} else {

		INIT_ALLOWED_RPS := 50.0
		MIN_ALLOWED_RPS := 5.0
		MAX_ALLOWED_RPS := 5000.0

		// calculate perf based allowed rps
		// if no rps cap, initialize it to the current arriving rps
		currentLimit, ok := de.PerfBasedAllowedRPS[svcName]
		if !ok {
			updatedPerfBasedCap = INIT_ALLOWED_RPS
		} else {
			gradient := targetLatencyMs / currLatencyMs
			gradient = clampFloat(gradient, 0.5, 1.0)

			queueSize := math.Sqrt(currentLimit)

			newLimit := currentLimit*gradient + queueSize

			newLimit = clampFloat(newLimit, MIN_ALLOWED_RPS, MAX_ALLOWED_RPS)
			updatedPerfBasedCap = newLimit

		}

	}

	de.PerfBasedAllowedRPS[svcName] = updatedPerfBasedCap

	return updatedHeadroomPct, updatedPerfBasedCap
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
