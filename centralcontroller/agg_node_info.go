// ...existing code...
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"log/slog"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const AGGREGATE_ECHO_MESSAGES = true
const AGGREGATE_ECHO_MESSAGES_INTERVAL_US = 5000 // microseconds

const LATENCY_STATS_WINDOW_MS = 250

// For latency tracking
type LatencyRecord struct {
	TimestampMs int64 // milliseconds
	LatencyMs   int   // milliseconds
}

type ServiceLatencyStats struct {
	mu        sync.Mutex
	latencies map[string][]LatencyRecord // service -> slice of (timestamp, latency in ms)
}

func NewServiceLatencyStats() *ServiceLatencyStats {
	return &ServiceLatencyStats{
		latencies: make(map[string][]LatencyRecord),
	}
}

// Record a completed request's latency for a service
func (s *ServiceLatencyStats) RecordLatency(service string, latencyMs int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	fmt.Printf("[ServiceLatencyStats] Recorded latency for service %s: %dms\n", service, latencyMs)
	s.latencies[service] = append(s.latencies[service], LatencyRecord{TimestampMs: now, LatencyMs: latencyMs})
}

// Get the nth percentile latency (ms) for a service over the last 5 seconds
func (s *ServiceLatencyStats) GetPercentileLatency(service string, percentile float64) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	cutoffMs := now - LATENCY_STATS_WINDOW_MS // last 0.5 seconds
	records, ok := s.latencies[service]
	if !ok || len(records) == 0 {
		return 0
	}
	// Prune old records
	i := 0
	for ; i < len(records); i++ {
		if records[i].TimestampMs >= cutoffMs {
			break
		}
	}
	records = records[i:]
	s.latencies[service] = records
	if len(records) == 0 {
		return 0
	}
	// Collect latencies
	latencies := make([]int, len(records))
	for j, rec := range records {
		latencies[j] = rec.LatencyMs
	}
	// Sort and get nth percentile
	sort.Ints(latencies)
	if percentile < 0 {
		percentile = 0
	}
	if percentile > 100 {
		percentile = 100
	}
	idx := int(float64(len(latencies))*percentile/100.0) - 1
	if idx < 0 {
		idx = 0
	}
	return latencies[idx]
}

// Get the mean latency (ms) for a service
func (s *ServiceLatencyStats) GetMean(service string) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	cutoffMs := now - LATENCY_STATS_WINDOW_MS // last 0.5 seconds
	records, ok := s.latencies[service]
	if !ok || len(records) == 0 {
		return 0
	}
	// Prune old records
	i := 0
	for ; i < len(records); i++ {
		if records[i].TimestampMs >= cutoffMs {
			break
		}
	}
	records = records[i:]
	s.latencies[service] = records
	if len(records) == 0 {
		return 0
	}
	// Collect latencies
	latencies := make([]int, len(records))
	for j, rec := range records {
		latencies[j] = rec.LatencyMs
	}
	// Sort and get mean
	sort.Ints(latencies)
	if len(latencies) == 0 {
		return 0
	}
	sum := 0
	for _, lat := range latencies {
		sum += lat
	}
	return sum / len(latencies)
}

// Get the mean latency (ms) for a service, considering only values below the cutoff percentile
func (s *ServiceLatencyStats) GetMeanUnderPercentile(service string, cutoffPercentile float64) int {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	cutoffMs := now - LATENCY_STATS_WINDOW_MS // last 0.5 seconds
	records, ok := s.latencies[service]
	if !ok || len(records) == 0 {
		return 0
	}
	// Prune old records
	i := 0
	for ; i < len(records); i++ {
		if records[i].TimestampMs >= cutoffMs {
			break
		}
	}
	records = records[i:]
	s.latencies[service] = records
	if len(records) == 0 {
		return 0
	}
	// Collect latencies
	latencies := make([]int, len(records))
	for j, rec := range records {
		latencies[j] = rec.LatencyMs
	}
	// Sort latencies
	sort.Ints(latencies)
	if len(latencies) == 0 {
		return 0
	}
	// Calculate cutoff index
	if cutoffPercentile < 0 {
		cutoffPercentile = 0
	}
	if cutoffPercentile > 100 {
		cutoffPercentile = 100
	}
	cutoffIdx := int(float64(len(latencies)) * cutoffPercentile / 100.0)
	if cutoffIdx <= 0 {
		cutoffIdx = 1
	}
	if cutoffIdx > len(latencies) {
		cutoffIdx = len(latencies)
	}
	// Calculate mean of values below cutoff
	sum := 0
	for j := 0; j < cutoffIdx; j++ {
		sum += latencies[j]
	}
	return sum / cutoffIdx
}

func getLatencyUsFromData(data []byte) int {
	dataStr := string(data)
	dataStr = strings.TrimSpace(dataStr)
	// data is in the form <startTimeNsUnix>|<>|<>|<>
	dataParts := strings.Split(dataStr, "|")
	startTime, err := strconv.ParseInt(dataParts[0], 10, 64)
	if err != nil {
		fmt.Printf("Error parsing startTime: %s\n", err)
		return -1
	}
	latency := time.Now().UnixNano() - startTime
	return int(latency / 1000)
}

func makeReqToK8sHost(dstURL string, aggregatedMessages []string) {

	// JSON marshal the aggregated messages
	jsonData, err := json.Marshal(aggregatedMessages)
	if err != nil {
		fmt.Printf("client: error marshalling aggregated messages: %s\n", err)
		return
	}

	req, err := http.NewRequest(http.MethodPost, dstURL, bytes.NewBuffer(jsonData))
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Connection", "close")

	// for identifying the request in the LB
	req.Header.Set("CC-State", "aggregated")
	req.Header.Set("CC-StartTime", strconv.FormatInt(time.Now().UnixNano(), 10))

	// Add aggregated messages to header as JSON string
	ccStatesData, err := json.Marshal(aggregatedMessages)
	if err != nil {
		fmt.Printf("client: error marshalling aggregated messages for header: %s\n", err)
	} else {
		req.Header.Set("CC-States", string(ccStatesData))
	}

	startReq := time.Now()
	client := &http.Client{
		Timeout: 15 * time.Second, // Set a timeout for the entire request
	}
	res, err := client.Do(req)
	_ = time.Since(startReq)
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	_, err = io.ReadAll(res.Body)
	if err != nil {
		errMsg := fmt.Sprintf("client: could not read response body: %s", err)
		fmt.Println(errMsg)
		return
	}

	// fmt.Printf("Request to %s | Response: [%s] %s, %dμs\n",
	// 	dstURL, res.Status, string(resBody), latency.Microseconds())
}

func makeReqToK8sHostImmediate(dstURL string, data []byte) {

	// fmt.Printf("Request to %s\n", dstURL)

	req, err := http.NewRequest(http.MethodPost, dstURL, bytes.NewBuffer(data))
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	// req.Host = dstHost
	req.Header.Set("Content-Type", "text/plain")
	req.Header.Set("Connection", "close")

	// for identifying the request in the LB
	req.Header.Set("CC-State", strings.TrimSpace(string(data)))
	req.Header.Set("CC-StartTime", strconv.FormatInt(time.Now().UnixNano(), 10))

	startReq := time.Now()
	client := &http.Client{
		Timeout: 15 * time.Second, // Set a timeout for the entire request
	}
	res, err := client.Do(req)
	_ = time.Since(startReq)
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	_, err = io.ReadAll(res.Body)
	if err != nil {
		errMsg := fmt.Sprintf("client: could not read response body: %s", err)
		fmt.Println(errMsg)
		return
	}

	// fmt.Printf("Request to %s | Response: [%s] %s, %dμs\n",
	// 	dstURL, res.Status, string(resBody), latency.Microseconds())
}

type ServiceArrivingRPS struct {
	mu                  sync.Mutex
	arrivalTimestampsMs map[string][]int64 // map from service to slice of arrival unix seconds
}

func NewServiceArrivingRPS() *ServiceArrivingRPS {
	return &ServiceArrivingRPS{
		arrivalTimestampsMs: make(map[string][]int64),
	}
}

// Call this on every '++' operation
func (s *ServiceArrivingRPS) RecordArrival(service string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	s.arrivalTimestampsMs[service] = append(s.arrivalTimestampsMs[service], now)
}

// Returns the average RPS for the service over the rolling window
func (s *ServiceArrivingRPS) GetRPS(service string) float64 {
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now().UnixMilli()
	cutoffMs := now - NUM_OF_SEC_FOR_ROLLING_AVG_OF_RPS*1000
	ts, ok := s.arrivalTimestampsMs[service]
	if !ok {
		log.Printf("[ServiceArrivingRPS] ERROR: service '%s' not found in arrivalTimestampsMs, returning 0", service)
		return 0.0
	}
	// Prune old timestamps
	i := 0
	for ; i < len(ts); i++ {
		if ts[i] >= cutoffMs {
			break
		}
	}
	ts = ts[i:]
	s.arrivalTimestampsMs[service] = ts
	numReqsArrived := len(ts)
	if numReqsArrived == 0 {
		return 0.0
	}

	// timeElapsedSinceFirstReqMs := now - ts[0]
	// timeElapsedSinceFirstReq := float64(timeElapsedSinceFirstReqMs) / 1000.0

	currRPS := float64(numReqsArrived) / float64(NUM_OF_SEC_FOR_ROLLING_AVG_OF_RPS)

	fmt.Printf("[ServiceArrivingRPS] Service: %s | NumReqsArrived in last %.2f seconds: %d | RPS: %.2f\n",
		service, float64(NUM_OF_SEC_FOR_ROLLING_AVG_OF_RPS), numReqsArrived,
		currRPS)
	return currRPS
}

type ServiceOutstandingRequests struct {
	mu                sync.Mutex
	numOutstandingReq map[string]int
}

func NewServiceOutstandingRequests() *ServiceOutstandingRequests {
	return &ServiceOutstandingRequests{
		numOutstandingReq: make(map[string]int),
	}
}

type MessageAggregator struct {
	mu       sync.Mutex
	messages []string
}

func NewMessageAggregator() *MessageAggregator {
	return &MessageAggregator{
		messages: make([]string, 0),
	}
}

func (ma *MessageAggregator) AddMessage(message string) {
	ma.mu.Lock()
	defer ma.mu.Unlock()
	ma.messages = append(ma.messages, message)
}

func (ma *MessageAggregator) FlushMessages() []string {
	ma.mu.Lock()
	defer ma.mu.Unlock()
	messages := make([]string, len(ma.messages))
	copy(messages, ma.messages)
	ma.messages = ma.messages[:0] // Clear the slice
	return messages
}

func updateReqStats(
	serviceOutstandingRequests *ServiceOutstandingRequests,
	serviceArrivingRPS *ServiceArrivingRPS,
	serviceLatencyStats *ServiceLatencyStats,
	reqBody []byte) {

	// reqBody := b"1745477992498147000|svc0|0|--|32"
	// or
	// reqBody := b"1745477992498147000|svc0|0|++|-1"
	reqBodyStr := string(reqBody)
	parts := strings.Split(reqBodyStr, "|")
	if len(parts) >= 5 {
		service := parts[1] // svc0
		operation := parts[3]

		serviceOutstandingRequests.mu.Lock()

		switch operation {
		case "--":
			serviceOutstandingRequests.numOutstandingReq[service]--
			if serviceOutstandingRequests.numOutstandingReq[service] < 0 {
				slog.Error(fmt.Sprintf("Warning: outstanding requests < 0 for service %s [%d]",
					service, serviceOutstandingRequests.numOutstandingReq[service]))
			}
			// Record latency if ServiceLatencyStats is provided
			if serviceLatencyStats != nil {
				if l, err := strconv.Atoi(strings.TrimSpace(parts[4])); err == nil && l >= 0 {
					serviceLatencyStats.RecordLatency(service, l)
				}
			}
		case "++":
			serviceOutstandingRequests.numOutstandingReq[service]++
			if serviceArrivingRPS != nil {
				serviceArrivingRPS.RecordArrival(service)
			}
		case "DR":
			// Dropped request, do nothing to outstanding count
			if serviceArrivingRPS != nil {
				serviceArrivingRPS.RecordArrival(service)
			}
			// fmt.Println("====\n========== Dropped request for service ===\n===", service)
		default:
			fmt.Println("Invalid input format", reqBodyStr)
		}

		// fmt.Printf("Updated %v\n", serviceOutstandingRequests.numOutstandingReq)

		serviceOutstandingRequests.mu.Unlock()

	} else {
		fmt.Println("Invalid input format", reqBodyStr)
	}
}

func echoServer(
	ingressGatewayURLs []string,
	serviceOutstandingRequests *ServiceOutstandingRequests,
	serviceArrivingRPS *ServiceArrivingRPS,
	serviceLatencyStats *ServiceLatencyStats) {

	var messageAggregator *MessageAggregator

	if AGGREGATE_ECHO_MESSAGES {
		// Create message aggregator
		messageAggregator = NewMessageAggregator()

		// Start background goroutine to send aggregated messages periodically
		go func() {
			ticker := time.NewTicker(AGGREGATE_ECHO_MESSAGES_INTERVAL_US * time.Microsecond)
			defer ticker.Stop()
			for range ticker.C {
				messages := messageAggregator.FlushMessages()
				if len(messages) > 0 {
					for _, ingressGatewayURL := range ingressGatewayURLs {
						go makeReqToK8sHost(ingressGatewayURL, messages)
					}
				}
			}
		}()
	}

	// HTTP Server to Echo POST Request Body
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {

		if r.Method != http.MethodPost {
			http.Error(w, "Only POST requests are allowed", http.StatusMethodNotAllowed)
			return
		}
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "Failed to read request body", http.StatusInternalServerError)
			return
		}

		// fmt.Printf("++ECHO++ Received request to echo at %d: %s\n", time.Now().UnixNano(), body)
		fmt.Printf("++ECHO++ Latency from LB to CC: %.2fms\n", float64(getLatencyUsFromData(body))/1000)

		// Update request stats immediately (don't wait)
		updateReqStats(serviceOutstandingRequests, serviceArrivingRPS, serviceLatencyStats, body)

		if AGGREGATE_ECHO_MESSAGES {
			// Add message to aggregator (will be sent later in batch)
			messageAggregator.AddMessage(string(body))
		} else {
			// Send immediately (old behavior)
			for _, ingressGatewayURL := range ingressGatewayURLs {
				go makeReqToK8sHostImmediate(ingressGatewayURL, body)
			}
		}

		defer r.Body.Close()
		w.WriteHeader(http.StatusOK)
		w.Write(body) // Echo back request body
	})

	// Start HTTP Server
	port := ":" + ECHO_SERVER_PORT
	log.Printf("Echo server listening on port %s", port)
	if err := http.ListenAndServe(port, nil); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}

// curl http://echo-server.default.svc.cluster.local:5656 -d '{"message": "Hello"}' -H "Content-Type: application/json"
