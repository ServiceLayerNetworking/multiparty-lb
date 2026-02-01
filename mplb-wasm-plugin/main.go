package main

import (
	"crypto/md5"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm"
	"github.com/tetratelabs/proxy-wasm-go-sdk/proxywasm/types"
	_ "github.com/wasilibs/nottinygc"
)

// These keys are global keys that are used to store shared data between all instances of the plugin.
// a lot of these keys are not used.
const (
	KEY_INFLIGHT_ENDPOINT_LIST = "slate_inflight_endpoint_list"
	KEY_ENDPOINT_RPS_LIST      = "slate_endpoint_rps_list"
	KEY_INFLIGHT_REQ_COUNT     = "slate_inflight_request_count"
	KEY_REQUEST_COUNT          = "slate_rps"
	KEY_LAST_RESET             = "slate_last_reset"
	KEY_RPS_THRESHOLDS         = "slate_rps_threshold"
	KEY_HASH_MOD               = "slate_hash_mod"
	KEY_TRACED_REQUESTS        = "slate_traced_requests"
	// this is in millis
	AGGREGATE_REQUEST_LATENCY = "slate_last_second_latency_avg"
	KEY_RPS_SHARED_QUEUE      = "slate_rps_shared_queue"
	KEY_RPS_SHARED_QUEUE_SIZE = "slate_rps_shared_queue_size"

	TIMESTAMPS_SHARED_QUEUE       = "mplb_timestamps_shared_queue"
	SENT_REQ_SHARED_QUEUE         = "mplb_sent_req_shared_queue"
	RIF_SHARED_QUEUE              = "mplb_rif_shared_queue"
	RATE_LIMITER_TIMESTAMPS_QUEUE = "mplb_rate_limiter_timestamps_queue"

	// this is the reporting period in millis
	TICK_PERIOD = 500

	// this is the number of requests that are allowed to be sent to the endpoints over the max allowed RPS calculated from the CPU allocated to the service.
	DEFAULT_MAX_RPS_ALLOWED                            = 105
	USE_DEFAULT_MAX_RPS_ALLOWED                        = false
	RATE_LIMITER_NUM_OF_REQ_ALLOWED_OVER_CPU_ALLOCATED = 0
	NUM_OF_LB_REPLICAS                                 = 1
	USE_CONCURRENT_CONNECTIONS_IN_RATE_LIMITER         = true
	RATE_LIMITER_ENFORCEMENT_INTERVAL_MS               = 3000

	// Timeout for removing RIF entries in milliseconds (should correspond to client timeout)
	RIF_ENTRY_TIMEOUT_MS = 5000 + 500 // adding 500ms buffer to prevent double removals

	// Hash mod for frequency of request tracing.
	DEFAULT_HASH_MOD = 10

	KEY_MATCH_DISTRIBUTION = "slate_match_distribution"

	// load balancing strategy
	// [leastrequest_plus_rlpb|leastrequest_plus_rl|leastrequest_rl|nodal_leastrequest_rlpb|only_nodal_leastrequest|leastrequest_plus|tmp_nodal_leastrequest|nodal_leastrequest|minimize_diff|locality_aware_weighted_random|leastrequest|weighted_random|weighted_roundrobin|weighted_leastrequest]
	LOAD_BALANCING_STRATEGY = "minimize_diff"
)

var (
	ALL_KEYS = []string{KEY_INFLIGHT_REQ_COUNT, KEY_REQUEST_COUNT, KEY_LAST_RESET, KEY_RPS_THRESHOLDS, KEY_HASH_MOD, AGGREGATE_REQUEST_LATENCY,
		KEY_TRACED_REQUESTS, KEY_MATCH_DISTRIBUTION, KEY_INFLIGHT_ENDPOINT_LIST, KEY_ENDPOINT_RPS_LIST, KEY_RPS_SHARED_QUEUE, KEY_RPS_SHARED_QUEUE_SIZE,
		TIMESTAMPS_SHARED_QUEUE, SENT_REQ_SHARED_QUEUE, RIF_SHARED_QUEUE, RATE_LIMITER_TIMESTAMPS_QUEUE}
	cur_idx      int
	latency_list []int64
	ts_list      []int64
)

func main() {
	proxywasm.SetVMContext(&vmContext{})
	rand.Seed(time.Now().UnixNano())
}

type vmContext struct {
	// Embed the default VM context here,
	// so that we don't need to reimplement all the methods.
	types.DefaultVMContext
}

// TracedRequestStats is a struct that holds information about a traced request.
// This is what is reported to the controller.
type TracedRequestStats struct {
	method       string
	path         string
	traceId      string
	spanId       string
	parentSpanId string
	startTime    int64
	endTime      int64
	bodySize     int64
	firstLoad    int64
	rps          int64
}

// Statistic for a given endpoint.
type EndpointStats struct {
	Inflight uint64
	Total    uint64
}

// Override types.DefaultVMContext.
func (*vmContext) NewPluginContext(contextID uint32) types.PluginContext {
	return &pluginContext{
		startTime: time.Now().UnixMilli(),
	}
}

func (*vmContext) OnVMStart(vmConfigurationSize int) types.OnVMStartStatus {
	// set all keys to 0
	for _, key := range ALL_KEYS {
		if err := proxywasm.SetSharedData(key, make([]byte, 8), 0); err != nil {
			proxywasm.LogCriticalf("unable to set shared data: %v", err)
		}
	}
	// set default hash mod
	buf := make([]byte, 8)
	binary.LittleEndian.PutUint64(buf, uint64(DEFAULT_HASH_MOD))
	if err := proxywasm.SetSharedData(KEY_HASH_MOD, buf, 0); err != nil {
		proxywasm.LogCriticalf("unable to set shared data: %v", err)
	}
	if _, err := proxywasm.RegisterSharedQueue(KEY_RPS_SHARED_QUEUE); err != nil {
		proxywasm.LogCriticalf("unable to register shared queue: %v", err)
	}
	return true
}

var region string
var serviceName string

type pluginContext struct {
	types.DefaultPluginContext

	podName          string
	serviceName      string
	svcWithoutRegion string

	region string

	startTime int64

	nodeID int
}

func (p *pluginContext) OnPluginStart(pluginConfigurationSize int) types.OnPluginStartStatus {
	if err := proxywasm.SetTickPeriodMilliSeconds(TICK_PERIOD); err != nil {
		proxywasm.LogCriticalf("unable to set tick period: %v", err)
		return types.OnPluginStartStatusFailed
	}
	svc := os.Getenv("ISTIO_META_WORKLOAD_NAME")
	if svc == "" {
		svc = "SLATE_UNKNOWN_SVC"
	}
	pod := os.Getenv("HOSTNAME")
	if pod == "" {
		pod = "SLATE_UNKNOWN_POD"
	}
	regionName := os.Getenv("ISTIO_META_REGION")
	if regionName == "" {
		regionName = "SLATE_UNKNOWN_REGION"
	}
	nodeNameEnv := os.Getenv("ISTIO_META_NODE_NAME")
	if nodeNameEnv == "" {
		nodeNameEnv = "SLATE_UNKNOWN_NODE"
	}

	// // Retrieve the node metadata
	// nodeName, err := proxywasm.GetProperty([]string{"node", "metadata", "NAME"})
	// if err != nil {
	// 	proxywasm.LogCriticalf("failed to get node name: %v", err)
	// 	return false
	// }

	proxywasm.LogCriticalf("Node name is: %s", string(nodeNameEnv))

	proxywasm.LogCriticalf("Load balancing strategy: %s", LOAD_BALANCING_STRATEGY)

	nodeID, err := getNodeID(string(nodeNameEnv))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get node ID: %v", err)
		nodeID = 0
	} else {
		proxywasm.LogCriticalf("Starting plugin with pod %s, service %s, region %s, nodeID %d", pod, svc, regionName, nodeID)
	}

	p.podName = pod
	p.serviceName = svc
	p.region = regionName
	p.nodeID = nodeID
	region = regionName
	serviceName = svc
	return types.OnPluginStartStatusOK
}

// OnTick reports load to the controller every TICK_PERIOD milliseconds.
func (p *pluginContext) OnTick() {

	// KEY_LAST_RESET acts as a mutex to prevent multiple instances of the plugin from calling OnTick at the same time.
	data, cas, err := proxywasm.GetSharedData(KEY_LAST_RESET)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get shared data: %v", err)
		return
	}
	lastReset := int64(binary.LittleEndian.Uint64(data))
	currentNanos := time.Now().UnixMilli()

	// allow for some jitter - this is bad and racy and hardcoded
	if (TICK_PERIOD / 2) >= (currentNanos - lastReset) {
		// we've been reset/mutex was locked.
		return
	}

	buf := make([]byte, 8)
	binary.LittleEndian.PutUint64(buf, uint64(currentNanos))
	if err := proxywasm.SetSharedData(KEY_LAST_RESET, buf, cas); err != nil {
		if errors.Is(err, types.ErrorStatusCasMismatch) {
			// we've been reset by another peer while we were trying to set the value.
			return
		}
	}

	tsListBytes, err := getAndSetSharedData(TIMESTAMPS_SHARED_QUEUE, make([]byte, 8))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get shared data for TIMESTAMPS_SHARED_QUEUE: %v", err)
		return
	}
	tsListStr := string(tsListBytes)

	tsSentReqListBytes, err := getAndSetSharedData(SENT_REQ_SHARED_QUEUE, make([]byte, 8))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get shared data for TIMESTAMPS_SHARED_QUEUE: %v", err)
		return
	}
	tsSentReqListStr := string(tsSentReqListBytes)

	authority := fmt.Sprintf("hostagent-node%d.mplb-system.svc.cluster.local", p.nodeID)

	controllerHeaders := [][2]string{
		{":method", "POST"},
		{":path", "/"},
		{":authority", authority},
		// {"x-slate-podname", p.podName},
		// {"x-slate-servicename", p.serviceName},
		// {"x-slate-region", p.region},
	}

	reqDest := fmt.Sprintf("outbound|9989||%s", authority)
	// reqBody := fmt.Sprintf("reqCount\n%d\n\ninflightStats\n%s\nrequestStats\n%s\ntimestampstats\n%s\n", reqCount, inflightStats, requestStatsStr, tsListStr)
	reqBody := fmt.Sprintf(
		"%s %s\nreqCount\n%d\ntimestampstats\n%s\nsentreqstats\n%s\n",
		p.serviceName,
		p.podName,
		len(tsListStr),
		tsListStr,
		tsSentReqListStr)
	proxywasm.LogCriticalf("<OnTick>@%dns\nreqDest:%s\nreqBody:\n%s", getCurrUnixTimeNs(), reqDest, reqBody)

	if _, err := proxywasm.DispatchHttpCall(reqDest, controllerHeaders,
		[]byte(reqBody), make([][2]string, 0), 5000, OnTickHttpCallResponse); err != nil {
		proxywasm.LogCriticalf("dispatch httpcall failed: %v", err)
	}

	// Process RIF events: handle timeouts and re-queue pending entries
	processRIFEvents()

	// Cleanup old rate limiter timestamps
	cleanupRateLimiterTimestamps(time.Now().UnixMilli())
}

// Override types.DefaultPluginContext.
func (p *pluginContext) NewHttpContext(contextID uint32) types.HttpContext {
	return &httpContext{contextID: contextID, pluginContext: p}
}

type httpContext struct {
	// Embed the default http context here,
	// so that we don't need to reimplement all the methods.
	types.DefaultHttpContext
	contextID              uint32
	pluginContext          *pluginContext
	isProcessingAggregated bool
}

func getRandomReqId() string {
	return fmt.Sprintf("%x", md5.Sum([]byte(strconv.Itoa(rand.Int()))))
}

func parseLBWeights(input string) ([]float64, []int, error) {

	podNodesStr := ""
	weightsStr := ""

	proxywasm.LogCritical("Parsing weights: " + input)

	// check if weight string has '/'
	if strings.Contains(input, "/") {
		parts := strings.Split(input, "/")
		proxywasm.LogCriticalf("Parts: %v", parts)
		weightsStr = parts[0]
		podNodesStr = parts[1]
	}

	weightsStrs := strings.Split(weightsStr, "|")

	weights := make([]float64, len(weightsStrs))

	for i, weightStr := range weightsStrs {

		weight, err := strconv.ParseFloat(weightStr, 64)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't parse weight: %v", err)
			return nil, nil, err
		}

		weights[i] = weight
	}

	podNodesStrs := strings.Split(podNodesStr, "|")
	podNodesInt := make([]int, len(podNodesStrs))
	for i, podNodeStr := range podNodesStrs {
		podNodeInt, err := strconv.Atoi(podNodeStr)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't parse pod node: %v", err)
			return nil, nil, err
		} else {
			podNodesInt[i] = podNodeInt
		}
	}

	return weights, podNodesInt, nil
}

func (ctx *httpContext) OnHttpRequestHeaders(int, bool) types.Action {

	// proxywasm.LogCriticalf("OnHttpRequestHeaders entered")

	reqMethod, err := proxywasm.GetHttpRequestHeader(":method")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get :method request header: %v", err)
		return types.ActionContinue
	}
	reqPath, err := proxywasm.GetHttpRequestHeader(":path")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get :path request header: %v", err)
		return types.ActionContinue
	}
	reqPath = strings.Split(reqPath, "?")[0]
	reqAuthority, err := proxywasm.GetHttpRequestHeader(":authority")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get :authority request header: %v", err)
		return types.ActionContinue
	}
	// if reqAuthority contains : then it is a request to a specific port
	dst := strings.Split(reqAuthority, ".")[0]
	if strings.Contains(reqAuthority, ":") {
		dst = strings.Split(reqAuthority, ":")[0]
	}

	// proxywasm.LogCriticalf("ServiceName: %s, dst: %s",
	// 	ctx.pluginContext.serviceName, dst)

	proxywasm.LogCriticalf(
		"--Request: %s %s %s", reqMethod, reqPath, reqAuthority)

	// check if request has "CC-State" header, if so it is a post request
	// from the controller that contains outstanding requests information
	// echo-ed back to the LB. Process the data and drop request
	ccState, err := proxywasm.GetHttpRequestHeader("CC-State")
	if err == nil {
		proxywasm.LogCriticalf("CC-State header found: %s", ccState)
		// process the data and drop the request

		// get the latency from CC-StartTime
		ccReqStartTimeNsStr, err := proxywasm.GetHttpRequestHeader("CC-StartTime")
		if err != nil {
			proxywasm.LogCriticalf("Couldn't get request header CC-StartTime: %v", err)
			ccReqStartTimeNsStr = "0"
		}
		ccReqStartTimeNs, err := strconv.ParseUint(ccReqStartTimeNsStr, 10, 64)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't parse CC-StartTime: %v", err)
			ccReqStartTimeNs = 0
		}
		ccReqLatencyNs := getCurrUnixTimeNs() - ccReqStartTimeNs
		ccReqLatencyUs := ccReqLatencyNs / 1000
		proxywasm.LogCriticalf("Latency from CC to LB: %dμs", ccReqLatencyUs)

		if ccState == "aggregated" {
			// Handle aggregated messages from header CC-States
			ccStates, err := proxywasm.GetHttpRequestHeader("CC-States")
			if err != nil {
				proxywasm.LogCriticalf("Couldn't get CC-States header: %v", err)
			} else {
				// Parse JSON array of strings from CC-States header
				var messages []string
				if err := json.Unmarshal([]byte(ccStates), &messages); err != nil {
					proxywasm.LogCriticalf("Failed to parse CC-States JSON: %v", err)
				} else {
					proxywasm.LogCriticalf("Processing %d aggregated messages from CC-States header", len(messages))
					// Process each message
					for _, message := range messages {
						processEchoBody(message, ctx.pluginContext.serviceName)
					}
				}
			}
		} else {
			// Handle single message (old behavior)
			processEchoBody(ccState, ctx.pluginContext.serviceName)
		}
		proxywasm.SendHttpResponse(
			200,
			[][2]string{
				{"Content-Type", "text/plain"},
			},
			[]byte("Received the state"), // Body of the response
			0,                            // GRPC status code OK
		)
		return types.ActionPause
	}

	// the request is originating from this sidecar to another service, we will perform routing magic
	if !strings.HasPrefix(ctx.pluginContext.serviceName, dst) {
		// policy enforcement for outbound requests

		// before routing, log the start time
		currentTime := time.Now().UnixMilli()
		currentTimeStr := fmt.Sprintf("%d", currentTime)

		// determine if this request is over capacity and should be dropped
		shouldDrop, err := shouldDropRequest(currentTime, dst)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't determine if request should be dropped: %v", err)
		} else {
			if shouldDrop {

				// first log the sent request
				appendSentReqStats(currentTimeStr, dst, "")

				// then inform CC if lb is going to perform rate limiting
				if LOAD_BALANCING_STRATEGY == "minimize_diff" ||
					LOAD_BALANCING_STRATEGY == "nodal_leastrequest" ||
					LOAD_BALANCING_STRATEGY == "leastrequest_rl" ||
					LOAD_BALANCING_STRATEGY == "leastrequest_plus_rl" ||
					LOAD_BALANCING_STRATEGY == "leastrequest_plus_rlpb" ||
					LOAD_BALANCING_STRATEGY == "nodal_leastrequest_rlpb" {
					// inform CC of dropped request due to rate limiting
					informCCofDroppedReq(dst)
				}

				proxywasm.LogCriticalf("Dropping request: %s %s %s", reqMethod, reqPath, reqAuthority)
				if err := proxywasm.SendHttpResponse(
					503, nil,
					[]byte("Request dropping as capacity reached"), -1); err != nil {
					proxywasm.LogCriticalf("failed to send http response: %v", err)
					panic(err)
				}
				return types.ActionPause
			}
		}

		// add current time to request header for latency logging when req finishes
		proxywasm.LogCriticalf("Setting x-mplb-start-time: " + currentTimeStr)
		headerErr := proxywasm.ReplaceHttpRequestHeader(
			"x-mplb-start-time", currentTimeStr)
		if headerErr != nil {
			proxywasm.LogCriticalf(
				"Error adding x-mplb-start-time header: %v", headerErr)
		}

		// add a unique id to the request
		var reqId string = getRandomReqId()
		proxywasm.LogCriticalf("Setting x-mplb-req-id: " + reqId)
		headerErr = proxywasm.ReplaceHttpRequestHeader(
			"x-mplb-req-id", reqId)
		if headerErr != nil {
			proxywasm.LogCriticalf(
				"Error adding x-mplb-req-id header: %v", headerErr)
		}

		// get stored weights from central controller
		weightsBStr, _, err := proxywasm.GetSharedData(dst)

		if err != nil {
			proxywasm.LogCriticalf("Shared data doesn't exist data for %s: %v", dst, err)
			// no rules available yet.
			proxywasm.LogCriticalf("Removing x-lb-endpt")
			headerErr := proxywasm.RemoveHttpRequestHeader("x-lb-endpt")
			if headerErr != nil {
				proxywasm.LogCriticalf("Error removing header: %v", headerErr)
			}

		} else {
			weightsStr := string(weightsBStr)
			if weightsStr == "nil" {
				proxywasm.LogCriticalf("Nil weights available for %s", dst)
				// no rules available yet.
				proxywasm.LogCriticalf("Removing x-lb-endpt")
				headerErr := proxywasm.RemoveHttpRequestHeader("x-lb-endpt")
				if headerErr != nil {
					proxywasm.LogCriticalf("Error removing header: %v", headerErr)
				}

			} else {

				// parse the weights from central controller
				weights, podNodes, err := parseLBWeights(weightsStr)
				if err != nil {
					proxywasm.LogCriticalf("Couldn't parse weights: %v", err)
					appendSentReqStats(currentTimeStr, dst, "")
					addToRIF(reqId, dst, "", currentTime)
					return types.ActionContinue
				}

				// get the next endpoint to send the request to
				endpointNum, err := getNextDstEndpoint(dst, weights, podNodes)
				if err != nil {
					proxywasm.LogCriticalf("Couldn't get next endpoint: %v", err)
					appendSentReqStats(currentTimeStr, dst, "")
					addToRIF(reqId, dst, "", currentTime)
					return types.ActionContinue
				}

				// set the header that would be used by sidecar to route the request
				header := fmt.Sprintf("%s-%d", dst, endpointNum)
				proxywasm.LogCriticalf("Setting x-lb-endpt:" + header)
				headerErr := proxywasm.ReplaceHttpRequestHeader(
					"x-lb-endpt", header)
				if headerErr != nil {
					proxywasm.LogCriticalf(
						"Error adding header: %v", headerErr)
				}

				appendSentReqStats(currentTimeStr, dst, header)
				addToRIF(reqId, dst, header, currentTime)
				return types.ActionContinue
			}
		}
		appendSentReqStats(currentTimeStr, dst, "")
		addToRIF(reqId, dst, "", currentTime)
		return types.ActionContinue
	}

	return types.ActionContinue
}

// OnHttpResponseHeaders is called when response headers arrive.
// Return types.ActionPause if you want to stop sending headers to downstream.
func (ctx *httpContext) OnHttpResponseHeaders(numHeaders int, endOfStream bool) types.Action {

	// check if x-dst-pod is already set
	podName, err := proxywasm.GetHttpResponseHeader("x-dst-pod")
	if err == nil {
		proxywasm.LogCriticalf("x-dst-pod already set. Value: \"%s\"", podName)
		// if set, this means upstream has already set the podname
		return types.ActionContinue
	}

	// else, this is the upstream, we need to set the podname
	currPodName := ctx.pluginContext.podName
	proxywasm.LogCriticalf("Setting x-dst-pod: " + currPodName)
	headerErr := proxywasm.ReplaceHttpResponseHeader(
		"x-dst-pod", currPodName)
	if headerErr != nil {
		proxywasm.LogCriticalf(
			"Error adding x-dst-pod: %s as response header: %v",
			currPodName, headerErr)
	}

	return types.ActionContinue
}

// OnHttpStreamDone is called when the stream is about to close.
// We use this to record the end time of the traced request.
// Since all responses are treated equally, regardless of whether
// they come from upstream or downstream, we need to do some clever
// bookkeeping and only record the end time for the last response.
func (ctx *httpContext) OnHttpStreamDone() {

	defer proxywasm.LogCriticalf("OnHttpStreamDone: Completed")
	proxywasm.LogCriticalf("OnHttpStreamDone: Entered")

	// check the status code of response
	statusCode, err := proxywasm.GetHttpResponseHeader(":status")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get :status response header: %v", err)
		return
	}
	if statusCode != "200" {
		proxywasm.LogCriticalf("Response status code is not 200: %s, so not doing anything in OnHttpStreamDone", statusCode)
		return
	}

	reqAuthority, err := proxywasm.GetHttpRequestHeader(":authority")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get :authority request header: %v", err)
		return
	}
	dstSvc := strings.Split(reqAuthority, ":")[0]

	// we will only log requests if they are orinigating from this sidecar to another service
	if strings.HasPrefix(ctx.pluginContext.serviceName, dstSvc) {
		return
	}

	// get x-mplb-start-time from request headers
	startTimeStr, err := proxywasm.GetHttpRequestHeader("x-mplb-start-time")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get request header x-mplb-start-time in the response: %v", err)
		return
	}

	// get x-mplb-req-id from request headers
	reqId, err := proxywasm.GetHttpRequestHeader("x-mplb-req-id")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get request header x-mplb-req-id in the response: %v", err)
		return
	}

	// get x-dst-pod from response headers
	dstPod, err := proxywasm.GetHttpResponseHeader("x-dst-pod")
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get response header x-dst-pod in the response: %v", err)
		proxywasm.LogCriticalf("Trying to get x-lb-endpt from the request header")
		dstPod, err = proxywasm.GetHttpRequestHeader("x-lb-endpt")
		if err != nil {
			proxywasm.LogCriticalf("Couldn't get request header x-lb-endpt in the response: %v", err)
		} else {
			proxywasm.LogCriticalf("Got x-lb-endpt: %s", dstPod)
		}
	}

	// CORNER CASE PREVENTION: (logging at frontend when request gateway->frontend)
	// for the request gateway->frontend:
	// 		dstSvc: <ClusterIP of istio-ingressgateway>
	// 		dstPod: frontend-\d+
	// because we want to log at gw and not at frontend,
	// we will check if the serviceName is prefix of dstPod
	// (just checking dstSvc will not work as it is the ClusterIP and not frontend)
	if strings.HasPrefix(dstPod, ctx.pluginContext.serviceName) {
		return
	}

	// log the end time and append start time and end time in an array in SharedData
	currentTime := time.Now().UnixMilli()
	endTimeStr := fmt.Sprintf("%d", currentTime)
	proxywasm.LogCriticalf("OnHttpStreamDone: StartTime: %s, EndTime: %s", startTimeStr, endTimeStr)

	latencyMs := currentTime - atoi64(startTimeStr)
	notifyRequestCompletedToLB(dstPod, latencyMs)

	// remove from RIF
	removeFromRIF(reqId)

	currTime := getCurrUnixTimeNs()

	isTsListChangeSuccessful := false

	for !isTsListChangeSuccessful {

		// get the current array of timestamps
		tsList, cas, err := proxywasm.GetSharedData(TIMESTAMPS_SHARED_QUEUE)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't get shared data for TIMESTAMPS_SHARED_QUEUE: %v", err)
			// this should never happen
			return
		}

		timeStampStr := fmt.Sprintf("\n%s %s %s %s", dstSvc, dstPod, startTimeStr, endTimeStr)

		// append the new timestamp to the list
		tsList = append(tsList, []byte(timeStampStr)...)

		// set the new list
		if err := proxywasm.SetSharedData(TIMESTAMPS_SHARED_QUEUE, tsList, cas); err != nil {
			proxywasm.LogCriticalf("unable to set shared data for TIMESTAMPS_SHARED_QUEUE: %v", err)
			if errors.Is(err, types.ErrorStatusCasMismatch) {
				proxywasm.LogCriticalf("CAS Mismatch on TIMESTAMPS_SHARED_QUEUE, failing: %v", err)
			}
		} else {
			proxywasm.LogCriticalf("added timestamp to shared data")
			isTsListChangeSuccessful = true
		}
	}

	// // get the response headers
	// respHeaders, err := proxywasm.GetHttpResponseHeaders()
	// if err != nil {
	// 	proxywasm.LogCriticalf("Couldn't get response headers: %v", err)
	// 	return
	// }
	// //print all headers
	// for _, header := range respHeaders {
	// 	proxywasm.LogCriticalf("Header: %s: %s", header[0], header[1])
	// }

	// perform the operation
	timeTaken := getCurrUnixTimeNs() - currTime
	proxywasm.LogCriticalf("Time taken to do remaining stuff at onHTTPStreamDone: %dus", timeTaken/1e3)

}

func atoi64(s string) int64 {
	i, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't parse string to int64: %v", err)
		return 0
	}
	return i
}

// callback for OnTick() http call response
func OnTickHttpCallResponse(numHeaders, bodySize, numTrailers int) {

	defer proxywasm.LogCriticalf("OnTickHttpCallResponse done")
	proxywasm.LogCriticalf("OnTickHttpCallResponse entered")

	// receive RPS thresholds, set shared data accordingly
	hdrs, err := proxywasm.GetHttpCallResponseHeaders()
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get http call response headers: %v", err)
		return
	}
	var status int
	status = 200
	for _, hdr := range hdrs {
		if hdr[0] == ":status" {
			status, err = strconv.Atoi(hdr[1])
			if err != nil {
				proxywasm.LogCriticalf("Couldn't parse :status header: %v", err)
				return
			}
		}
	}

	if status >= 400 {
		proxywasm.LogCriticalf("received ERROR http call response, status %v body size: %d", hdrs, bodySize)
		return
	}
	if bodySize == 0 {
		return
	}

	respBody, err := proxywasm.GetHttpCallResponseBody(0, bodySize)
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get http call response body: %v", err)
		return
	}

	body := string(respBody)
	// example response body: "svcA:45.5|69.22 svcB:54.7|44.1 "
	// , or:                  "svcA:4.54:45.5|69.22 svcB:7.8:54.7|44.1 "
	body = strings.TrimSpace(body)
	if body == "" {
		return
	}
	svcInfos := strings.Split(body, " ")[1:]
	topo := make(map[string][]int)
	for _, svcInfo := range svcInfos {
		svcInfoSplit := strings.Split(svcInfo, ":")
		if len(svcInfoSplit) == 2 {
			svcName := svcInfoSplit[0]
			svcWeights := svcInfoSplit[1]
			proxywasm.LogCriticalf("setting outbound request weights %v: %v", svcName, svcWeights)
			if err := proxywasm.SetSharedData(svcName, []byte(svcWeights), 0); err != nil {
				proxywasm.LogCriticalf("unable to set shared data for endpoint distribution %v: %v", svcName, err)
			}
		} else if len(svcInfoSplit) == 7 {
			svcName := svcInfoSplit[0]
			svcCPUConsumptionPerReq := svcInfoSplit[1]
			svcCPUAllocated := svcInfoSplit[2]
			svcCPUDemand := svcInfoSplit[3]
			svcPerfBasedAllowedRPS := svcInfoSplit[4]
			svcWeights := svcInfoSplit[5] + "/" + svcInfoSplit[6]
			topo[svcName] = getSvcNodes(svcInfoSplit[6])
			proxywasm.LogCriticalf(
				"setting outbound request weights %v: %v, and svcCPUConsumptionPerReq:%s",
				svcName, svcWeights, svcCPUConsumptionPerReq)
			if err := proxywasm.SetSharedData(svcCPUConsumptionPerReqKey(svcName), []byte(svcCPUConsumptionPerReq), 0); err != nil {
				proxywasm.LogCriticalf("unable to set svcCPUConsumptionPerReq for endpoint distribution %v: %v", svcName, err)
			}
			if err := proxywasm.SetSharedData(svcCPUAllocatedKey(svcName), []byte(svcCPUAllocated), 0); err != nil {
				proxywasm.LogCriticalf("unable to set svcCPUAllocated for endpoint distribution %v: %v", svcName, err)
			}
			if err := proxywasm.SetSharedData(svcCPUDemandKey(svcName), []byte(svcCPUDemand), 0); err != nil {
				proxywasm.LogCriticalf("unable to set svcCPUDemand for endpoint distribution %v: %v", svcName, err)
			}
			if err := proxywasm.SetSharedData(svcPerfBasedAllowedRPSKey(svcName), []byte(svcPerfBasedAllowedRPS), 0); err != nil {
				proxywasm.LogCriticalf("unable to set svcPerfBasedAllowedRPS for endpoint distribution %v: %v", svcName, err)
			}
			if err := proxywasm.SetSharedData(svcName, []byte(svcWeights), 0); err != nil {
				proxywasm.LogCriticalf("unable to set shared data for endpoint distribution %v: %v", svcName, err)
			}
		} else {
			proxywasm.LogCriticalf("received invalid http call response, svcInfo: %s", svcInfo)
			continue
		}
	}
	// set the topo
	// marshal the map svcNodes to json bytes and set shared data with key topoKey()
	topoBytes, err := json.Marshal(topo)
	if err != nil {
		proxywasm.LogCriticalf("unable to marshal svcNodes to json: %v", err)
	} else {
		if err := proxywasm.SetSharedData(topoKey(), topoBytes, 0); err != nil {
			proxywasm.LogCriticalf("unable to set shared data for topo: %v", err)
		}
	}

}

func GetUint64SharedDataOrZero(key string) uint64 {
	data, _, err := proxywasm.GetSharedData(key)
	if err != nil {
		return 0
	}
	if len(data) == 0 {
		return 0
	}
	return binary.LittleEndian.Uint64(data)
}

func GetUint64SharedData(key string) (uint64, error) {
	data, _, err := proxywasm.GetSharedData(key)
	if err != nil {
		return 0, err
	}
	if len(data) == 0 {
		return 0, nil
	}
	return binary.LittleEndian.Uint64(data), nil
}

func getNodeID(nodeName string) (int, error) {

	// Example node: node1.k8s-mplb.mlnetwork.emulab.net

	nodeName = strings.Split(nodeName, ".")[0]
	nodeIDStr := nodeName[4:]
	nodeID, err := strconv.Atoi(nodeIDStr)
	if err != nil {
		return 0, err
	}

	return nodeID, nil
}

// handles race conditions for the shared data while getting a value
// and resetting data
func getAndSetSharedData(dataKey string, setValue []byte) ([]byte, error) {

	data, cas, err := proxywasm.GetSharedData(dataKey)
	if err != nil {
		return nil, err
	}

	// set the shared data to setValue
	if err := proxywasm.SetSharedData(dataKey, setValue, cas); err != nil {
		if err == types.ErrorStatusCasMismatch {
			// try again
			return getAndSetSharedData(dataKey, setValue)
		} else {
			return nil, err
		}
	}

	return data, nil
}

func appendSentReqStats(currentTime, dstSvc, dstPod string) {

	isTsListChangeSuccessful := false

	for !isTsListChangeSuccessful {

		// get the current array of timestamps
		tsList, cas, err := proxywasm.GetSharedData(SENT_REQ_SHARED_QUEUE)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't get shared data for SENT_REQ_SHARED_QUEUE: %v", err)
			// this should never happen
			return
		}

		timeStampStr := fmt.Sprintf("\n%s %s %s", dstSvc, dstPod, currentTime)

		// append the new timestamp to the list
		tsList = append(tsList, []byte(timeStampStr)...)

		// set the new list
		if err := proxywasm.SetSharedData(SENT_REQ_SHARED_QUEUE, tsList, cas); err != nil {
			proxywasm.LogCriticalf("unable to set shared data for SENT_REQ_SHARED_QUEUE: %v", err)
			if errors.Is(err, types.ErrorStatusCasMismatch) {
				proxywasm.LogCriticalf("CAS Mismatch on SENT_REQ_SHARED_QUEUE, failing: %v", err)
			}
		} else {
			proxywasm.LogCriticalf("added timestamp to shared data")
			isTsListChangeSuccessful = true
		}
	}

}

// addToRIF - appends a start event to RIF_SHARED_QUEUE
// Event format: "\nS|reqId|dstPod|timestamp"
func addToRIF(reqId, dstSvc, dstPod string, currentTime int64) {
	event := fmt.Sprintf("\nS|%s|%s|%d", reqId, dstPod, currentTime)
	appendToRIFQueue(event)
	proxywasm.LogCriticalf("added start event to RIF: %s", reqId)
}

// removeFromRIF - appends a finish event to RIF_SHARED_QUEUE
// Event format: "\nF|reqId"
func removeFromRIF(reqId string) {
	event := fmt.Sprintf("\nF|%s", reqId)
	appendToRIFQueue(event)
	proxywasm.LogCriticalf("added finish event to RIF: %s", reqId)
}

// appendToRIFQueue - appends an event to the RIF queue with CAS retry
func appendToRIFQueue(event string) {
	for {
		data, cas, err := proxywasm.GetSharedData(RIF_SHARED_QUEUE)
		if err != nil {
			proxywasm.LogCriticalf("Couldn't get RIF_SHARED_QUEUE: %v", err)
			return
		}

		newData := append(data, []byte(event)...)

		if err := proxywasm.SetSharedData(RIF_SHARED_QUEUE, newData, cas); err != nil {
			if errors.Is(err, types.ErrorStatusCasMismatch) {
				continue // retry
			}
			proxywasm.LogCriticalf("unable to append to RIF_SHARED_QUEUE: %v", err)
			return
		}
		return
	}
}

// processRIFEvents - processes RIF events, handles timeouts, and re-queues pending entries
func processRIFEvents() {
	currentTimeMs := time.Now().UnixMilli()

	// Get and reset RIF queue (same pattern as TIMESTAMPS_SHARED_QUEUE)
	rifData, err := getAndSetSharedData(RIF_SHARED_QUEUE, make([]byte, 8))
	if err != nil {
		proxywasm.LogCriticalf("Couldn't get RIF_SHARED_QUEUE: %v", err)
		return
	}

	rifStr := strings.TrimLeft(string(rifData), "\x00")
	if rifStr == "" {
		return
	}

	// Parse events into started map and finished set
	type startedEntry struct {
		dstPod    string
		timestamp int64
	}
	started := make(map[string]startedEntry)
	finished := make(map[string]bool)

	lines := strings.Split(rifStr, "\n")
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}

		parts := strings.Split(line, "|")
		if len(parts) < 2 {
			continue
		}

		eventType := parts[0]
		reqId := parts[1]

		if eventType == "S" && len(parts) >= 4 {
			timestamp, err := strconv.ParseInt(parts[3], 10, 64)
			if err != nil {
				continue
			}
			started[reqId] = startedEntry{
				dstPod:    parts[2],
				timestamp: timestamp,
			}
		} else if eventType == "F" {
			finished[reqId] = true
		}
	}

	// Process: find timed-out and still-pending
	var stillPending []string
	var timedOutEntries []startedEntry

	for reqId, entry := range started {
		if finished[reqId] {
			// Completed normally, discard
			continue
		}

		if currentTimeMs-entry.timestamp > RIF_ENTRY_TIMEOUT_MS {
			// Timed out
			proxywasm.LogCriticalf("RIF timeout for reqId %s, dstPod %s", reqId, entry.dstPod)
			timedOutEntries = append(timedOutEntries, entry)
		} else {
			// Still in flight - re-queue
			stillPending = append(stillPending, fmt.Sprintf("S|%s|%s|%d", reqId, entry.dstPod, entry.timestamp))
		}
	}

	// Notify LB of timed-out entries
	for _, entry := range timedOutEntries {
		notifyRequestCompletedToLB(entry.dstPod, RIF_ENTRY_TIMEOUT_MS)
	}

	// Re-queue pending entries
	if len(stillPending) > 0 {
		pendingStr := "\n" + strings.Join(stillPending, "\n")
		appendToRIFQueue(pendingStr)
	}
}

func getSvcNodes(svcNodesStr string) []int {

	// format of svcNodesStr: "1|2|3|4"

	svcNodesStrs := strings.Split(svcNodesStr, "|")
	svcNodesInt := make([]int, len(svcNodesStrs))
	for i, svcNodeStr := range svcNodesStrs {
		svcNodeInt, err := strconv.Atoi(svcNodeStr)
		if err != nil {
			proxywasm.LogCriticalf("ERROR: Couldn't parse svc node: %v", err)
			return nil
		} else {
			svcNodesInt[i] = svcNodeInt
		}
	}

	return svcNodesInt

}

func maxIntArray(arr []int) int {
	if len(arr) == 0 {
		return 0 // Return 0 or some other value if the array is empty
	}

	max := arr[0]
	for _, value := range arr {
		if value > max {
			max = value
		}
	}
	return max
}

func inboundCountKey(traceId string) string {
	return traceId + "-inbound-request-count"
}

func spanIdKey(traceId string) string {
	return traceId + "-s"
}

func parentSpanIdKey(traceId string) string {
	return traceId + "-p"
}

func startTimeKey(traceId string) string {
	return traceId + "-startTime"
}

func endTimeKey(traceId string) string {
	return traceId + "-endTime"
}

func bodySizeKey(traceId string) string {
	return traceId + "-bodySize"
}

func firstLoadKey(traceId string) string {
	return traceId + "-firstLoad"
}

func methodKey(traceId string) string {
	return traceId + "-method"
}

func pathKey(traceId string) string {
	return traceId + "-path"
}

func emptyBytes(b []byte) bool {
	for _, v := range b {
		if v != 0 {
			return false
		}
	}
	return true
}

func svcCPUConsumptionPerReqKey(svc string) string {
	return svc + "-cpucons-pr"
}

func svcCPUAllocatedKey(svc string) string {
	return svc + "-cpu-alloc"
}

func svcCPUDemandKey(svc string) string {
	return svc + "-cpu-demand"
}

func svcPerfBasedAllowedRPSKey(svc string) string {
	return svc + "-perf-allowed-rps"
}

func topoKey() string {
	return "topo"
}

func endpointOutstandingReqKey(dstSvc string, endpointNum int) string {
	return fmt.Sprintf("%s-%d-or", dstSvc, endpointNum)
}

func outstandingReqsKey(dstSvc string) string {
	return dstSvc + "-or"
}

func outstandingLoadAtNodesKey() string {
	return "nodal-ol"
}

func localityAwareStatsKey(dstSvc string) string {
	return dstSvc + "-las"
}

func weightedRoundRobinStatsKey(dstSvc string) string {
	return dstSvc + "-wrr"
}

func endpointListKey(method string, path string) string {
	return method + "@" + path
}

func inflightCountKey(method string, path string) string {
	return "inflight/" + method + "-" + path
}

func endpointCountKey(method string, path string) string {
	return "endpointRPS/" + method + "-" + path
}

func endpointInflightStatsKey(traceId string) string {
	return traceId + "-endpointInflightStats"
}

func endpointDistributionKey(svc, method, path string) string {
	return svc + "@" + method + "@" + path + "-distribution"
}

func sharedQueueKey(method, path string) string {
	return method + "@" + path
}

func sharedQueueSizeKey(method, path string) string {
	return method + "@" + path + "-queuesize"
}

func timestampListWritePosKey(method, path string) string {
	return method + "@" + path + "-writepos"
}

func timestampListReadPosKey(method, path string) string {
	return method + "@" + path + "-readpos"
}

func tracedRequest(traceId string) bool {
	// use md5 for speed
	hash := md5Hash(traceId)
	_, _, err := proxywasm.GetSharedData(KEY_HASH_MOD)
	var mod uint32
	if err != nil {
		mod = DEFAULT_HASH_MOD
	} else {
		//mod = binary.LittleEndian.Uint32(modBytes)
		mod = DEFAULT_HASH_MOD

	}
	return hash%int(mod) == 0
}

func md5Hash(s string) int {
	h := md5.New()
	h.Write([]byte(s))
	return int(binary.LittleEndian.Uint64(h.Sum(nil)))
}
