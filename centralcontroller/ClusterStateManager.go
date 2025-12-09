package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

type ClusterStateManager struct {
	Nodes             []Node
	RoundsAppCPUUtils []map[string]float64
}

func (c *ClusterStateManager) Initialize(nodes []Node, appNames []string) {

	setInitialGurobiWeights(nodes, appNames)

	c.RoundsAppCPUUtils = make([]map[string]float64, 0)

	// if USE_RPS_INSTEAD_OF_CPU {
	// change the cap of every node
	// for i := range nodes {
	// 	nodes[i].MilliCores = NODE_RPS_CAP * 10
	// }
	// }
	c.Nodes = nodes
}

func getSvcNamesFromPodCPUUtilizations(nodeCPUUtilizations []string) []string {

	svcNames := make(map[string]struct{})
	for _, cpuUtil := range nodeCPUUtilizations {

		// example cpuUtil to parse: "utils:hostagent-node2-0:1.676123 svc0-1:0.470927 svc1-0:0.453747"

		if cpuUtil[:6] == "utils:" {
			cpuUtil = cpuUtil[6:] // remove "utils:"
		}

		cpuUtilStrs := strings.Split(cpuUtil, " ")
		for _, cpuUtilStr := range cpuUtilStrs {
			util := strings.Split(cpuUtilStr, ":")
			podName := util[0]
			svcName := strings.Split(podName, "-")[0] // get "svc0" from "svc0-1"
			if svcName == "hostagent" {
				continue
			}
			svcNames[svcName] = struct{}{}
		}
	}

	// convert map keys to slice
	svcNamesSlice := make([]string, 0, len(svcNames))
	for svcName := range svcNames {
		svcNamesSlice = append(svcNamesSlice, svcName)
	}

	return svcNamesSlice
}

func (c *ClusterStateManager) GetOptimalLBWeights(
	nodeCPUUtilizations []string,
	reqStatsServer *ReqStatsServer,
	svcCPUConsumptionPerReq map[string]float64,
	svcPerfBasedAllowedRPS map[string]float64) string {

	var gurobiInput map[string]float64

	if USE_RPS_INSTEAD_OF_CPU {

		svcNames := getSvcNamesFromPodCPUUtilizations(nodeCPUUtilizations)
		// currentAppUtils := getPerAppRPS(reqStats)
		currentAppUtils := getPerAppRpsBasedUtil(
			svcNames,
			reqStatsServer,
			svcCPUConsumptionPerReq)

		slog.Info(fmt.Sprintf("Current App Utils: %v\n", currentAppUtils))

		// get weights from gurobi
		gurobiInput = currentAppUtils

	} else {
		currentAppUtils := getPerAppUtilizations(nodeCPUUtilizations)
		slog.Info(fmt.Sprintf("Current App Utils: %v\n", currentAppUtils))

		// effectiveAppUtils := makeNoiseZero(currentAppUtils, NOISE)
		// effectiveAppUtils = addOverhead(effectiveAppUtils, OVERHEAD)

		// get rolling average
		avgAppUtils, newRoundsAppCPUUtils := getRollingAverage(
			currentAppUtils, c.RoundsAppCPUUtils)
		c.RoundsAppCPUUtils = newRoundsAppCPUUtils

		slog.Info(fmt.Sprintf("Rolling App Utils: %v\n", c.RoundsAppCPUUtils))

		// round all app utils to whole numbers
		appUtilsForGurobi := make(map[string]float64)
		for appNum, util := range avgAppUtils {
			appUtilsForGurobi[appNum] = float64(int(util))
		}

		gurobiInput = appUtilsForGurobi
	}

	// get weights from gurobi
	gurobiResponse := getGenericWeightsFromGurobi(c.Nodes, gurobiInput)

	// print Gurobi weights:
	fmt.Printf("Gurobi Response: %s\n", gurobiResponse)

	lbWeights := parseGurobiResponse(
		gurobiResponse,
		svcCPUConsumptionPerReq,
		svcPerfBasedAllowedRPS,
		c.Nodes)
	return lbWeights

	// return "profile:0.0|100.0 frontend:0.0|100.0 recommendation:100.0",
	// 	newRoundsAppCPUUtils

}

func getPerAppRpsBasedUtil(
	svcNames []string,
	reqStatsServer *ReqStatsServer,
	svcCPUConsumptionPerReq map[string]float64) map[string]float64 {

	serviceOutstandingReqs := reqStatsServer.serviceOutstandingRequests
	serviceArrivingRPS := reqStatsServer.serviceArrivingRPS

	// get the number of requests outstanding
	serviceOutstandingReqs.mu.Lock()

	// get the RPS for each service
	svcRPSBasedUtil := make(map[string]float64)
	for _, svc := range svcNames {

		oustandingRequests := serviceOutstandingReqs.numOutstandingReq[svc]

		// svcRPS := float64(sentReqs) / (float64(RPS_WINDOW_MS) / 1000.0)
		svcRPS := serviceArrivingRPS.GetRPS(svc)
		svcRPSBasedUtil[svc] = svcRPS * svcCPUConsumptionPerReq[svc] // * SVC_UTIL_SCALE_FACTOR

		fmt.Printf("svcRPSBasedUtil |||||| %s: %f rps %d ots-req %f%% util\n",
			svc, svcRPS, oustandingRequests, svcRPSBasedUtil[svc])
	}

	serviceOutstandingReqs.mu.Unlock()

	// svcRPSBasedUtil["svc0"] = 300.0 * 0.8
	// svcRPSBasedUtil["svc1"] = 200.0 * 0.8

	return svcRPSBasedUtil
}

func getPerAppRPS(reqStats []ReqStat) map[string]float64 {

	// get the max endtimems from all reqStats
	var maxEndTimeMs int64 = 0
	for _, reqStat := range reqStats {
		if reqStat.EndTimeMs > maxEndTimeMs {
			maxEndTimeMs = reqStat.EndTimeMs
		}
	}

	// get the number of requests completed in the last RPS_WINDOW_MS
	svcComletedReqs := make(map[string]int)
	for _, reqStat := range reqStats {
		if maxEndTimeMs-reqStat.EndTimeMs <= RPS_WINDOW_MS {
			// remove .mplb.com from the dstSvc
			dstSvc := strings.ReplaceAll(reqStat.DstSvc, ".mplb.com", "")
			svcComletedReqs[dstSvc]++
		}
	}

	// get the RPS for each service
	svcRPS := make(map[string]float64)
	for svc, completedReqs := range svcComletedReqs {
		svcRPS[svc] = float64(completedReqs) / (float64(RPS_WINDOW_MS) / 1000.0)
	}

	return svcRPS
}

func getPerAppUtilizations(nodeCPUUtilizations []string) map[string]float64 {

	appUtils := make(map[string]float64)
	for _, cpuUtil := range nodeCPUUtilizations {

		// example cpuUtil to parse: "utils:hostagent-node2-0:1.676123 svc0-1:0.470927 svc1-0:0.453747"

		if cpuUtil[:6] == "utils:" {
			cpuUtil = cpuUtil[6:] // remove "utils:"
		}

		cpuUtilStrs := strings.Split(cpuUtil, " ")
		for _, cpuUtilStr := range cpuUtilStrs {

			util := strings.Split(cpuUtilStr, ":")
			appName := util[0]

			// don't consider hostagents for gurobi calculations
			if strings.Contains(appName, "hostagent") {
				continue
			}

			// get "app1-node1" from "app1-0"
			pattern := `^(.+)-\d+$`
			// Compile the regex
			re := regexp.MustCompile(pattern)
			// Find the first match
			match := re.FindStringSubmatch(util[0])

			if len(match) > 1 {
				// match[0] is the full match, match[1] is the first capturing group
				appName = match[1]
			}

			podUtil, err := strconv.ParseFloat(util[1], 64)
			check(err)

			appUtils[appName] += podUtil
		}

	}

	slog.Info(fmt.Sprintf("nodeCPUUtilizations: %v\n", nodeCPUUtilizations))
	slog.Info(fmt.Sprintf("App Utils: %v\n", appUtils))

	return appUtils
}

func getRollingAverage(
	currentAppUtils map[string]float64,
	roundsAppCPUUtils []map[string]float64) (map[string]float64, []map[string]float64) {

	// update rounds
	newRoundsAppCPUUtils := append(roundsAppCPUUtils, currentAppUtils)
	if len(newRoundsAppCPUUtils) > ROUNDS_FOR_ROLLING_AVG_OF_CPU_UTILS {
		newRoundsAppCPUUtils = newRoundsAppCPUUtils[1:]
	}

	// get avg utils
	avgAppUtils := make(map[string]float64)
	for _, appUtils := range newRoundsAppCPUUtils {
		for appNum, util := range appUtils {
			avgAppUtils[appNum] += util
		}
	}
	for appNum := range avgAppUtils {
		avgAppUtils[appNum] /= float64(len(newRoundsAppCPUUtils))
	}

	return avgAppUtils, newRoundsAppCPUUtils
}

func getGenericWeightsFromGurobi(
	nodes []Node, appUtils map[string]float64) string {

	startTime := time.Now()
	defer func() {
		elapsed := time.Since(startTime)
		fmt.Printf("Time taken to get weights from Gurobi: %d us\n", elapsed.Microseconds())
	}()

	if USE_HARDCODE_GUROBI_RESPONSE {

		response := `{"status": 2, "result": {"svc1": {"svc1-0": 0.0, "svc1-1": 200.0}, "svc9": {"svc9-0": 0.0, "svc9-1": 200.0}, "svc2": {"svc2-0": 0.0, "svc2-1": 200.0}, "svc4": {"svc4-0": 0.0, "svc4-1": 200.0}, "svc5": {"svc5-0": 0.0, "svc5-1": 200.0}, "svc7": {"svc7-0": 0.0, "svc7-1": 200.0}, "svc0": {"svc0-0": 200.0}, "svc10": {"svc10-0": 0.0, "svc10-1": 200.0}, "svc8": {"svc8-0": 0.0, "svc8-1": 200.0}, "svc3": {"svc3-0": 0.0, "svc3-1": 200.0}, "svc6": {"svc6-0": 0.0, "svc6-1": 200.0}, "svc11": {"svc11-0": 0.0, "svc11-1": 200.0}, "svc12": {"svc12-0": 0.0, "svc12-1": 200.0}, "svc13": {"svc13-0": 0.0, "svc13-1": 200.0}, "svc14": {"svc14-0": 0.0, "svc14-1": 200.0}}}`

		fmt.Printf("Using hardcoded Gurobi response: %s\n", response)

		return response
	}

	hosts := make([]HostJSON, 0)
	for _, node := range nodes {
		// // TEMPORARY: don't consider nodes 0, 4, 5
		// if strings.Contains(node.Name, "node0") ||
		// 	strings.Contains(node.Name, "node4") ||
		// 	strings.Contains(node.Name, "node5") {
		// 	continue
		// }
		hosts = append(hosts, HostJSON{
			Name: node.Name,
			Cap:  float64(node.MilliCores) / 10.0,
		})
	}
	hostsJSON, err := json.Marshal(hosts)
	check(err)

	tenants := make([]TenantJSON, 0)
	for appName, util := range appUtils {
		// don't consider hostagents for gurobi calculations
		if strings.Contains(appName, "hostagent") {
			continue
		}

		// Get fair share load
		fshare := getFShareLoad(nodes, appName)

		// Skip or replace infinity/NaN values
		if math.IsInf(util, 0) || math.IsNaN(util) {
			fmt.Printf("Warning: Invalid util for %s: %f, setting to 0.0\n", appName, util)
			util = 0.0
		}
		if math.IsInf(fshare, 0) || math.IsNaN(fshare) {
			fmt.Printf("Warning: Invalid fshare for %s: %f, setting to 1.0\n", appName, fshare)
			fshare = 1.0
		}

		tenants = append(tenants, TenantJSON{
			Name:       appName,
			Load:       util,
			FShareLoad: fshare,
		})
	}
	tenantsJSON, err := json.Marshal(tenants)
	if err != nil {
		fmt.Printf("Error in marshalling tenants JSON: %s\n", err)
	}
	check(err)

	pods := make([]PodJSON, 0)
	for _, node := range nodes {
		for _, pod := range node.Pods {
			// don't consider hostagents for gurobi calculations
			if strings.Contains(pod.Name, "hostagent") {
				continue
			}
			pods = append(pods, PodJSON{
				Name:   pod.Name,
				Tenant: pod.AppName,
				Host:   node.Name,
			})
		}
	}
	podsJSON, err := json.Marshal(pods)
	check(err)

	baseURL := GUROBI_URL
	payload := fmt.Sprintf(
		"[%s,%s,%s]", string(hostsJSON), string(tenantsJSON), string(podsJSON))

	slog.Info(fmt.Sprintf("Payload sending to Gurobi: %s\n", payload))

	resBody, err := sendPostRequestToGurobi(baseURL, payload)
	check(err)

	return string(resBody)
}

func sendPostRequestToGurobi(url, payload string) (string, error) {
	// HTTP client with a 2s timeout per attempt
	client := &http.Client{Timeout: GUROBI_TIMEOUT_MS * time.Millisecond}

	for {
		req, err := http.NewRequest("POST", url, bytes.NewBuffer([]byte(payload)))
		if err != nil {
			return "", err
		}
		req.Header.Set("Content-Type", "application/json")

		response, err := client.Do(req)
		if err != nil {
			// Retry only on timeouts
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() || errors.Is(err, context.DeadlineExceeded) {
				time.Sleep(10 * time.Millisecond)
				continue
			}
			return "", err
		}

		// Read and close the body before returning/looping
		body, readErr := io.ReadAll(response.Body)
		response.Body.Close()
		if readErr != nil {
			return "", readErr
		}

		// Stop retrying once we receive any response (200 or otherwise)
		if response.StatusCode != http.StatusOK {
			return "", fmt.Errorf("received non-200 status code: %d, body: %s", response.StatusCode, string(body))
		}
		return string(body), nil
	}
}

func getEqualPodWeightsForGurobi(nodes []Node, appNames []string) string {
	// return the weights in the format:
	/*
		"{
			"app1-0": 33.33,
			"app1-1": 33.33,
			"app1-2": 33.33,
			"app2-0": 50.00,
			"app2-1": 50.00,
			"app3-0": 100.00
		}"
	*/

	// get the number of pods for each app
	appNumOfPods := make(map[string]int)
	for _, appName := range appNames {
		appNumOfPods[appName] = 0
	}
	for _, node := range nodes {
		for _, pod := range node.Pods {
			appNumOfPods[pod.AppName]++
		}
	}

	// generate the weights
	gurobiWeights := map[string]float64{}
	for _, node := range nodes {
		for _, pod := range node.Pods {
			gurobiWeights[pod.Name] = 100.0 / float64(appNumOfPods[pod.AppName])
		}
	}

	gurobiWeightsBytes, err := json.Marshal(gurobiWeights)
	check(err)

	return string(gurobiWeightsBytes)
}

func setInitialGurobiWeights(nodes []Node, appNames []string) {

	gurobiWeights := getEqualPodWeightsForGurobi(nodes, appNames)

	baseURL := GUROBI_URL + "set" // "http://localhost:4876/" + "set"
	payload := gurobiWeights

	slog.Info(fmt.Sprintf(
		"Payload sending to Gurobi to set initial weights: %s\n", payload))

	resBody, err := sendPostRequestToGurobi(baseURL, payload)
	check(err)

	slog.Info(fmt.Sprintf(
		"Response from Gurobi for setting initial weights: %s\n",
		string(resBody)))
}

func parseGurobiResponse(
	gurobiResponse string,
	svcCPUConsumptionPerReq map[string]float64,
	svcPerfBasedAllowedRPS map[string]float64,
	nodes []Node) string {
	// example gurobi response:
	// {"status": 2, "result": {"app1": {"app1-node1": 89.33617463143995, "app1-node2": 178.6723492628799}, "app2": {"app2-node2": 10.66382536856006, "app2-node3": 189.33617463143995}, "app3": {"app3-node1": 100.0}, "app4": {"app4-node4": 3200.0}}}

	var response GurobiGenericResponse
	err := json.Unmarshal([]byte(gurobiResponse), &response)
	check(err)

	lbWeights := ""
	for appName, podResult := range response.Result {
		sortedValues := getValuesFromMapSortedByKeys(podResult)
		var appSum float64
		for _, value := range sortedValues {
			appSum += value
		}
		sortedWeights := make([]float64, len(sortedValues))
		for i, value := range sortedValues {
			if appSum == 0 {
				sortedWeights[i] = 100.0 / float64(len(sortedValues))
			} else {
				sortedWeights[i] = (value * 100) / appSum
			}
		}

		strSortedWeights := make([]string, len(sortedWeights))
		for i, weight := range sortedWeights {
			strSortedWeights[i] = fmt.Sprintf("%f", weight)
		}

		// get the node numbers for the app pods
		podnames := make([]string, 0, len(podResult))
		for podName := range podResult {
			podnames = append(podnames, podName)
		}
		sort.Strings(podnames)
		strNodeNums := make([]string, len(podResult))
		for i, podname := range podnames {
			strNodeNums[i] = fmt.Sprintf("%d", getNodeNumberForPod(podname, nodes))
		}

		// we want to not drop requests if the sum of cpu usage is less than
		// their fair share, so if appSum < fairShare, set appSum = fairShare
		cpuAlloc := appSum
		fairshare := getFShareLoad(nodes, appName)
		if cpuAlloc < fairshare {
			cpuAlloc = fairshare
		}

		// output in the format: "app1:45.0:100.0:45.0|55.0:1|2"
		lbWeights += fmt.Sprintf("%s:%f:%f:%f:%s:%s ",
			appName,
			svcCPUConsumptionPerReq[appName],
			cpuAlloc,
			svcPerfBasedAllowedRPS[appName],
			strings.Join(strSortedWeights, "|"),
			strings.Join(strNodeNums, "|"))
	}

	fmt.Printf("LB Weights: %s\n", lbWeights)

	return lbWeights
}

func getNodeNumberForPod(podName string, nodes []Node) int {
	for _, node := range nodes {
		_, exists := node.Pods[podName]
		if exists {
			return node.Num
		}
	}
	return -1
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
