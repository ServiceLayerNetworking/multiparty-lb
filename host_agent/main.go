package main

import (
	"fmt"
	"io"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	CC_SERVER_HOST              = "localhost"
	CC_SERVER_PORT              = 9988
	CC_SERVER_TYPE              = "tcp"
	LB_SERVER_PORT              = 9989
	CPU_UTILIZATION_INTERVAL_MS = 500
	DEFAULT_LB_WEIGHTS          = ""
)

/*
What does this server do:

1. Listen for connections from CC
2. When a connection is received, handle the connection in a new goroutine
3. In the goroutine, read the message from the connection
4. If the message is an request to update the pod state, update agent's pod
	state, and send a success/failure response
	(state would contain list of podnames to uid mappings in the node)
4. If the message is a request for the server to apply CPU shares,
	apply the CPU shares in the kernel, and send a success/failure response
5. If the message is a request for the server to get CPU utilizations,
	send the CPU utilizations for each pod
6. Repeat from 3. indefinitely (until connection is closed)
*/

type SafeLBWeights struct {
	mu      sync.Mutex
	weights string
}

type ReqStat struct {
	SrcSvc      string `json:"srcSvc"`
	SrcPod      string `json:"srcPod"`
	DstSvc      string `json:"dstSvc"`
	DstPod      string `json:"dstPod"`
	StartTimeMs int64  `json:"startTimeMs"`
	EndTimeMs   int64  `json:"endTimeMs"`
}

type SafeReqStats struct {
	ReqStats []ReqStat `json:"reqStats"`
	mu       sync.Mutex
}

func main() {

	log.SetFlags(log.LstdFlags | log.Lmicroseconds)

	lbWeights := &SafeLBWeights{
		weights: DEFAULT_LB_WEIGHTS}
	reqStats := &SafeReqStats{
		ReqStats: make([]ReqStat, 0)}
	sentReqStats := &SafeReqStats{
		ReqStats: make([]ReqStat, 0)}

	// start the server that will communicate with the central controller
	go startServerForCC(lbWeights, reqStats, sentReqStats)

	// listen for requests from the load balancer for updating its weights
	listenForReqsFromLB(lbWeights, reqStats, sentReqStats)
}

func startServerForCC(
	lbWeights *SafeLBWeights,
	reqStats *SafeReqStats,
	sentReqStats *SafeReqStats) {

	fmt.Println("Server Running...")

	server, err := net.Listen(
		CC_SERVER_TYPE, fmt.Sprintf(":%d", CC_SERVER_PORT))
	if err != nil {
		fmt.Println("Error listening:", err.Error())
		os.Exit(1)
	}

	defer server.Close()

	fmt.Println(
		"Listening on " + CC_SERVER_HOST + fmt.Sprintf(":%d", CC_SERVER_PORT))
	fmt.Println("Waiting for client...")

	for {
		connection, err := server.Accept()
		if err != nil {
			fmt.Println("Error accepting: ", err.Error())
			os.Exit(1)
		}
		fmt.Println("client connected")
		go processClient(connection, lbWeights, reqStats, sentReqStats)
	}

}

func listenForReqsFromLB(
	lbWeights *SafeLBWeights,
	reqStats *SafeReqStats,
	sentReqStats *SafeReqStats) {
	// listen for http requests at a specific port
	// and update the LB weights

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Header().Set("Connection", "close")

		lbWeights.mu.Lock()
		currLBWeights := lbWeights.weights
		lbWeights.mu.Unlock()

		// get post body
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Error reading request body",
				http.StatusInternalServerError)
			return
		}
		fmt.Println("Received request: " + string(body))

		// update the request stats
		updateRequestStats(reqStats, sentReqStats, string(body))

		fmt.Fprint(w, currLBWeights)
	})

	fmt.Printf(
		"Server running (port=%d), route: http://localhost:%d\n",
		LB_SERVER_PORT, LB_SERVER_PORT)

	if err := http.ListenAndServe(fmt.Sprintf(":%d", LB_SERVER_PORT), nil); err != nil {
		log.Fatal(err)
	}

}

func updateRequestStats(
	reqStats *SafeReqStats,
	sentReqStats *SafeReqStats,
	reqStatsStr string) error {

	/* Example reqStatsStr
	profile profile-0
	reqCount
	8
	timestampstats
	........
	profile 1721841927366 1721841927374
	profile 1721841927415 1721841927422
	profile 1721841927463 1721841927470
	profile 1721841927510 1721841927515
	profile 1721841927552 1721841927559
	profile 1721841927593 1721841927599
	profile 1721841927636 1721841927644
	profile 1721841927682 1721841927688
	profile 1721841927724 1721841927728
	*/

	//

	// parse the request stats and update the state

	newReqCompletedStats := make([]ReqStat, 0)

	// trim the string
	reqStatsStr = strings.TrimSpace(reqStatsStr)
	// get lines
	lines := strings.Split(reqStatsStr, "\n")
	if len(lines) < 5 {
		// no request stats to parse
		return nil
	}
	// get the src
	src := strings.Split(lines[0], " ")
	srcSvc := src[0]
	srcPod := src[1]

	// get the reqStats
	sentReqLineNum := -1

	lineNum := 5

	for _, line := range lines[5:] {

		// breakpoint for sentreqstats
		if line == "sentreqstats" {
			sentReqLineNum = lineNum
			break
		}
		lineNum++

		lineStats := strings.Split(line, " ")
		if len(lineStats) < 4 {
			fmt.Println("Error parsing reqstats line: ", line)
			continue
		}
		dstSvc := lineStats[0]
		dstPod := lineStats[1]
		startTimeStr := lineStats[2]
		endTimeStr := lineStats[3]
		startTime, err := strconv.ParseInt(startTimeStr, 10, 64)
		if err != nil {
			fmt.Println("Error parsing startTime: ", err.Error())
			return err
		}
		endTime, err := strconv.ParseInt(endTimeStr, 10, 64)
		if err != nil {
			fmt.Println("Error parsing endTime: ", err.Error())
			return err
		}
		newReqCompletedStats = append(newReqCompletedStats, ReqStat{
			SrcSvc:      srcSvc,
			SrcPod:      srcPod,
			DstSvc:      dstSvc,
			DstPod:      dstPod,
			StartTimeMs: startTime,
			EndTimeMs:   endTime,
		})
	}

	newReqSentStats := make([]ReqStat, 0)
	for _, line := range lines[sentReqLineNum+1:] {
		// example line: `dstSvc dstPod startTime`
		lineStats := strings.Split(line, " ")
		if len(lineStats) < 3 {
			fmt.Println("Error parsing sentReqStats line: ", line)
			continue
		}
		dstSvc := lineStats[0]
		dstPod := lineStats[1]
		startTimeStr := lineStats[2]
		startTime, err := strconv.ParseInt(startTimeStr, 10, 64)
		if err != nil {
			fmt.Println("Error parsing startTime: ", err.Error())
			return err
		}
		newReqSentStats = append(newReqSentStats, ReqStat{
			SrcSvc:      srcSvc,
			SrcPod:      srcPod,
			DstSvc:      dstSvc,
			DstPod:      dstPod,
			StartTimeMs: startTime,
			EndTimeMs:   -1,
		})
	}

	reqStats.mu.Lock()
	reqStats.ReqStats = append(reqStats.ReqStats, newReqCompletedStats...)
	// slog.Info("Updated reqStats: " + fmt.Sprintf("%v", reqStats.ReqStats))

	// only keep the most recent 10000 entries
	if len(reqStats.ReqStats) > 10000 {
		reqStats.ReqStats = reqStats.ReqStats[len(reqStats.ReqStats)-1000:]
	}
	reqStats.mu.Unlock()

	sentReqStats.mu.Lock()
	sentReqStats.ReqStats = append(sentReqStats.ReqStats, newReqSentStats...)
	// slog.Info("Updated sentReqStats: " + fmt.Sprintf("%v", sentReqStats.ReqStats))

	// only keep the most recent 10000 entries
	if len(sentReqStats.ReqStats) > 10000 {
		sentReqStats.ReqStats = sentReqStats.ReqStats[len(sentReqStats.ReqStats)-1000:]
	}
	sentReqStats.mu.Unlock()

	return nil
}

func processClient(
	connection net.Conn,
	lbWeights *SafeLBWeights,
	reqStats *SafeReqStats,
	sentReqStats *SafeReqStats) {

	defer connection.Close()

	podUIDs := make(map[string]string)

	for {

		msgFromCC, err := readMsgFromConnection(connection)
		if err != nil {
			fmt.Println("Error reading:", err.Error())
			break
		}
		slog.Info("Received: " + msgFromCC)

		msgType := strings.Split(msgFromCC, " ")[0]

		if msgType == "updatePods" {
			newPodUIDs, ok := getNewPods(msgFromCC)
			if ok {
				podUIDs = newPodUIDs
			}
			sendSuccessOrFailResponse(connection, ok)

		} else if msgType == "applyLBWeights" {
			ok := updateLBWeights(podUIDs, msgFromCC, lbWeights)
			sendSuccessOrFailResponse(connection, ok)

		} else if msgType == "applyCPUShares" {
			ok := applyCPUShares(podUIDs, msgFromCC)
			sendSuccessOrFailResponse(connection, ok)

		} else if msgType == "applyCPUQuotas" {
			ok := applyCPUQuotas(podUIDs, msgFromCC)
			sendSuccessOrFailResponse(connection, ok)

		} else if msgType == "getCPUUtilizations" {
			cpuUtilizations := getCPUUtilizations(podUIDs)
			sendMsgToConnection(connection, cpuUtilizations)

		} else if msgType == "getCPUUtilsAndReqStats" {
			cT := time.Now()
			cpuUtilizations := getCPUUtilizations(podUIDs)
			fmt.Printf("Time to get CPU utils: %.2f ms\n", float64(time.Since(cT).Microseconds())/1000.0)
			cT = time.Now()
			reqStatsStr, sentReqStatsStr := getReqStatsStr(reqStats, sentReqStats)
			fmt.Printf("Time to get Req stats: %.2f ms\n", float64(time.Since(cT).Microseconds())/1000.0)
			toSend := cpuUtilizations + "\n<SEP>\n" + reqStatsStr + "\n<SEP>\n" + sentReqStatsStr
			sendMsgToConnection(connection, toSend)

		} else {
			// unknown message type
			sendMsgToConnection(connection, "Unknown message type")
		}
	}

	slog.Warn("Client disconnected")
}

func getAndResetReqStats(statName string, reqStats *SafeReqStats) string {

	reqStats.mu.Lock()
	defer reqStats.mu.Unlock()

	reqStatsStr := statName + ":"
	for _, reqStat := range reqStats.ReqStats {
		reqStatsStr += fmt.Sprintf(
			"\n%s %s %s %s %d %d",
			reqStat.SrcSvc, reqStat.SrcPod,
			reqStat.DstSvc, reqStat.DstPod,
			reqStat.StartTimeMs, reqStat.EndTimeMs)
	}

	reqStats.ReqStats = make([]ReqStat, 0)

	return reqStatsStr
}

func getReqStatsStr(reqStats, sentReqStats *SafeReqStats) (string, string) {

	reqStatsStr := getAndResetReqStats("reqStats", reqStats)
	sentReqStatsStr := getAndResetReqStats("sentReqStats", sentReqStats)

	return reqStatsStr, sentReqStatsStr
}

func getNewPods(msg string) (map[string]string, bool) {
	// parse the message and update the state
	// return true if successful, false otherwise

	// example message to parse: "updateState pod1:uid1 pod2:uid2"

	podUIDs := make(map[string]string)
	podStrs := strings.Split(msg, " ")[1:]
	for _, podStr := range podStrs {
		podNameToUID := strings.Split(podStr, ":")
		if len(podNameToUID) != 2 {
			return podUIDs, false
		}
		podUIDs[podNameToUID[0]] = podNameToUID[1]
	}

	slog.Info("Updated pods: " + fmt.Sprintf("%v", podUIDs))

	return podUIDs, true
}

func applyCPUQuotas(podUIDs map[string]string, msg string) bool {
	// parse the message and apple CPU quota
	// return true if successful, false otherwise

	podQuotas, ok := parsePodShares(msg)
	if !ok {
		return false
	}

	for podName, share := range podQuotas {

		fileName := "/host/sys/fs/cgroup/cpu/kubepods/" +
			podUIDs[podName] + "/cpu.cfs_quota_us"
		// fileName := "/Users/twaheed2/go/src/host_agent/" +
		// 	podUIDs[podName]

		// err := os.WriteFile(fileName, []byte(share+"\n"), 0644)
		// if err != nil {
		// 	slog.Warn(err.Error())
		// 	return false
		// }

		slog.Info(fmt.Sprintf("%s %s %s %s",
			"bash", "./writetofile.sh", share, fileName))

		cmd := exec.Command("bash", "./writetofile.sh", share, fileName)
		_, err := cmd.Output()
		if err != nil {
			slog.Warn(err.Error())
			return false
		}
	}

	slog.Info("Applied CPU shares: " + fmt.Sprintf("%v", podQuotas))

	return true
}

func updateLBWeights(
	podUIDs map[string]string, msg string, lbWeights *SafeLBWeights) bool {
	// parse the message and update lb weights
	// return true if successful, false otherwise

	// newLBWeights, ok := parseLBWeights(msg)
	// if !ok {
	// 	return false
	// }

	lbWeights.mu.Lock()
	lbWeights.weights = msg
	lbWeights.mu.Unlock()

	slog.Info("Updated LB weights: " + msg)

	return true
}

func applyCPUShares(podUIDs map[string]string, msg string) bool {
	// parse the message and apple CPU shares
	// return true if successful, false otherwise

	podShares, ok := parsePodShares(msg)
	if !ok {
		return false
	}

	for podName, share := range podShares {

		uid := podUIDs[podName]
		fileName := "/host/sys/fs/cgroup/kubepods.slice/" + uid + "/cpu.weight"
		// fileName := "/Users/twaheed2/go/src/host_agent/" +
		// 	podUIDs[podName]

		// err := os.WriteFile(fileName, []byte(share+"\n"), 0644)
		// if err != nil {
		// 	slog.Warn(err.Error())
		// 	return false
		// }

		slog.Info(fmt.Sprintf("%s %s %s %s",
			"bash", "./writetofile.sh", share, fileName))

		cmd := exec.Command("bash", "./writetofile.sh", share, fileName)
		output, err := cmd.Output()

		if err != nil {
			slog.Info(fmt.Sprintf("Error: %s\n", err.Error()))
			return false
		} else {
			slog.Info("Output: " + string(output))
		}
	}

	slog.Info("Applied CPU shares: " + fmt.Sprintf("%v", podShares))

	return true
}

func parsePodShares(msg string) (map[string]string, bool) {

	// example message to parse: "applyCPUShares pod1:45 pod2:69"

	msg = strings.TrimSpace(msg)
	podShares := make(map[string]string)
	podStrs := strings.Split(msg, " ")[1:]
	for _, podStr := range podStrs {
		podNameToShare := strings.Split(podStr, ":")
		if len(podNameToShare) != 2 {
			return podShares, false
		}
		share, err := strconv.ParseFloat(podNameToShare[1], 64)
		if err != nil {
			return podShares, false
		}
		podShares[podNameToShare[0]] = fmt.Sprintf("%d", int64(share))
	}

	return podShares, true
}

func parseLBWeights(msg string) (map[string]float64, bool) {

	// example message to parse: "updateLBWeights svcA:45.5|69.22 svcB:54.7|44.1"

	weights := make(map[string]float64)
	podStrs := strings.Split(msg, " ")[1:]
	for _, podStr := range podStrs {
		podNameToShare := strings.Split(podStr, ":")
		if len(podNameToShare) != 2 {
			return weights, false
		}
		share, err := strconv.ParseFloat(podNameToShare[1], 64)
		if err != nil {
			return weights, false
		}
		weights[podNameToShare[0]] = share
	}

	return weights, true
}

func getOSFileFirstLine(readPath string) (string, error) {

	// Reliable, but really really slow.
	out, err := exec.Command("head", "-1", readPath).Output()
	return string(out), err
}

func getOSFile(readPath string) (string, error) {

	// Reliable, but really really slow.
	out, err := exec.Command("cat", readPath).Output()
	return string(out), err

	// file, err := os.Open(readPath)
	// if err != nil {
	// 	fmt.Printf("Error opening file: %v\n", err)
	// 	return "", err
	// }
	// defer file.Close()

	// readBuf := make([]byte, 4096)
	// readFile := file

	// // Seek should tell us the new offset (0) and no err.
	// bytesRead := 0
	// _, err = readFile.Seek(0, 0)

	// // Loop until N > 0 AND err != EOF && err != timeout.
	// if err == nil {
	// 	n := 0
	// 	for {
	// 		n, err = readFile.Read(readBuf)
	// 		bytesRead += n
	// 		if os.IsTimeout(err) {
	// 			// bail out.
	// 			bytesRead = 0
	// 			break
	// 		}
	// 		if err == io.EOF {
	// 			// Success!
	// 			break
	// 		}
	// 		// Any other err means 'keep trying to read.'
	// 	}
	// }

	// return string(readBuf), err
}

// blocking, to be called asynchonously in go routine
func fetchPodCPUUtil(podName string, uid string, respChan chan string) {

	initialCPUUtil := getPodCurrentCPUUsageTime(uid)
	intialTime := time.Now().UnixMicro()

	time.Sleep(CPU_UTILIZATION_INTERVAL_MS * time.Millisecond)

	finalCPUUtil := getPodCurrentCPUUsageTime(uid)
	timeElapsed := time.Now().UnixMicro() - intialTime

	respChan <- fmt.Sprintf("%s:%f",
		podName,
		(float64(finalCPUUtil-initialCPUUtil)/
			float64(timeElapsed))*100)
}

func getCPUUtilizations(podUIDs map[string]string) string {

	response := "utils:"

	respChan := make(chan string, len(podUIDs))

	// fetch CPU utilization for each pod
	for podName, uid := range podUIDs {
		go fetchPodCPUUtil(podName, uid, respChan)
	}

	// append them to the response
	for range podUIDs {
		response += <-respChan + " "
	}

	// strip response
	response = strings.TrimSpace(response)

	return response
}

// // pathExists checks if a given path exists and is either a file or a directory.
// func pathExists(path string) bool {
// 	_, err := os.Stat(path)
// 	if os.IsNotExist(err) {
// 		return false
// 	}
// 	return err == nil
// }

// func getPodcgroupFilePath(uid string) string {
// 	qosClass := []string{"burstable/", "besteffort/", ""}
// 	for _, class := range qosClass {
// 		fileName := "/sys/fs/cgroup/cpu/kubepods/" + class + "pod" + uid
// 		if pathExists(fileName) {
// 			return fileName
// 		} else {
// 			slog.Warn("No cgroup path found: " + fileName)
// 		}
// 	}
// 	slog.Warn("No cgroup file found for pod: " + uid)
// 	return "/sys/fs/cgroup/cpu/kubepods/" + qosClass[0] + "pod" + uid
// }

func getPodCurrentCPUUsageTime(uid string) int64 {
	// get the CPU utilization of the pod
	// return the CPU utilization

	// read the file and return the value
	fileName := "/host/sys/fs/cgroup/kubepods.slice/" + uid + "/cpu.stat"

	cpuUtil, err := getOSFileFirstLine(fileName)
	if err != nil {
		slog.Warn(
			fmt.Sprintf("error in reading OS file %s: %s", fileName, err.Error()))
		return -1
	}

	slog.Info("CPU Utilization [" + uid + "]: \"" + cpuUtil + "\"")

	cpuUtilStr := strings.Trim(cpuUtil, "\n")
	cpuUtilStr = strings.Split(cpuUtilStr, " ")[1]

	cpuUtilInt64, err := strconv.ParseInt(cpuUtilStr, 10, 64)
	if err != nil {
		slog.Warn(err.Error())
		return -1
	}

	return cpuUtilInt64
}

func sendSuccessOrFailResponse(connection net.Conn, ok bool) {
	if ok {
		sendMsgToConnection(connection, "Success")
	} else {
		sendMsgToConnection(connection, "Failure")
	}
}

func readMsgFromConnection(connection net.Conn) (string, error) {
	var fullMessage strings.Builder
	buffer := make([]byte, 64*1024) // 64KB buffer
	
	for {
		mLen, err := connection.Read(buffer)
		if err != nil {
			if err == io.EOF && fullMessage.Len() > 0 {
				break
			}
			return "", err
		}
		
		fullMessage.Write(buffer[:mLen])
		
		// Check if we've received the complete message
		// (if less than buffer size, likely the end of message)
		if mLen < len(buffer) {
			break
		}
	}
	
	return fullMessage.String(), nil
}

func sendMsgToConnection(connection net.Conn, msg string) {
	msg = msg + "<END>"
	_, err := connection.Write([]byte(msg))
	if err != nil {
		fmt.Println("Error writing:", err.Error())
	} else {
		slog.Info("Sent: \"" + msg + "\"")
	}
}
