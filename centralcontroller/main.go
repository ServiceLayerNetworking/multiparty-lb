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
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	CFS_PERIOD_US     = 100000
	CPUS_IN_NODE      = 200
	MINIMUM_CPU_QUOTA = 1000

	SERVER_PORT = "9988"
	SERVER_TYPE = "tcp"

	ECHO_SERVER_PORT = "5656"

	ROUNDS_FOR_ROLLING_AVG_OF_CPU_UTILS = 5
	NUM_OF_SEC_FOR_ROLLING_AVG_OF_RPS   = 10 // Number of seconds for rolling average of RPS

	NUM_OF_SECS_FOR_REQ_STATS = 5    // Number of seconds of past request stats to consider
	INIT_HEADROOM_PCT         = 10.0 // Initial headroom percentage for each service
	MINIMUM_HEADROOM_PCT      = 0.0  // Minimum headroom percentage for each service
	DELTA_HEADROOM_PCT        = 5.0  // Change in headroom percentage for each service

	NODE_CAP_SCALE_FACTOR = 1
	M_CPUS_IN_NODE        = 2000 * NODE_CAP_SCALE_FACTOR

	USE_RPS_INSTEAD_OF_CPU      = true
	USE_OFFLINE_DEMAND_ESTIMATE = false
	CPU_CONSUMPTION_PER_REQ     = 3.0
	SVC_CPU_UTIL_HEADROOM       = 0    // deprecated
	RPS_WINDOW_MS               = 1000 // 500ms window to look for how many requests are sent and base our CPU off of that
	SVC_UTIL_SCALE_FACTOR       = 1    // by this factor, scale the cpuutil
	CPU_PER_REQ_SCALE_FACTOR    = 1    // by this factor, scale the cpuconsumptionperreq

	// these are deprecated
	OVERHEAD           = 10 // 10% overhead
	POD_QUOTA_OVERHEAD = 10 // 5% overhead
	NOISE              = 2  // 2% noise
	ENFORCEMENT        = "LB"
	USE_PRESET_SHARES  = false

	DEFAULT_LB_WEIGHTS = ""
	LOG_FILE_PREFIX    = "/users/twaheed/multiparty-lb"

	GUROBI_PORT = "4876"
	GUROBI_URL  = "http://localhost:" + GUROBI_PORT + "/"

	SUPPRESS_CPU_STATS_PRINTING = false
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
	NodeName       string
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
	ReqSentStats    string
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
			"%s/%s/%s_%s_%d", LOG_FILE_PREFIX, filename, *enforcement, "cc", runNum)
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

type ReqStatsServer struct {
	serviceOutstandingRequests *ServiceOutstandingRequests
	serviceLatencyStats        *ServiceLatencyStats
	serviceArrivingRPS         *ServiceArrivingRPS
}

func NewReqStatsServer() *ReqStatsServer {
	return &ReqStatsServer{
		serviceOutstandingRequests: NewServiceOutstandingRequests(),
		serviceLatencyStats:        NewServiceLatencyStats(),
		serviceArrivingRPS:         NewServiceArrivingRPS(),
	}
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
	setNilLBWeights(nodes, appNames)

	// Set default CPU Shares
	setDefaultCPUShares(nodes)

	// Setup the Echo Service
	if err := k8sClient.SetupEchoService(); err != nil {
		log.Fatalf("Failed to set up Kubernetes Service and Endpoint: %v", err)
	}
	// Get the ingress gateway URLs
	ingressGatewayURLs := k8sClient.GetIngressGatewayURLs()
	fmt.Printf("Ingress Gateway URLs: %v\n", ingressGatewayURLs)

	// Start the Echo Server
	reqStatsServer := NewReqStatsServer()
	go echoServer(
		ingressGatewayURLs,
		reqStatsServer.serviceOutstandingRequests,
		reqStatsServer.serviceArrivingRPS,
		reqStatsServer.serviceLatencyStats)

	// get pods to log
	podNamesToLog := getPodsToLog(podNames)

	if enforcement == "NONE" {
		go ccWithNoEnforcement(cpuLogFile, nodes, podNamesToLog)

	} else {

		if enforcement == "LB" {

			go ccWithLBEnforcement(cpuLogFile, nodes, appNames, podNamesToLog, reqStatsServer)

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
		nodeCPUUtilizations, reqStats, _ := getCPUUtilAndReqStatsFromCluster(nodes)

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

func parseCPUUtilsAndReqStats(resp string) (string, string, string, error) {
	parts := strings.Split(resp, "\n<SEP>\n")
	if len(parts) != 3 {
		return "", "", "", errors.New(
			"invalid response from host agent: " + resp)
	}
	return parts[0], parts[1], parts[2], nil
}

func parseReqStats(reqStatsStr string) []ReqStat {

	// fmt.Printf("ReqStatsStr: %s\n", reqStatsStr)

	reqStats := make([]ReqStat, 0)
	reqStatsStr = strings.TrimSpace(reqStatsStr)
	if reqStatsStr == "reqStats:" || reqStatsStr == "sentReqStats:" {
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

func getCPUUtilAndReqStatsFromCluster(nodes []Node) ([]string, []ReqStat, []ReqStat) {

	// - Get CPU Utilizations from host agents
	cpuUtilizationCh := make(chan NodeStats)
	for i := range nodes {
		msg := "getCPUUtilsAndReqStats"
		go func(i int, node Node) {
			resp := node.SendMessageAndGetResponse(msg)
			cpuUtils, reqStats, reqSentStats, err := parseCPUUtilsAndReqStats(resp)
			if err != nil {
				slog.Error(fmt.Sprintf("Failed to parse CPU Utilizations and ReqStats from Node %d: %s", i, err.Error()))
				panic(err)
			}
			cpuUtilizationCh <- NodeStats{i, cpuUtils, reqStats, reqSentStats}
		}(i, nodes[i])
	}
	reqStats := make([]ReqStat, 0)
	reqSentStats := make([]ReqStat, 0)
	nodeCPUUtilizations := make([]string, len(nodes))
	for range nodes {
		nodeStats := <-cpuUtilizationCh
		nodeCPUUtilizations[nodeStats.Node] = nodeStats.CPUUtilizations
		reqStats = append(reqStats, parseReqStats(nodeStats.ReqStats)...)
		reqSentStats = append(reqSentStats, parseReqStats(nodeStats.ReqSentStats)...)
		slog.Info(fmt.Sprintf("CPU Utilizations [Node %d]: %s",
			nodeStats.Node, nodeStats.CPUUtilizations))
	}

	return nodeCPUUtilizations, reqStats, reqSentStats
}

func ccWithLBEnforcement(
	cpuLogFile *LogFile, nodes []Node, appNames []string, podsToLog []string,
	reqStatsServer *ReqStatsServer) {

	// Initialize cluster state
	cs := ClusterStateManager{}
	cs.Initialize(nodes, appNames)

	// Initialize the Demand Estimator
	de := DemandEstimator{}
	de.Initialize()

	// set initial LB weights
	setInitialLBWeights(nodes, appNames)

	// Repeat the following:
	// - Get CPU Utilizations from host agents
	for {

		// Get CPU Utilizations and Request Stats from host agents
		nodeCPUUtilizations, reqStats, reqSentStats := getCPUUtilAndReqStatsFromCluster(nodes)

		// update the state in the demand estimator and get demand estimates
		de.UpdateState(getPerAppUtilizations(nodeCPUUtilizations), reqStats)
		svcCPUConsumptionPerReq := de.GetDemandEstimates(reqStatsServer)

		// - Solve the optimization problem by connection to Gurobi Optimizer
		lbWeights := cs.GetOptimalLBWeights(
			nodeCPUUtilizations,
			reqStats,
			reqSentStats,
			reqStatsServer,
			svcCPUConsumptionPerReq)

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
	// sortedPodsToLog := getKeysSortedByValue(cpuUtilMap, podsToLog)
	sort.Strings(podsToLog)
	for _, podName := range podsToLog {
		toPrint += fmt.Sprintf("%-30s %.2f\n",
			podName, cpuUtilMap[podName])
	}
	if !SUPPRESS_CPU_STATS_PRINTING {
		fmt.Printf("%s\n", toPrint)
	}
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
		nodeCPUUtilizations, reqStats, _ := getCPUUtilAndReqStatsFromCluster(nodes)

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
				cpuUtilizationCh <- NodeStats{i, cpuUtilizations, "", ""}
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
				cpuUtilizationCh <- NodeStats{i, cpuUtilizations, "", ""}
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

type LBStat struct {
	CPUConsumptionPerReq float64            `json:"CPUConsumptionPerReq"`
	CPUAllocated         float64            `json:"CPUAllocated"`
	Weights              map[string]float64 `json:"Weights"`
}

type LogFileFormat struct {
	Time            int64             `json:"time"`
	CPUUtilizations map[string]string `json:"CPUUtilizations"`
	CPUShares       map[string]string `json:"CPUShares"`
	CPUQuotas       map[string]string `json:"CPUQuotas"`
	LBStats         map[string]LBStat `json:"LBStats"`
}

func getCPUUtilMap(nodeCPUUtilizations []string) map[string]float64 {
	cpuUtilMap := make(map[string]float64)
	for _, nodeCPUUtil := range nodeCPUUtilizations {
		podCPUtils := strings.Split(nodeCPUUtil[6:], " ")
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
		make(map[string]LBStat),
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
		make(map[string]LBStat),
	}

	fmt.Println("Node CPU Utilizations[0]: ", nodeCPUUtilizations[0])

	for _, nodeCPUUtil := range nodeCPUUtilizations {

		podCPUtils := strings.Split(nodeCPUUtil[6:], " ")

		for _, podCPUUtil := range podCPUtils {
			podUtilMap := strings.Split(podCPUUtil, ":")
			podName, podUtil := podUtilMap[0], podUtilMap[1]
			logFileFormat.CPUUtilizations[podName] = podUtil
		}
	}

	logFileFormat.LBStats = parseLBWeightStr(lbWeightsStr)

	logFileFormatStr, err := json.Marshal(logFileFormat)
	if err != nil {
		fmt.Printf("Couldn't marshal logFileFormat: %v\n", logFileFormat)
	}
	check(err)

	return string(logFileFormatStr)
}

func parseLBWeightStr(lbWeightsStr string) map[string]LBStat {

	lbWeights := make(map[string]LBStat)

	// example lbWeightsStr:
	// 		"profile:45.0:450.3:0.0|100.0 frontend:45.0:450.3:0.0|100.0 recommendation:45.0:450.3:100.0"
	lbWeightsStr = strings.TrimSpace(lbWeightsStr)
	appWeights := strings.Split(lbWeightsStr, " ")
	for _, appWeight := range appWeights {
		appWeightMap := strings.Split(appWeight, ":")
		if len(appWeightMap) != 5 {
			panic("Invalid lbWeightsStr: " + lbWeightsStr)
		}
		appName := appWeightMap[0]
		cpuConsumptionPerReq := stringToFloat(appWeightMap[1])
		cpuAllocated := stringToFloat(appWeightMap[2])
		weights := strings.Split(appWeightMap[3], "|")
		lbWeights[appName] = LBStat{
			cpuConsumptionPerReq,
			cpuAllocated,
			make(map[string]float64),
		}
		for replicaNum, weight := range weights {
			lbWeights[appName].Weights[fmt.Sprintf("%s-%d", appName, replicaNum)] = stringToFloat(weight)
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
		make(map[string]LBStat),
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
		make(map[string]LBStat),
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

	baseURL := GUROBI_URL
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
				fShare := pod.FShare * float64(node.MilliCores) / 10.0
				slog.Info(fmt.Sprintf("found pod %s util: %f\n", pod.Name, fShare))
				totalUtil += fShare
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

func getEqualWeightsForEachPod(nodes []Node, appNames []string) string {
	appNumOfPods := make(map[string]int)
	for _, appName := range appNames {
		appNumOfPods[appName] = 0
	}
	for _, node := range nodes {
		for _, pod := range node.Pods {
			appNumOfPods[pod.AppName]++
		}
	}

	lbWeights := ""
	for _, appName := range appNames {
		lbWeights += appName + ":"
		for i := 0; i < appNumOfPods[appName]; i++ {
			lbWeights += fmt.Sprintf(
				"%.1f|", 100.0/float64(appNumOfPods[appName]))
		}
		lbWeights = lbWeights[:len(lbWeights)-1] + " "
	}

	lbWeights = strings.TrimSpace(lbWeights)
	return lbWeights
}

func setNilLBWeights(nodes []Node, appNames []string) {

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

func setInitialLBWeights(nodes []Node, appNames []string) {

	lbWeights := getEqualWeightsForEachPod(nodes, appNames)

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
