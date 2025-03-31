package main

import (
	"bytes"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

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

func makeReqToK8sHost(dstURL string, dstHost string, data []byte) {

	fmt.Printf("Request to %s|%s\n", dstURL, dstHost)

	fmt.Printf("Latency from LB to CC: %dμs\n", getLatencyUsFromData(data))

	req, err := http.NewRequest(http.MethodPost, dstURL, bytes.NewBuffer(data))
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	req.Host = dstHost
	req.Header.Set("Content-Type", "text/plain")
	req.Header.Set("Connection", "close")

	// for identifying the request in the LB
	req.Header.Set("CC-State", strings.TrimSpace(string(data)))
	req.Header.Set("CC-StartTime", strconv.FormatInt(time.Now().UnixNano(), 10))

	startReq := time.Now()
	client := &http.Client{
		Timeout: 3 * time.Second, // Set a timeout for the entire request
	}
	res, err := client.Do(req)
	latency := time.Since(startReq)
	if err != nil {
		fmt.Printf("client: error creating http request to echo: %s\n", err)
		return
	}
	resBody, err := io.ReadAll(res.Body)
	if err != nil {
		errMsg := fmt.Sprintf("client: could not read response body: %s", err)
		fmt.Println(errMsg)
		return
	}

	fmt.Printf("Request to %s|%s | Response: [%s] %s, %dμs\n",
		dstURL, dstHost, res.Status, string(resBody), latency.Microseconds())
}

func echoServer(ingressGatewayURL string) {

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

		fmt.Printf("Received request to echo: %s\n", body)

		// Make request to K8s Host
		go makeReqToK8sHost(ingressGatewayURL, "app1.mplb.com", body)
		// go makeReqToK8sHost("http://172.24.92.73:3333", "app1.mplb.com", body)

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
