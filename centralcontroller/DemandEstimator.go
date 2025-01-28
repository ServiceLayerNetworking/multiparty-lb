package main

import (
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
}

func (de *DemandEstimator) Initialize() {
	// Initialize the DemandEstimator
	de.CPUUtilizationTimestamps = make(map[string][]CPUUtilState)
	de.ProcessedReqTimestamps = make(map[string][]int64)
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
				CpuUtil: util,
			})
	}

	// Sorting req stats in ascending order based on endtimems
	sort.Slice(reqStats, func(i, j int) bool {
		return reqStats[i].EndTimeMs < reqStats[j].EndTimeMs
	})

	// appending all the processed requests to the state
	for _, reqStat := range reqStats {
		if _, ok := de.ProcessedReqTimestamps[reqStat.DstSvc]; !ok {
			de.ProcessedReqTimestamps[reqStat.DstSvc] = make([]int64, 0)
		}
		de.ProcessedReqTimestamps[reqStat.DstSvc] = append(
			de.ProcessedReqTimestamps[reqStat.DstSvc], reqStat.EndTimeMs)
	}

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
		for i, reqTimestamp := range reqTimestamps {
			if reqTimestamp >= earlistCPUTimeStampMs-700 {
				truncateIndex = i
				break
			}
		}
		de.ProcessedReqTimestamps[svcName] = de.ProcessedReqTimestamps[svcName][truncateIndex:]
	}

}

func (de *DemandEstimator) GetDemandEstimates() map[string]float64 {

	// Get the demand estimates for each service
	cpuConsumptionsPerReq := make(map[string]float64)

	for svcName, _ := range de.CPUUtilizationTimestamps {

		// sum up the cpu utilizations and multiply by the time
		// time is the difference between the first and (last-700ms) cpu utilization timestamp
		// multiply the sum by the time to get the cpu consumption

		cpuUtilStates := de.CPUUtilizationTimestamps[svcName]

		sumCPUUtil := 0.0
		for _, cpuUtilState := range cpuUtilStates {
			sumCPUUtil += cpuUtilState.CpuUtil
		}

		timeTakenMs := int64(700)
		if len(cpuUtilStates) > 1 {
			timeTakenMs += cpuUtilStates[len(cpuUtilStates)-1].EndTime - cpuUtilStates[0].EndTime
		}

		timeTakenSec := float64(timeTakenMs) / 1000.0

		cpuConsumption := sumCPUUtil * timeTakenSec

		// now get the number of requests processed in the last timeTakenMs
		numReqs := len(de.ProcessedReqTimestamps[svcName])

		cpuConsumptionPerReq := cpuConsumption / float64(numReqs)

		cpuConsumptionsPerReq[svcName] = cpuConsumptionPerReq
	}

	return cpuConsumptionsPerReq
}
