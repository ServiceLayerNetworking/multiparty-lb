package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	CFS_PERIOD_US     = 100000
	CPUS_IN_NODE      = 2
	MINIMUM_CPU_QUOTA = 1000

	SERVER_PORT = "9988"
	SERVER_TYPE = "tcp"

	ROUNDS_FOR_ROLLING_AVG_OF_CPU_UTILS = 50
	DURATION_FOR_ONE_ROUND_MS           = 1000
	OVERHEAD                            = 5      // 10% overhead
	POD_QUOTA_OVERHEAD                  = 10     // 5% overhead
	NOISE                               = 2      // 2% noise
	ENFORCEMENT                         = "NONE" // CPU_QUOTA | CPU_SHARE | BOTH | NONE
	USE_PRESET_SHARES                   = true

	LOG_FILE_PREFIX                     = "/home/twaheed2/go/src/multiparty-lb/"
	DURATION_THAT_THIS_FILE_WILL_RUN_MS = 80_000
)

/*
What does cc do:
1. Connect to all host agents
2. Send messages to host agents to update pod state
3. Repeat the following:
	- Get CPU Utilizations from host agents
	- Solve the optimization problem by connection to Gurobi Optimizer
	- Send the CPU shares to the host agents to be applied
*/

type Node struct {
	Num               int
	Name              string
	IP                string
	HostAgentNodePort int
	Pods              map[string]string

	connection *net.Conn
}

func (n *Node) Connect() {
	connection, err := net.Dial(SERVER_TYPE,
		fmt.Sprintf("%s:%d", n.IP, n.HostAgentNodePort))
	if err != nil {
		panic(err)
	}
	n.connection = &connection
}

func (n *Node) Disconnect() {
	(*n.connection).Close()
}

func (n *Node) SendMessageAndGetResponse(msg string) string {

	slog.Info(fmt.Sprintf("conn: %v", n.connection))

	_, err := (*n.connection).Write([]byte(msg))
	if err != nil {
		slog.Warn("Error sending:" + err.Error())
	}
	slog.Info("Sent: " + msg)
	buffer := make([]byte, 4096)
	mLen, err := (*n.connection).Read(buffer)
	if err != nil {
		slog.Warn("Error reading:" + err.Error())
	}
	slog.Info("Received: " + string(buffer[:mLen]))
	return string(buffer[:mLen])
}

type LogFile struct {
	logWriter *bufio.Writer
}

func (l *LogFile) Initialize(logType string) {
	var filename string
	var runNum int
	fmt.Println("Enter log folder's name and run number:")
	fmt.Scan(&filename, &runNum)

	logFileName := fmt.Sprintf(
		"%s/%s/none_%s_%d", LOG_FILE_PREFIX, filename, logType, runNum)

	logFile, err := os.Create(logFileName)
	check(err)
	l.logWriter = bufio.NewWriter(logFile)
}

func (l *LogFile) Writeln(msg string) {
	fmt.Fprintf(l.logWriter, "%s\n", msg)
	l.logWriter.Flush()
}

type CPUUtil struct {
	Node            int
	CPUUtilizations string
}

func main() {

	// Initialize log file write
	cpuLogFile := new(LogFile)
	cpuLogFile.Initialize("CPU")

	// Initialize KubernetesClient
	k8sClient := new(KubernetesClient)
	k8sClient.Initialize()

	// Initialize nodes
	nodes := k8sClient.GetNodes()[1:]

	// Connect to all host agents
	for i := range nodes {
		nodes[i].Connect()
	}

	// Defer disconnecting from all host agents
	defer func() {
		for _, node := range nodes {
			node.Disconnect()
		}
	}()

	// Send messages to host agents to update pod state
	for i := range nodes {
		msg := "updatePods"
		for pod, uid := range nodes[i].Pods {
			msg += " " + pod + ":" + uid
		}
		slog.Info("msg: " + msg)
		response := nodes[i].SendMessageAndGetResponse(msg)
		if response != "Success" {
			panic("Failed to update pod state on node: " + nodes[i].IP)
		}
	}

	if ENFORCEMENT == "NONE" {

		go ccWithNoEnforcement(cpuLogFile, nodes)

	} else {

		// update with default values of the cpu quotas and shares
		setDefaultCPUQuotas(nodes, cpuLogFile)
		setDefaultCPUShares(nodes, cpuLogFile)

		if ENFORCEMENT == "CPU_QUOTA" {
			slog.Info("Enforcing CPU Quotas")
			go ccWithCPUQuotas(cpuLogFile, nodes)
		} else if ENFORCEMENT == "CPU_SHARE" {
			slog.Info("Enforcing CPU Shares")
			go ccWithCPUShares(cpuLogFile, nodes)
		} else if ENFORCEMENT == "BOTH" {
			slog.Info("Enforcing CPU Quotas and Shares")
			go ccWithBoth(cpuLogFile, nodes)
		} else {
			panic("Invalid enforcement type")
		}
	}

	time.Sleep(DURATION_THAT_THIS_FILE_WILL_RUN_MS * time.Millisecond)
}

func ccWithNoEnforcement(cpuLogFile *LogFile, nodes []Node) {

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan CPUUtil)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- CPUUtil{i, cpuUtilizations}
			}(i, nodes[i])
		}
		nodeCPUUtilizations := make([]string, len(nodes))
		for range nodes {
			cpuUtil := <-cpuUtilizationCh
			nodeCPUUtilizations[cpuUtil.Node] = cpuUtil.CPUUtilizations
			slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
				cpuUtil.Node, cpuUtil.CPUUtilizations))
		}

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormatNoEnforcement(nodeCPUUtilizations))
	}
}

func ccWithCPUShares(cpuLogFile *LogFile, nodes []Node) {

	// Initialize past CPU Utilizations
	roundsAppCPUUtils := make([]map[int]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan CPUUtil)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- CPUUtil{i, cpuUtilizations}
			}(i, nodes[i])
		}
		nodeCPUUtilizations := make([]string, len(nodes))
		for range nodes {
			cpuUtil := <-cpuUtilizationCh
			nodeCPUUtilizations[cpuUtil.Node] = cpuUtil.CPUUtilizations
			slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
				cpuUtil.Node, cpuUtil.CPUUtilizations))
		}

		// - Solve the optimization problem by connection to Gurobi Optimizer
		nodeCPUShares, newRoundsAppCPUUtils := getOptimalCPUShares(
			nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormat(nodeCPUUtilizations, nodeCPUShares))

		// - Send the CPU shares to the host agents to be applied
		if nodeCPUShares == nil {
			slog.Warn("Failed to get optimal CPU shares")
		} else {
			for i := range nodes {
				msg := "applyCPUShares " + nodeCPUShares[i]
				response := nodes[i].SendMessageAndGetResponse(msg)
				if response != "Success" {
					slog.Warn("Failed to apply CPU shares on node: " +
						nodes[i].IP)
				}
			}
		}
	}
}

func ccWithCPUQuotas(cpuLogFile *LogFile, nodes []Node) {

	// Initialize past CPU Utilizations
	roundsAppCPUUtils := make([]map[int]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan CPUUtil)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- CPUUtil{i, cpuUtilizations}
			}(i, nodes[i])
		}
		nodeCPUUtilizations := make([]string, len(nodes))
		for range nodes {
			cpuUtil := <-cpuUtilizationCh
			nodeCPUUtilizations[cpuUtil.Node] = cpuUtil.CPUUtilizations
			slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
				cpuUtil.Node, cpuUtil.CPUUtilizations))
		}

		// - Solve the optimization problem by connection to Gurobi Optimizer
		nodeCPUQuotas, newRoundsAppCPUUtils := getOptimalCPUQuotas(
			nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Quotas
		cpuLogFile.Writeln(
			getLogFileFormatForCPUQuotas(nodeCPUUtilizations, nodeCPUQuotas))

		// - Send the CPU Quotas to the host agents to be applied
		if nodeCPUQuotas == nil {
			slog.Warn("Failed to get optimal CPU Quotas")
		} else {
			for i := range nodes {
				msg := "applyCPUQuotas " + nodeCPUQuotas[i]
				response := nodes[i].SendMessageAndGetResponse(msg)
				if response != "Success" {
					slog.Warn("Failed to apply CPU Quotas on node: " +
						nodes[i].IP)
				}
			}
		}
	}
}

func ccWithBoth(cpuLogFile *LogFile, nodes []Node) {

	// Initialize past CPU Utilizations
	roundsAppCPUUtils := make([]map[int]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan CPUUtil)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- CPUUtil{i, cpuUtilizations}
			}(i, nodes[i])
		}
		nodeCPUUtilizations := make([]string, len(nodes))
		for range nodes {
			cpuUtil := <-cpuUtilizationCh
			nodeCPUUtilizations[cpuUtil.Node] = cpuUtil.CPUUtilizations
			slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
				cpuUtil.Node, cpuUtil.CPUUtilizations))
		}

		// - Solve the optimization problem by connection to Gurobi Optimizer
		nodeCPUQuotas, newRoundsAppCPUUtils := getOptimalCPUQuotas(
			nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Quotas
		cpuLogFile.Writeln(
			getLogFileFormatForCPUQuotas(nodeCPUUtilizations, nodeCPUQuotas))

		// - Send the CPU Quotas to the host agents to be applied
		if nodeCPUQuotas == nil {
			slog.Warn("Failed to get optimal CPU Quotas")
		} else {
			for i := range nodes {
				msg := "applyCPUQuotas " + nodeCPUQuotas[i]
				response := nodes[i].SendMessageAndGetResponse(msg)
				if response != "Success" {
					slog.Warn("Failed to apply CPU Quotas on node: " +
						nodes[i].IP)
				}
			}
		}

		// - Solve the optimization problem by connection to Gurobi Optimizer
		nodeCPUShares, newRoundsAppCPUUtils := getOptimalCPUShares(
			nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormat(nodeCPUUtilizations, nodeCPUShares))

		// - Send the CPU shares to the host agents to be applied
		if nodeCPUShares == nil {
			slog.Warn("Failed to get optimal CPU shares")
		} else {
			for i := range nodes {
				msg := "applyCPUShares " + nodeCPUShares[i]
				response := nodes[i].SendMessageAndGetResponse(msg)
				if response != "Success" {
					slog.Warn("Failed to apply CPU shares on node: " +
						nodes[i].IP)
				}
			}
		}
	}
}

func makeNoiseZero(appUtils map[int]float64, noise float64) map[int]float64 {
	for appNum, util := range appUtils {
		if util < noise {
			appUtils[appNum] = 0
		}
	}
	return appUtils
}

func getOptimalCPUQuotas(
	nodeCPUUtilizations []string,
	roundsAppCPUUtils []map[int]float64) ([]string, []map[int]float64) {

	// parse current cpu utilizations
	currentAppUtils := getPerAppUtilizations(nodeCPUUtilizations)
	effectiveAppUtils := makeNoiseZero(currentAppUtils, NOISE)
	effectiveAppUtils = addOverhead(effectiveAppUtils, OVERHEAD)

	// get rolling average
	avgAppUtils, newRoundsAppCPUUtils := getRollingAverage(
		effectiveAppUtils, roundsAppCPUUtils)

	// avgAppUtils = map[int]float64{
	// 	1: 300.0,
	// 	2: 200.0,
	// 	3: 100.0,
	// }

	// get weights from gurobi
	gurobiResponse := getWeightsFromGurobi(200.0, avgAppUtils)

	// get cpu shares
	nodeCPUShares := getNodeCPUQuotas(gurobiResponse)

	return nodeCPUShares, newRoundsAppCPUUtils
}

func getOptimalCPUShares(
	nodeCPUUtilizations []string,
	roundsAppCPUUtils []map[int]float64) ([]string, []map[int]float64) {

	// parse current cpu utilizations
	currentAppUtils := getPerAppUtilizations(nodeCPUUtilizations)
	effectiveAppUtils := makeNoiseZero(currentAppUtils, NOISE)
	effectiveAppUtils = addOverhead(effectiveAppUtils, OVERHEAD)

	// get rolling average
	avgAppUtils, newRoundsAppCPUUtils := getRollingAverage(
		effectiveAppUtils, roundsAppCPUUtils)

	// avgAppUtils = map[int]float64{
	// 	1: 300.0,
	// 	2: 200.0,
	// 	3: 100.0,
	// }

	// get weights from gurobi
	gurobiResponse := getWeightsFromGurobi(200.0, avgAppUtils)

	// get cpu shares
	nodeCPUShares := getNodeCPUShares(gurobiResponse)

	return nodeCPUShares, newRoundsAppCPUUtils
}

func addOverhead(appUtils map[int]float64, overhead float64) map[int]float64 {
	for appNum, util := range appUtils {
		if appNum == 3 {
			appUtils[appNum] = util + overhead
		} else {
			appUtils[appNum] = util + overhead*2
		}
	}
	return appUtils
}

func getRollingAverage(
	currentAppUtils map[int]float64,
	roundsAppCPUUtils []map[int]float64) (map[int]float64, []map[int]float64) {

	// update rounds
	newRoundsAppCPUUtils := append(roundsAppCPUUtils, currentAppUtils)
	if len(newRoundsAppCPUUtils) > ROUNDS_FOR_ROLLING_AVG_OF_CPU_UTILS {
		newRoundsAppCPUUtils = newRoundsAppCPUUtils[1:]
	}

	// get avg utils
	avgAppUtils := make(map[int]float64)
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

type LogFileFormat struct {
	Time            int64             `json:"time"`
	CPUUtilizations map[string]string `json:"CPUUtilizations"`
	CPUShares       map[string]string `json:"CPUShares"`
	CPUQuotas       map[string]string `json:"CPUQuotas"`
}

func getLogFileFormatNoEnforcement(nodeCPUUtilizations []string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
	}

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil, " ")

		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName, podUtil := podUtilMap[0], podUtilMap[1]
			logFileFormat.CPUUtilizations[podName] = podUtil
		}
	}

	logFileFormatStr, err := json.Marshal(logFileFormat)
	check(err)

	return string(logFileFormatStr)
}

func getLogFileFormat(
	nodeCPUUtilizations []string, nodeCPUShares []string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
	}

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil, " ")

		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName, podUtil := podUtilMap[0], podUtilMap[1]
			logFileFormat.CPUUtilizations[podName] = podUtil
		}

	}

	for _, nodeCPUShare := range nodeCPUShares {

		podCPShares := strings.Split(nodeCPUShare, " ")

		for _, podCPUShare := range podCPShares {
			podShareMap := strings.Split(podCPUShare, ":")
			podName, podShare := podShareMap[0], podShareMap[1]
			logFileFormat.CPUShares[podName] = podShare
		}

	}

	logFileFormatStr, err := json.Marshal(logFileFormat)
	check(err)

	return string(logFileFormatStr)
}

func getLogFileFormatForCPUQuotas(
	nodeCPUUtilizations []string, nodeCPUQuotas []string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
	}

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil, " ")

		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName, podUtil := podUtilMap[0], podUtilMap[1]
			logFileFormat.CPUUtilizations[podName] = podUtil
		}

	}

	for _, nodeCPUQuota := range nodeCPUQuotas {

		podCPUQuotas := strings.Split(nodeCPUQuota, " ")

		for _, podCPUQuota := range podCPUQuotas {
			podQuotaMap := strings.Split(podCPUQuota, ":")
			podName, podQuota := podQuotaMap[0], podQuotaMap[1]
			logFileFormat.CPUQuotas[podName] = podQuota
		}

	}

	logFileFormatStr, err := json.Marshal(logFileFormat)
	check(err)

	return string(logFileFormatStr)
}

func check(err error) {
	if err != nil {
		panic(err)
	}
}

func getPerAppUtilizations(nodeCPUUtilizations []string) map[int]float64 {

	appUtils := make(map[int]float64)
	for _, cpuUtil := range nodeCPUUtilizations {

		// example cpuUtil to parse: "cpuUtilizations app1-node1:45 app2-node1:69"

		cpuUtilStrs := strings.Split(cpuUtil, " ")[1:]
		for _, cpuUtilStr := range cpuUtilStrs {

			util := strings.Split(cpuUtilStr, ":")

			appNumStr := (util[0][3:4])
			appNum, err := strconv.Atoi(appNumStr)
			check(err)

			podUtil, err := strconv.ParseFloat(util[1], 64)
			check(err)

			appUtils[appNum] += podUtil
		}

	}
	return appUtils
}

type GurobiResponse struct {
	Status    int     `json:"status"`
	App1Node1 float64 `json:"t00"`
	App1Node2 float64 `json:"t01"`
	App2Node2 float64 `json:"t11"`
	App2Node3 float64 `json:"t12"`
	App3Node1 float64 `json:"t20"`
}

func getWeightsFromGurobi(
	hostCap float64, appUtils map[int]float64) string {

	baseURL := "http://localhost:5000"
	resource := "/"
	params := url.Values{}
	params.Add("host_cap", fmt.Sprintf("%f", hostCap))
	params.Add("t0", fmt.Sprintf("%f", appUtils[1]))
	params.Add("t1", fmt.Sprintf("%f", appUtils[2]))
	params.Add("t2", fmt.Sprintf("%f", appUtils[3]))

	u, _ := url.ParseRequestURI(baseURL)
	u.Path = resource
	u.RawQuery = params.Encode()
	urlStr := fmt.Sprintf("%v", u)

	res, err := http.Get(urlStr)
	check(err)

	resBody, err := io.ReadAll(res.Body)
	check(err)

	return string(resBody)
}

func getNodeCPUShares(gurobiResponse string) []string {

	if USE_PRESET_SHARES {
		return getPresetCPUShares()
	}

	var response GurobiResponse
	err := json.Unmarshal([]byte(gurobiResponse), &response)
	check(err)

	if response.Status != 2 {
		slog.Warn(fmt.Sprintf("gurobi returned status %d", response.Status))
		return nil
	} else {
		nodeCPUShares := make([]string, 3)
		nodeCPUShares[0] = fmt.Sprintf("%s:%f %s:%f",
			"app1-node1",
			(response.App1Node1*512)/(response.App1Node1+response.App3Node1),
			"app3-node1",
			(response.App3Node1*512)/(response.App1Node1+response.App3Node1))
		nodeCPUShares[1] = fmt.Sprintf("%s:%f %s:%f",
			"app1-node2",
			(response.App1Node2*512)/(response.App1Node2+response.App2Node2),
			"app2-node2",
			(response.App2Node2*512)/(response.App1Node2+response.App2Node2))
		nodeCPUShares[2] = fmt.Sprintf("%s:%f",
			"app2-node3",
			(response.App2Node3*512)/response.App2Node3)

		// nodeCPUShares[0] = fmt.Sprintf("%s:%f %s:%f",
		// 	"app1-node1",
		// 	256.0,
		// 	"app3-node1",
		// 	256.0)
		// nodeCPUShares[1] = fmt.Sprintf("%s:%f %s:%f",
		// 	"app1-node2",
		// 	256.0,
		// 	"app2-node2",
		// 	256.0)
		// nodeCPUShares[2] = fmt.Sprintf("%s:%f",
		// 	"app2-node3",
		// 	256.0)

		return nodeCPUShares
	}
}

func getQuota(appShare, nodeSum float64) int64 {
	quota := int64((appShare * (CFS_PERIOD_US * CPUS_IN_NODE)) / (nodeSum))
	if quota < 1000 {
		quota = 1000
	}
	podQuotaOverhead :=
		(CFS_PERIOD_US * CPUS_IN_NODE) * (POD_QUOTA_OVERHEAD / 100.0)
	return quota + int64(podQuotaOverhead)
}

func setDefaultCPUQuotas(nodes []Node, cpuLogFile *LogFile) {

	nodeCPUQuotas := getDefaultCPUQuotas()

	// - Send the CPU Quotas to the host agents to be applied
	if nodeCPUQuotas == nil {
		slog.Warn("Failed to get optimal CPU Quotas")
	} else {
		for i := range nodes {
			msg := "applyCPUQuotas " + nodeCPUQuotas[i]
			response := nodes[i].SendMessageAndGetResponse(msg)
			if response != "Success" {
				slog.Warn("Failed to apply CPU Quotas on node: " +
					nodes[i].IP)
			}
		}
	}
}

func setDefaultCPUShares(nodes []Node, cpuLogFile *LogFile) {

	nodeCPUShares := getDefaultCPUShares()

	// - Send the CPU Shares to the host agents to be applied
	if nodeCPUShares == nil {
		slog.Warn("Failed to get optimal CPU Shares")
	} else {
		for i := range nodes {
			msg := "applyCPUShares " + nodeCPUShares[i]
			response := nodes[i].SendMessageAndGetResponse(msg)
			if response != "Success" {
				slog.Warn("Failed to apply CPU Shares on node: " +
					nodes[i].IP)
			}
		}
	}
}

func getDefaultCPUShares() []string {
	return []string{
		"app1-node1:256 app3-node1:256",
		"app1-node2:256 app2-node2:256",
		"app2-node3:512",
	}
}

func getDefaultCPUQuotas() []string {
	return []string{
		"app1-node1:-1 app3-node1:-1",
		"app1-node2:-1 app2-node2:-1",
		"app2-node3:-1",
	}
}

func getPresetCPUShares() []string {
	return []string{
		"app1-node1:0 app3-node1:512",
		"app1-node2:512 app2-node2:0",
		"app2-node3:512",
	}
}

func getPresetCPUQuotas() []string {
	return []string{
		fmt.Sprintf("app1-node1:%d app3-node1:%d",
			MINIMUM_CPU_QUOTA, CFS_PERIOD_US*CPUS_IN_NODE),
		fmt.Sprintf("app1-node2:%d app2-node2:%d",
			CFS_PERIOD_US*CPUS_IN_NODE, MINIMUM_CPU_QUOTA),
		fmt.Sprintf("app2-node3:%d",
			CFS_PERIOD_US*CPUS_IN_NODE),
	}
}

func getNodeCPUQuotas(gurobiResponse string) []string {

	if USE_PRESET_SHARES {
		return getPresetCPUQuotas()
	}

	var response GurobiResponse
	err := json.Unmarshal([]byte(gurobiResponse), &response)
	check(err)

	if response.Status != 2 {
		slog.Warn(fmt.Sprintf("gurobi returned status %d", response.Status))
		return nil
	} else {
		nodeCPUShares := make([]string, 3)
		nodeCPUShares[0] = fmt.Sprintf("%s:%d %s:%d",
			"app1-node1",
			getQuota(response.App1Node1, response.App1Node1+response.App3Node1),
			"app3-node1",
			getQuota(response.App3Node1, response.App1Node1+response.App3Node1))
		nodeCPUShares[1] = fmt.Sprintf("%s:%d %s:%d",
			"app1-node2",
			getQuota(response.App1Node2, response.App1Node2+response.App2Node2),
			"app2-node2",
			getQuota(response.App2Node2, response.App1Node2+response.App2Node2))
		nodeCPUShares[2] = fmt.Sprintf("%s:%d",
			"app2-node3",
			getQuota(response.App2Node3, response.App2Node3))

		return nodeCPUShares
	}
}
