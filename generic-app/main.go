package main

import (
	"flag"
	"fmt"
	"log"
	"math"
	"math/rand"
	"net/http"
	"os"
	"runtime"
	"strconv"
	"syscall"
	"time"
)

func runCPULoad(millicores int, timeMillis int) {
	if millicores == 0 {
		return
	}

	cpuPct := millicores / 10
	runFor := time.Duration(1000*cpuPct) * time.Microsecond
	sleepFor := time.Duration(1000*(100-cpuPct)) * time.Microsecond
	fmt.Printf("Worker sleepFor %s, runFor %s\n", sleepFor.String(), runFor.String())
	runtime.LockOSThread()
	// every milliseconds, run for runMicrosecond microseconds, and sleep for sleepMicrosecond microseconds

	ch := time.After(time.Duration(timeMillis) * time.Millisecond)
startLoop:
	for {
		select {
		case <-ch:
			runtime.UnlockOSThread()
			return
		default:
			begin := time.Now()
			for {
				select {
				case <-ch:
					fmt.Printf("Done\n")
					runtime.UnlockOSThread()
					return
				default:
					if time.Since(begin) > runFor {
						for {
							select {
							case <-ch:
								fmt.Printf("Done\n")
								runtime.UnlockOSThread()
								return
							case <-time.After(sleepFor):
								continue startLoop
							}
						}
					}

				}
			}
		}
	}
}

func runCPUBudgetFair(threadID int, targetMillis int) {
	target := time.Duration(targetMillis) * time.Millisecond
	totalUsed := time.Duration(0)

	fmt.Printf("[Thread %d] Starting. Target: %v\n", threadID, target)

	for totalUsed < target {
		runtime.LockOSThread()

		start := getThreadCPUTime()
		// Do a short burst of CPU work (~few ms)
		workUntil := time.Now().Add(1 * time.Millisecond)
		for time.Now().Before(workUntil) {
			for i := 0; i < 10000; i++ {
				_ = i * i
			}
		}
		end := getThreadCPUTime()
		runtime.UnlockOSThread()

		// Accumulate CPU time used by this burst
		burstUsed := end - start
		totalUsed += burstUsed

		// Yield to scheduler to let others run
		runtime.Gosched()
	}

	fmt.Printf("[Thread %d] Done. CPU used: %v\n", threadID, totalUsed)
}

func getThreadCPUTime() time.Duration {
	var ru syscall.Rusage
	_ = syscall.Getrusage(syscall.RUSAGE_THREAD, &ru)
	utime := time.Duration(ru.Utime.Sec)*time.Second + time.Duration(ru.Utime.Usec)*time.Microsecond
	stime := time.Duration(ru.Stime.Sec)*time.Second + time.Duration(ru.Stime.Usec)*time.Microsecond
	return utime + stime
}

func processRequest(totalLoopCount, base, exp float64) float64 {
	resultSum := 0.0
	for loopCount := 0.0; loopCount < totalLoopCount; loopCount++ {
		result := 0.0
		for i := math.Pow(base, exp); i >= 0; i-- {
			result += math.Atan(i) // * math.Tan(i)
		}
		resultSum += result
	}
	return resultSum
}

func convParamsToFloat(loopCount string, base string, exp string) (float64, float64, float64, bool) {
	loopCountFloat, err1 := strconv.ParseFloat(loopCount, 64)
	baseFloat, err2 := strconv.ParseFloat(base, 64)
	expFloat, err3 := strconv.ParseFloat(exp, 64)
	isErr := err1 != nil || err2 != nil || err3 != nil
	if isErr {
		fmt.Println(err1, ", ", err2, ", ", err3)
	}
	return loopCountFloat, baseFloat, expFloat, isErr
}

func getHostName() string {
	hostname, err := os.Hostname()
	if err != nil {
		return err.Error()
	}
	return hostname
}

func respondWithError(
	w http.ResponseWriter,
	loopCount string,
	base string,
	exp string,
	numOutstandingReqs int64,
	timeOutStandingReqs int64) {

	w.WriteHeader(http.StatusBadRequest)
	w.Header().Set("Connection", "close")
	fmt.Fprintf(
		w,
		"Error at %s w/ loopCount=%s & compute=(%s,%s) (outstanding requests: %d at %d)",
		getHostName(), loopCount, base, exp, numOutstandingReqs, timeOutStandingReqs)
}

func respondWithSuccess(
	w http.ResponseWriter,
	loopCount string,
	base string,
	exp string,
	reqResult float64,
	numOutstandingReqs int64,
	timeOutStandingReqs int64) {

	w.WriteHeader(http.StatusOK)
	w.Header().Set("Connection", "close")
	fmt.Fprintf(
		w,
		"Processed at %s w/ loopCount=%s & compute=(%s,%s) => %f (outstanding requests: %d at %d)",
		getHostName(), loopCount, base, exp, reqResult, numOutstandingReqs, timeOutStandingReqs)
}

func handleRequest(w http.ResponseWriter, r *http.Request) {

	numOutstandingReqs := int64(-1)
	currentTime := time.Now().UnixNano()

	// check if there is a cpu parameter
	strCPUMilliCores := r.URL.Query().Get("cpu_mCores")

	// if there, run cpu load directly
	if strCPUMilliCores != "" {
		// get all params
		strDurationMs := r.URL.Query().Get("d_ms")
		cpuMilliCores, err := strconv.Atoi(strCPUMilliCores)
		if err != nil {
			respondWithError(w, strCPUMilliCores, strDurationMs, "", numOutstandingReqs, currentTime)
		}
		durationMs, err := strconv.Atoi(strDurationMs)
		if err != nil {
			respondWithError(w, strCPUMilliCores, strDurationMs, "", numOutstandingReqs, currentTime)
		}

		// runCPULoad(cpuMilliCores, durationMs)
		randomInt := rand.Intn(100)
		runCPUBudgetFair(randomInt, int((float64(cpuMilliCores)/1000.0)*float64(durationMs)))

		respondWithSuccess(w, strCPUMilliCores, strDurationMs, "", 0.0, numOutstandingReqs, currentTime)
	} else
	// do the math operations
	{

		loopCount := r.URL.Query().Get("loopCount")
		base := r.URL.Query().Get("base")
		exp := r.URL.Query().Get("exp")

		loopCountFloat, baseFloat, expFloat, isErr := convParamsToFloat(loopCount, base, exp)
		if isErr {
			respondWithError(w, loopCount, base, exp, numOutstandingReqs, currentTime)
		} else {
			reqResult := processRequest(loopCountFloat, baseFloat, expFloat)

			respondWithSuccess(w, loopCount, base, exp, reqResult, numOutstandingReqs, currentTime)

		}
	}
}

func waitAndRespond(
	w http.ResponseWriter, r *http.Request,
	latency time.Duration, endpointName string) {

	// check if latency is a get variable
	// if it is, then use that as the latency
	// if not, then use the default latency

	latencyFromReq := r.URL.Query().Get("latency")
	if latencyFromReq != "" {
		latencyMs, err := strconv.Atoi(latencyFromReq)
		if err == nil {
			latency = time.Duration(latencyMs) * time.Millisecond
		}
	}

	time.Sleep(latency)

	w.WriteHeader(http.StatusOK)
	w.Header().Set("Connection", "close")
	fmt.Fprintf(
		w,
		"Processed at %s w/ latency=%dms",
		endpointName, latency.Milliseconds())
}

type Response struct {
	ReqNum      int
	IsError     bool
	ErrMsg      string
	StatusCode  int
	Body        string
	StartTimeNs int64
	LatencyNs   int64
	ReadTimeNs  int64
}

func getFlags() (int, int, string) {
	port := flag.Int("p", 3333, "Port to run on")
	latencyMs := flag.Int("l", -1, "")
	endpointName := flag.String("e", "go_endpoint", "")
	flag.Parse()
	log.Printf("Port is %d, endpoint name is %s, and latency is %d\n",
		*port, *endpointName, *latencyMs)
	return *port, *latencyMs, *endpointName
}

func main() {

	portToListenOn, latencyMs, endpointName := getFlags()

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		if isEndpointLatencyFlagSet(latencyMs) {
			latency := time.Duration(latencyMs) * time.Millisecond
			waitAndRespond(w, r, latency, endpointName)
		} else {
			handleRequest(w, r)
		}
	})
	fmt.Printf("Server running (port=%d), route: http://localhost:%d/?loopCount=1&base=8&exp=7.7\n", portToListenOn, portToListenOn)

	if err := http.ListenAndServe(fmt.Sprintf(":%d", portToListenOn), nil); err != nil {
		log.Fatal(err)
	}
}

func isEndpointLatencyFlagSet(latency int) bool {
	return latency > 0
}
