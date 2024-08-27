package main

import (
	"flag"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"strconv"
	"time"
)

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
	latencyMs := flag.Int("l", 50, "")
	endpointName := flag.String("e", "go_endpoint", "")
	flag.Parse()
	log.Printf("Port is %d, endpoint name is %s, and latency is %d\n",
		*port, *endpointName, *latencyMs)
	return *port, *latencyMs, *endpointName
}

func main() {

	portToListenOn, latencyMs, endpointName := getFlags()
	latency := time.Duration(latencyMs) * time.Millisecond

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// handleRequest(w, r)
		waitAndRespond(w, r, latency, endpointName)
	})
	fmt.Printf("Server running (port=%d), route: http://localhost:%d/?loopCount=1&base=8&exp=7.7\n", portToListenOn, portToListenOn)

	if err := http.ListenAndServe(fmt.Sprintf(":%d", portToListenOn), nil); err != nil {
		log.Fatal(err)
	}
}
