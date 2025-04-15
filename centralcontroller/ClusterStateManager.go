package main

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"regexp"
	"sort"
	"strconv"
	"strings"
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

func (c *ClusterStateManager) GetOptimalLBWeights(
	nodeCPUUtilizations []string,
	reqStats []ReqStat,
	reqSentStats []ReqStat,
	svcCPUConsumptionPerReq map[string]float64) string {

	var gurobiInput map[string]float64

	if USE_RPS_INSTEAD_OF_CPU {

		// currentAppUtils := getPerAppRPS(reqStats)
		currentAppUtils := getPerAppRpsBasedUtil(
			reqSentStats,
			svcCPUConsumptionPerReq)

		// get weights from gurobi
		gurobiInput = currentAppUtils

	} else {
		currentAppUtils := getPerAppUtilizations(nodeCPUUtilizations)

		// effectiveAppUtils := makeNoiseZero(currentAppUtils, NOISE)
		// effectiveAppUtils = addOverhead(effectiveAppUtils, OVERHEAD)

		// get rolling average
		avgAppUtils, newRoundsAppCPUUtils := getRollingAverage(
			currentAppUtils, c.RoundsAppCPUUtils)
		c.RoundsAppCPUUtils = newRoundsAppCPUUtils

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

	lbWeights := parseGurobiResponse(gurobiResponse,
		svcCPUConsumptionPerReq,
		c.Nodes)
	return lbWeights

	// return "profile:0.0|100.0 frontend:0.0|100.0 recommendation:100.0",
	// 	newRoundsAppCPUUtils

}

func getPerAppRpsBasedUtil(
	reqSentStats []ReqStat,
	svcCPUConsumptionPerReq map[string]float64) map[string]float64 {

	// THIS CODE IS BUGGY. WE DON'T HAVE THE EXACT TIME FOR WHEN WE RECEIVED THE
	// REQUEST LOG REQUEST SO WE DON'T KNOW WHERE TO START THE RPS_WINDOW_MS
	// FROM. WE ESTIMATE THE TIME BY TAKING THE START TIME OF MOST RECENTLY SENT
	// REQUEST

	// UPDATE: WE IMPROVED THE CODE BY USING CURRENT TIME AS THE START TIME OF THE WINDOW

	// get the most recently sent request's time
	var maxStartTimeMs int64 = 0
	for _, reqStat := range reqSentStats {
		if reqStat.StartTimeMs > maxStartTimeMs {
			maxStartTimeMs = reqStat.StartTimeMs
		}
	}
	// curentTimeMs := time.Now().UnixMilli()
	// maxStartTimeMs := curentTimeMs

	// get the number of requests sent in the last RPS_WINDOW_MS
	svcSentReqs := make(map[string]int)
	for _, reqStat := range reqSentStats {
		if maxStartTimeMs-reqStat.StartTimeMs <= RPS_WINDOW_MS {
			// remove .mplb.com from the dstSvc
			dstSvc := strings.ReplaceAll(reqStat.DstSvc, ".mplb.com", "")
			_, ok := svcSentReqs[dstSvc]
			if !ok {
				svcSentReqs[dstSvc] = 0
			}
			svcSentReqs[dstSvc]++
		}
	}

	// get the RPS for each service
	svcRPSBasedUtil := make(map[string]float64)
	for svc, sentReqs := range svcSentReqs {
		svcRPS := float64(sentReqs) / (float64(RPS_WINDOW_MS) / 1000.0)
		svcRPSBasedUtil[svc] = svcRPS * svcCPUConsumptionPerReq[svc]
	}

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

		// example cpuUtil to parse: "cpuUtilizations app1-node1:45 app2-node1:69"

		cpuUtilStrs := strings.Split(cpuUtil, " ")[1:]
		for _, cpuUtilStr := range cpuUtilStrs {

			util := strings.Split(cpuUtilStr, ":")
			appName := util[0]

			// don't consider hostagents for gurobi calculations
			if strings.Contains(appName, "hostagent") {
				continue
			}

			// get "app1-node1" from "app1-node1-0"
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
		tenants = append(tenants, TenantJSON{
			Name:       appName,
			Load:       util,
			FShareLoad: getFShareLoad(nodes, appName),
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

	resBody, err := sendPostRequest(baseURL, payload)
	check(err)

	return string(resBody)
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

	resBody, err := sendPostRequest(baseURL, payload)
	check(err)

	slog.Info(fmt.Sprintf(
		"Response from Gurobi for setting initial weights: %s\n",
		string(resBody)))
}

func parseGurobiResponse(
	gurobiResponse string,
	svcCPUConsumptionPerReq map[string]float64,
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

		// output in the format: "app1:45.0:100.0:45.0|55.0:1|2"
		lbWeights += fmt.Sprintf("%s:%f:%f:%s:%s ",
			appName,
			svcCPUConsumptionPerReq[appName],
			appSum,
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
