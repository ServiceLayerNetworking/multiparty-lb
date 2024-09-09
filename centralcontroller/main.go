package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	CFS_PERIOD_US     = 100000
	CPUS_IN_NODE      = 210
	MINIMUM_CPU_QUOTA = 1000

	SERVER_PORT = "9988"
	SERVER_TYPE = "tcp"

	CPU_UTILIZATION_INTERVAL_MS         = 500
	ROUNDS_FOR_ROLLING_AVG_OF_CPU_UTILS = 50

	OVERHEAD           = 10 // 10% overhead
	POD_QUOTA_OVERHEAD = 10 // 5% overhead
	NOISE              = 2  // 2% noise
	ENFORCEMENT        = "LB"
	USE_PRESET_SHARES  = false

	DEFAULT_LB_WEIGHTS = ""
	LOG_FILE_PREFIX    = "/users/twaheed/multiparty-lb"
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

type Pod struct {
	Name           string
	AppName        string
	FShare         float64
	CGroupFilePath string
}

type Node struct {
	Num               int
	Name              string
	IP                string
	HostAgentNodePort int
	Pods              map[string]Pod
	MilliCores        int

	connection *net.Conn
}

type ReqStat struct {
	SrcSvc      string `json:"srcSvc"`
	SrcPod      string `json:"srcPod"`
	DstSvc      string `json:"dstSvc"`
	DstPod      string `json:"dstPod"`
	StartTimeMs int64  `json:"startTimeMs"`
	EndTimeMs   int64  `json:"endTimeMs"`
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

	// slog.Info(fmt.Sprintf("conn: %v", n.connection))

	_, err := (*n.connection).Write([]byte(msg))
	if err != nil {
		slog.Warn("Error sending:" + err.Error())
	}
	slog.Info("Sent: " + msg)

	var buffer strings.Builder
	delim := "<END>"
	buf := make([]byte, 1024)

	for {
		n, err := (*n.connection).Read(buf)
		if err != nil {
			slog.Warn("Error sending:" + err.Error())
			return ""
		}

		buffer.Write(buf[:n])

		// Convert the accumulated buffer to a string
		data := buffer.String()

		// Check if the delimiter is in the accumulated data
		if strings.Contains(data, delim) {
			// Extract the message up to the delimiter
			message := data[:strings.Index(data, delim)]
			slog.Info("Received message: " + message)
			return message
		}
	}
}

type LogFile struct {
	logWriter *bufio.Writer
}

func (l *LogFile) Initialize(logFileName string) {
	logFile, err := os.Create(logFileName)
	check(err)
	l.logWriter = bufio.NewWriter(logFile)
}

func (l *LogFile) Writeln(msg string) {
	fmt.Fprintf(l.logWriter, "%s\n", msg)
	l.logWriter.Flush()
}

type NodeStats struct {
	Node            int
	CPUUtilizations string
	ReqStats        string
}

func getFlags() (string, string, int) {
	// get file name to log
	logfile := flag.String("logfile", "", "Name of the log file")

	// get the enforcement strategy
	enforcement := flag.String("enforcement", "NONE",
		"Enforcement strategy [CPU_QUOTA|CPU_SHARE|BOTH|NONE|LB]")

	// get the duration this file will run
	durationMs := flag.Int("d", 70_000, "Duration this file will run in ms")

	// Parse the command line flags
	flag.Parse()

	logfileName := *logfile

	if *logfile == "" {
		var filename string
		var runNum int
		fmt.Println("Enter log folder's name and run number:")
		fmt.Scan(&filename, &runNum)

		logfileName = fmt.Sprintf(
			"%s/%s/%s_%s_%d",
			LOG_FILE_PREFIX, filename, enforcement, "cc", runNum)
	}

	return logfileName, *enforcement, *durationMs
}

func getPodsToLog(allPodNames []string) []string {
	// Define the 'pods' flag
	pods := flag.String("pods", "", "Comma-separated list of pod names")

	// Parse the command line flags
	flag.Parse()

	// Check if the 'pods' flag is provided
	if *pods == "" {
		fmt.Printf("Pods to print: %v\n", allPodNames)
		return allPodNames
	}

	// Convert the comma-separated string to an array of names
	podArray := strings.Split(*pods, ",")

	return podArray
}

// handlerWriter is an io.Writer that calls an  slog.Handler.
// It is used to link the default log.Logger to the default slog.Logger.
type handlerWriter struct {
	h         slog.Handler
	level     slog.Level
	capturePC bool
}

func (w *handlerWriter) Write(buf []byte) (int, error) {
	if !w.h.Enabled(context.Background(), w.level) {
		return 0, nil
	}
	var pc uintptr
	if w.capturePC {
		// skip [runtime.Callers, w.Write, Logger.Output, log.Print]
		var pcs [1]uintptr
		runtime.Callers(4, pcs[:])
		pc = pcs[0]
	}

	// Remove final newline.
	origLen := len(buf) // Report that the entire buf was written.
	if len(buf) > 0 && buf[len(buf)-1] == '\n' {
		buf = buf[:len(buf)-1]
	}
	r := slog.NewRecord(time.Now(), w.level, string(buf), pc)
	return origLen, w.h.Handle(context.Background(), r)
}

func main() {

	// Initialize the logger
	l := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelError,
	}))
	slog.SetDefault(l) // configures log package to print with LevelError
	capturePC := log.Flags()&(log.Lshortfile|log.Llongfile) != 0
	log.SetOutput(&handlerWriter{l.Handler(), slog.LevelError, capturePC}) // configures log package to print with LevelError

	// get flags
	logFileName, enforcement, durationMs := getFlags()

	// Initialize log file write
	cpuLogFile := new(LogFile)
	cpuLogFile.Initialize(logFileName)

	// Initialize KubernetesClient
	k8sClient := new(KubernetesClient)
	k8sClient.Initialize()

	// Initialize nodes
	nodes := k8sClient.GetNodes()
	appNames := k8sClient.GetAppNames()
	fmt.Printf("Nodes:\n")
	for i, node := range nodes {
		fmt.Printf("Node %d:\n%v\n\n", i, node)
	}

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
	podNames := make([]string, 0)
	for i := range nodes {
		msg := "updatePods"
		for podName, pod := range nodes[i].Pods {
			msg += " " + podName + ":" + pod.CGroupFilePath
			podNames = append(podNames, podName)
		}
		slog.Info("msg: " + msg)
		response := nodes[i].SendMessageAndGetResponse(msg)
		if response != "Success" {
			panic("Failed to update pod state on node: " + nodes[i].IP)
		}
	}

	// Set default LB weights
	setDefaultLBWeights(nodes, appNames)

	// Set default CPU Shares
	setDefaultCPUShares(nodes)

	// get pods to log
	podNamesToLog := getPodsToLog(podNames)

	if enforcement == "NONE" {
		go ccWithNoEnforcement(cpuLogFile, nodes, podNamesToLog)

	} else {

		if enforcement == "LB" {
			go ccWithLBEnforcement(cpuLogFile, nodes, podNamesToLog)

		} else {

			if enforcement == "CPU_QUOTA" {
				slog.Info("Enforcing CPU Quotas")
				go ccWithCPUQuotas(cpuLogFile, nodes)
			} else if enforcement == "CPU_SHARE" {
				slog.Info("Enforcing CPU Shares")
				go ccWithCPUShares(cpuLogFile, nodes, podNamesToLog)
			} else if enforcement == "BOTH" {
				slog.Info("Enforcing CPU Quotas and Shares")
				go ccWithBoth(cpuLogFile, nodes)
			} else {
				panic("Invalid enforcement type")
			}
		}
	}

	time.Sleep(time.Duration(durationMs) * time.Millisecond)
	fmt.Println("Time is up. Exiting...")
}

func ccWithNoEnforcement(
	cpuLogFile *LogFile, nodes []Node, podsToLog []string) {

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	for {

		// Get CPU Utilizations and Request Stats from host agents
		nodeCPUUtilizations, reqStats := getCPUUtilAndReqStatsFromCluster(nodes)

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormatNoEnforcement(nodeCPUUtilizations))
		printCPUStatsToConsole(nodeCPUUtilizations, reqStats, podsToLog)

		// log the request stats
		cpuLogFile.Writeln(
			fmt.Sprintf("ReqStats: %s", getReqStatsJSON(reqStats)))
	}
}

func getKeysSortedByValue(m map[string]float64, keys []string) []string {
	// Sort the keys based on the corresponding values in the map
	sort.Slice(keys, func(i, j int) bool {
		return m[keys[i]] > m[keys[j]]
	})

	return keys
}

func parseCPUUtilsAndReqStats(resp string) (string, string, error) {
	parts := strings.Split(resp, "\n<SEP>\n")
	if len(parts) != 2 {
		return "", "", errors.New("invalid response from host agent: " + resp)
	}
	return parts[0], parts[1], nil
}

func parseReqStats(reqStatsStr string) []ReqStat {

	// fmt.Printf("ReqStatsStr: %s\n", reqStatsStr)

	reqStats := make([]ReqStat, 0)
	reqStatsStr = strings.TrimSpace(reqStatsStr)
	if reqStatsStr == "reqStats:" {
		return reqStats
	}
	reqStatsStrs := strings.Split(reqStatsStr, "\n")[1:]
	for _, reqStatStr := range reqStatsStrs {
		reqStatParts := strings.Split(reqStatStr, " ")
		slog.Info(fmt.Sprintf("reqStatToStore: %s\n", reqStatParts))
		reqStats = append(reqStats, ReqStat{
			SrcSvc:      reqStatParts[0],
			SrcPod:      reqStatParts[1],
			DstSvc:      reqStatParts[2],
			DstPod:      reqStatParts[3],
			StartTimeMs: stringToInt64(reqStatParts[4]),
			EndTimeMs:   stringToInt64(reqStatParts[5]),
		})
	}
	return reqStats
}

func stringToInt64(str string) int64 {
	i, err := strconv.ParseInt(str, 10, 64)
	check(err)
	return i
}

func getCPUUtilAndReqStatsFromCluster(nodes []Node) ([]string, []ReqStat) {

	// - Get CPU Utilizations from host agents
	cpuUtilizationCh := make(chan NodeStats)
	for i := range nodes {
		msg := "getCPUUtilsAndReqStats"
		go func(i int, node Node) {
			resp := node.SendMessageAndGetResponse(msg)
			cpuUtils, reqStats, err := parseCPUUtilsAndReqStats(resp)
			if err != nil {
				slog.Error(fmt.Sprintf("Failed to parse CPU Utilizations and ReqStats from Node %d: %s", i, err.Error()))
				panic(err)
			}
			cpuUtilizationCh <- NodeStats{i, cpuUtils, reqStats}
		}(i, nodes[i])
	}
	reqStats := make([]ReqStat, 0)
	nodeCPUUtilizations := make([]string, len(nodes))
	for range nodes {
		nodeStats := <-cpuUtilizationCh
		nodeCPUUtilizations[nodeStats.Node] = nodeStats.CPUUtilizations
		reqStats = append(reqStats, parseReqStats(nodeStats.ReqStats)...)
		slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
			nodeStats.Node, nodeStats.CPUUtilizations))
	}

	return nodeCPUUtilizations, reqStats
}

func ccWithLBEnforcement(
	cpuLogFile *LogFile, nodes []Node, podsToLog []string) {

	// Initialize past CPU Utilizations
	roundsAppCPUUtils := make([]map[string]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	for {

		// Get CPU Utilizations and Request Stats from host agents
		nodeCPUUtilizations, reqStats := getCPUUtilAndReqStatsFromCluster(nodes)

		// - Solve the optimization problem by connection to Gurobi Optimizer
		lbWeights, newRoundsAppCPUUtils := getOptimalLBWeights(
			nodes, nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(
			getLogFileFormatLBEnforcement(nodeCPUUtilizations, lbWeights))
		printCPUStatsToConsole(nodeCPUUtilizations, reqStats, podsToLog)

		// log the request stats
		cpuLogFile.Writeln(
			fmt.Sprintf("ReqStats: %s", getReqStatsJSON(reqStats)))

		// lbWeights := getLBWeights()
		// lbWeights := "profile:0.0|100.0 frontend:0.0|100.0 recommendation:100.0"
		// - Send the CPU Quotas to the host agents to be applied
		for i := range nodes {
			msg := "applyLBWeights " + lbWeights
			response := nodes[i].SendMessageAndGetResponse(msg)
			if response != "Success" {
				slog.Warn("Failed to apply CPU Quotas on node: " +
					nodes[i].IP)
			}
		}
	}
}

func printCPUStatsToConsole(
	nodeCPUUtilizations []string, reqStats []ReqStat, podsToLog []string) {

	cpuUtilMap := getCPUUtilMap(nodeCPUUtilizations)
	currentTimeStr := time.Now().Format("2006-01-02 15:04:05.000")
	toPrint := "----------------------------------------\n"
	toPrint += fmt.Sprintf("Number of requests logged: %d\n", len(reqStats))
	toPrint += fmt.Sprintf("Time: %s:\n\n", currentTimeStr)
	toPrint += fmt.Sprintf("%-30s %s\n", "PODNAME", "CPU (%)")
	// fmt.Printf("Pods to log: %v\n", podsToLog)
	// fmt.Printf("CPU Map: %v\n", cpuUtilMap)
	sortedPodsToLog := getKeysSortedByValue(cpuUtilMap, podsToLog)
	// sort.Strings(podsToLog)
	for _, podName := range sortedPodsToLog {
		toPrint += fmt.Sprintf("%-30s %.2f\n",
			podName, cpuUtilMap[podName])
	}
	fmt.Printf("%s\n", toPrint)
}

func getReqStatsJSON(reqStats []ReqStat) string {
	reqStatsJSON, err := json.Marshal(reqStats)
	check(err)
	return string(reqStatsJSON)
}

func ccWithCPUShares(cpuLogFile *LogFile, nodes []Node, podsToLog []string) {

	// Initialize past CPU Utilizations
	roundsAppCPUUtils := make([]map[string]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// Get CPU Utilizations and Request Stats from host agents
		nodeCPUUtilizations, reqStats := getCPUUtilAndReqStatsFromCluster(nodes)

		// - Solve the optimization problem by connection to Gurobi Optimizer
		nodeCPUShares, newRoundsAppCPUUtils := getOptimalCPUShares(
			nodes, nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormat(nodeCPUUtilizations, nodeCPUShares))
		printCPUStatsToConsole(nodeCPUUtilizations, reqStats, podsToLog)

		// log the request stats
		cpuLogFile.Writeln(
			fmt.Sprintf("ReqStats: %s", getReqStatsJSON(reqStats)))

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
	roundsAppCPUUtils := make([]map[string]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan NodeStats)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- NodeStats{i, cpuUtilizations, ""}
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
	roundsAppCPUUtils := make([]map[string]float64, 0)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	// - Solve the optimization problem by connection to Gurobi Optimizer
	// - Send the CPU shares to the host agents to be applied
	for {

		// - Get CPU Utilizations from host agents
		cpuUtilizationCh := make(chan NodeStats)
		for i := range nodes {
			msg := "getCPUUtilizations"
			go func(i int, node Node) {
				cpuUtilizations := node.SendMessageAndGetResponse(msg)
				cpuUtilizationCh <- NodeStats{i, cpuUtilizations, ""}
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
			nodes, nodeCPUUtilizations, roundsAppCPUUtils)
		roundsAppCPUUtils = newRoundsAppCPUUtils

		// log the CPU Utilizations and CPU Shares
		cpuLogFile.Writeln(getLogFileFormat(nodeCPUUtilizations, nodeCPUShares))

		// - Send the CPU shares to the host agents to be applied
		if nodeCPUShares == nil {
			slog.Warn("Failed to get optimal CPU shares")
		} else {
			for i := range nodes {
				nodeCPUShares[i] = strings.TrimSpace(nodeCPUShares[i])
				if nodeCPUShares[i] != "" {
					continue
				}
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

func makeNoiseZero(
	appUtils map[string]float64, noise float64) map[string]float64 {
	for appNum, util := range appUtils {
		if util < noise {
			appUtils[appNum] = 0
		}
	}
	return appUtils
}

func getOptimalCPUQuotas(
	nodeCPUUtilizations []string,
	roundsAppCPUUtils []map[string]float64) ([]string, []map[string]float64) {

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

func getOptimalLBWeights(
	nodes []Node,
	nodeCPUUtilizations []string,
	roundsAppCPUUtils []map[string]float64) (string, []map[string]float64) {

	// parse current cpu utilizations
	currentAppUtils := getPerAppUtilizations(nodeCPUUtilizations)
	// effectiveAppUtils := makeNoiseZero(currentAppUtils, NOISE)
	// effectiveAppUtils = addOverhead(effectiveAppUtils, OVERHEAD)

	// get rolling average
	avgAppUtils, newRoundsAppCPUUtils := getRollingAverage(
		currentAppUtils, roundsAppCPUUtils)

	// get weights from gurobi
	gurobiResponse := getGenericWeightsFromGurobi(nodes, avgAppUtils)

	// print Gurobi weights:
	fmt.Printf("Gurobi Response: %s\n", gurobiResponse)

	lbWeights := parseGurobiResponse(gurobiResponse)

	// return "profile:0.0|100.0 frontend:0.0|100.0 recommendation:100.0",
	// 	newRoundsAppCPUUtils

	return lbWeights, newRoundsAppCPUUtils
}

func getValuesFromMapSortedByKeys(m map[string]float64) []float64 {
	var keys []string
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	var values []float64
	for _, k := range keys {
		values = append(values, m[k])
	}
	return values
}

func parseGurobiResponse(gurobiResponse string) string {
	var response GurobiGenericResponse
	err := json.Unmarshal([]byte(gurobiResponse), &response)
	check(err)

	lbWeights := ""
	for appName, podResult := range response.Result {
		lbWeights += appName + ":"
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
		lbWeights += strings.Join(strSortedWeights, "|") + " "
	}
	return lbWeights
}

func getOptimalCPUShares(
	nodes []Node,
	nodeCPUUtilizations []string,
	roundsAppCPUUtils []map[string]float64) ([]string, []map[string]float64) {

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
	gurobiResponse := getGenericWeightsFromGurobi(nodes, avgAppUtils)

	// print Gurobi weights:
	fmt.Printf("Gurobi Response: %s\n", gurobiResponse)

	// get cpu shares
	nodeCPUShares := getNodeCPUShares(nodes, gurobiResponse)

	return nodeCPUShares, newRoundsAppCPUUtils
}

func addOverhead(
	appUtils map[string]float64, overhead float64) map[string]float64 {
	for appNum, util := range appUtils {
		if appNum == "app3" {
			appUtils[appNum] = util + overhead
		} else {
			appUtils[appNum] = util + overhead*2
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

type LogFileFormat struct {
	Time            int64                         `json:"time"`
	CPUUtilizations map[string]string             `json:"CPUUtilizations"`
	CPUShares       map[string]string             `json:"CPUShares"`
	CPUQuotas       map[string]string             `json:"CPUQuotas"`
	LBWeights       map[string]map[string]float64 `json:"LBWeights"`
}

func getCPUUtilMap(nodeCPUUtilizations []string) map[string]float64 {
	cpuUtilMap := make(map[string]float64)
	for _, nodeCPUUtil := range nodeCPUUtilizations {
		podCPUtils := strings.Split(nodeCPUUtil, " ")[1:]
		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName := podUtilMap[0]
			podUtil, err := strconv.ParseFloat(podUtilMap[1], 64)
			if err != nil {
				fmt.Printf("error here: %s", podCPUtils)
				check(err)
			}
			cpuUtilMap[podName] = podUtil
		}
	}
	return cpuUtilMap
}

func getLogFileFormatNoEnforcement(nodeCPUUtilizations []string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
		make(map[string]map[string]float64),
	}

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil, " ")[1:]

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

func getLogFileFormatLBEnforcement(
	nodeCPUUtilizations []string,
	lbWeightsStr string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
		make(map[string]map[string]float64),
	}

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil, " ")

		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName, podUtil := podUtilMap[0], podUtilMap[1]
			logFileFormat.CPUUtilizations[podName] = podUtil
		}
	}

	logFileFormat.LBWeights = parseLBWeightStr(lbWeightsStr)

	logFileFormatStr, err := json.Marshal(logFileFormat)
	check(err)

	return string(logFileFormatStr)
}

func parseLBWeightStr(lbWeightsStr string) map[string]map[string]float64 {

	lbWeights := make(map[string]map[string]float64)

	// example lbWeightsStr:
	// 		"profile:0.0|100.0 frontend:0.0|100.0 recommendation:100.0"
	lbWeightsStr = strings.TrimSpace(lbWeightsStr)
	appWeights := strings.Split(lbWeightsStr, " ")
	for _, appWeight := range appWeights {
		appWeightMap := strings.Split(appWeight, ":")
		appName := appWeightMap[0]
		weights := strings.Split(appWeightMap[1], "|")
		lbWeights[appName] = make(map[string]float64)
		for replicaNum, weight := range weights {
			lbWeights[appName][fmt.Sprintf("%s-%d", appName, replicaNum)] = stringToFloat(weight)
		}
	}

	return lbWeights
}

func stringToFloat(str string) float64 {
	f, err := strconv.ParseFloat(str, 64)
	check(err)
	return f
}

func getLogFileFormat(
	nodeCPUUtilizations []string, nodeCPUShares []string) string {

	logFileFormat := LogFileFormat{
		time.Now().UnixNano(),
		make(map[string]string),
		make(map[string]string),
		make(map[string]string),
		make(map[string]map[string]float64),
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

		nodeCPUShare = strings.TrimSpace(nodeCPUShare)
		if nodeCPUShare == "" {
			continue
		}

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
		make(map[string]map[string]float64),
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

type GurobiResponse struct {
	Status    int     `json:"status"`
	App1Node1 float64 `json:"t00"`
	App1Node2 float64 `json:"t01"`
	App2Node2 float64 `json:"t11"`
	App2Node3 float64 `json:"t12"`
	App3Node1 float64 `json:"t20"`
}

func getWeightsFromGurobi(
	hostCap float64, appUtils map[string]float64) string {

	baseURL := "http://localhost:5000"
	resource := "/"
	params := url.Values{}
	params.Add("host_cap", fmt.Sprintf("%f", hostCap))
	params.Add("t0", fmt.Sprintf("%f", appUtils["app1"]))
	params.Add("t1", fmt.Sprintf("%f", appUtils["app2"]))
	params.Add("t2", fmt.Sprintf("%f", appUtils["app3"]))

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

// JSON structs to send to the Gurobi Server
type HostJSON struct {
	Name string  `json:"name"`
	Cap  float64 `json:"cap"`
}
type TenantJSON struct {
	Name       string  `json:"name"`
	Load       float64 `json:"load"`
	FShareLoad float64 `json:"fshareload"`
}
type PodJSON struct {
	Name   string `json:"name"`
	Tenant string `json:"tenant"`
	Host   string `json:"host"`
}

func getFShareLoad(nodes []Node, appName string) float64 {
	totalUtil := 0.0
	for _, node := range nodes {
		slog.Info(fmt.Sprintf("checking node %s\n", node.Name))
		for _, pod := range node.Pods {
			// don't consider hostagents for gurobi calculations
			// if strings.Contains(pod.Name, "hostagent") {
			// 	continue
			// }
			if pod.AppName == appName {
				slog.Info(fmt.Sprintf("found pod %s util: %f\n", pod.Name, pod.FShare*float64(node.MilliCores)))
				totalUtil += pod.FShare * float64(node.MilliCores)
			}
		}
	}

	if totalUtil == 0 {
		panic("total util is 0 for app " + appName)
	}
	return totalUtil
}

type GurobiGenericResponse struct {
	Status int                           `json:"status"`
	Result map[string]map[string]float64 `json:"result"`
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

	baseURL := "http://localhost:5000/"
	payload := fmt.Sprintf(
		"[%s,%s,%s]", string(hostsJSON), string(tenantsJSON), string(podsJSON))

	slog.Info(fmt.Sprintf("Payload sending to Gurobi: %s\n", payload))

	resBody, err := sendPostRequest(baseURL, payload)
	check(err)

	return string(resBody)
}

func sendPostRequest(url, payload string) (string, error) {
	// Send the POST request
	response, err := http.Post(url, "application/json",
		bytes.NewBuffer([]byte(payload)))
	if err != nil {
		return "", err
	}
	// Ensure the response body is closed after the function returns
	defer response.Body.Close()

	// Check the response status
	if response.StatusCode != http.StatusOK {
		return "", errors.New("received non-201 status code")
	}

	// Read the response body
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return "", err
	}

	// Print the response body
	return string(body), nil
}

func getNodeNumOfPod(podName string, nodes []Node) (int, error) {
	for i, node := range nodes {
		for _, pod := range node.Pods {
			if pod.Name == podName {
				return i, nil
			}
		}
	}
	return -1, errors.New("Pod not found in nodes")
}

func getNodeCPUShares(nodes []Node, gurobiResponse string) []string {

	if USE_PRESET_SHARES {
		return getPresetCPUShares()
	}

	var response GurobiGenericResponse
	err := json.Unmarshal([]byte(gurobiResponse), &response)
	check(err)

	if response.Status != 2 {
		slog.Warn(fmt.Sprintf("gurobi returned status %d", response.Status))
		return nil
	} else {
		nodeCPUShares := make([]string, len(nodes))
		for _, podResult := range response.Result {
			for podName, share := range podResult {
				nodeNum, err := getNodeNumOfPod(podName, nodes)
				check(err)
				nodeCPUShares[nodeNum] += fmt.Sprintf("%s:%f ", podName, share)
			}
		}
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

func getNilWeights(appNames []string) string {
	lbWeights := ""
	for _, appName := range appNames {
		lbWeights += appName + ":nil "
	}
	lbWeights = strings.TrimSpace(lbWeights)
	return lbWeights
}

func setDefaultLBWeights(nodes []Node, appNames []string) {

	lbWeights := getNilWeights(appNames)

	for i := range nodes {
		msg := "applyLBWeights " + lbWeights
		response := nodes[i].SendMessageAndGetResponse(msg)
		if response != "Success" {
			slog.Warn("Failed to apply LB Weights on node: " +
				nodes[i].IP)
		}
	}
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

func setDefaultCPUShares(nodes []Node) {

	nodeCPUShares := getDefaultCPUShares(nodes)

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

func getDefaultCPUShares(nodes []Node) []string {

	CPUShares := make([]string, 0)

	for _, node := range nodes {
		nodeCPUShares := ""
		for _, pod := range node.Pods {
			// don't consider hostagents for setting cpu shares
			if strings.Contains(pod.Name, "hostagent") {
				continue
			}
			nodeCPUShares += fmt.Sprintf(
				"%s:%d ", pod.Name, int64(pod.FShare*1000))
		}
		nodeCPUShares = strings.TrimSpace(nodeCPUShares)
		CPUShares = append(CPUShares, nodeCPUShares)
	}

	return CPUShares
}

func getDefaultCPUQuotas() []string {
	return []string{
		"app1-node1:-1 app3-node1:-1",
		"app1-node2:-1 app2-node2:-1",
		"app2-node3:-1",
	}
}

func getPresetCPUShares() []string {
	// raise not implemented error
	check(errors.New("Preset CPU Shares not implemented"))
	return nil
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
