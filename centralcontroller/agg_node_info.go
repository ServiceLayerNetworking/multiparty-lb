package main

import (
	"bytes"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"sync"
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

func makeReqToK8sHost(dstURL string, data []byte) {

	// fmt.Printf("Request to %s\n", dstURL)

	// fmt.Printf("Latency from LB to CC: %dμs\n", getLatencyUsFromData(data))

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
		Timeout: 3 * time.Second, // Set a timeout for the entire request
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

type ServiceOutstandingRequests struct {
	mu                sync.Mutex
	numOutstandingReq map[string]int
}

func updateOutstandingRequests(serviceOutstandingRequests *ServiceOutstandingRequests, reqBody []byte) {
	// input := "1745477992498147000|svc0|0|--"
	reqBodyStr := string(reqBody)
	parts := strings.Split(reqBodyStr, "|")
	if len(parts) >= 4 {
		service := parts[1] // svc0
		operation := parts[3]

		serviceOutstandingRequests.mu.Lock()

		if operation == "--" {
			serviceOutstandingRequests.numOutstandingReq[service]--
			if serviceOutstandingRequests.numOutstandingReq[service] < 0 {
				fmt.Println("This shouldn't have happened!")
			}
		} else if operation == "++" {
			serviceOutstandingRequests.numOutstandingReq[service]++
		} else {
			fmt.Println("Invalid input format", reqBodyStr)
		}

		// fmt.Printf("Updated %v\n", serviceOutstandingRequests.numOutstandingReq)

		serviceOutstandingRequests.mu.Unlock()

	} else {
		fmt.Println("Invalid input format", reqBodyStr)
	}
}

func echoServer(ingressGatewayURLs []string, serviceOutstandingRequests *ServiceOutstandingRequests) {

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

		// fmt.Printf("Received request to echo: %s\n", body)

		// 1745477992498147000|svc0|0|--
		updateOutstandingRequests(serviceOutstandingRequests, body)

		for _, ingressGatewayURL := range ingressGatewayURLs {
			// Make request to K8s Host
			go makeReqToK8sHost(ingressGatewayURL, body)
		}
		// go makeReqToK8sHost(ingressGatewayURL, "app1.mplb.com", body)
		// go makeReqToK8sHost(ingressGatewayURL, "app1.mplb.com", body)
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
