package main

import (
	"reflect"
	"testing"
)

func TestAggregateNodeOutstandingLoads(t *testing.T) {
	serviceAOutstanding := []int{1, 4}
	serviceBOutstanding := []int{3}

	svcNodes := map[string][]int{
		"svcA": {1, 2},
		"svcB": {1},
	}
	svcOutstandingReqs := map[string]*[]int{
		"svcA": &serviceAOutstanding,
		"svcB": &serviceBOutstanding,
	}
	requestWeights := map[string]float64{
		"svcA": 8,
		"svcB": 2,
	}

	got, err := aggregateNodeOutstandingLoads(svcNodes, svcOutstandingReqs, requestWeights)
	if err != nil {
		t.Fatalf("aggregateNodeOutstandingLoads returned an error: %v", err)
	}

	want := map[int]float64{
		1: 14,
		2: 32,
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected node loads: got %v, want %v", got, want)
	}
}

func TestAggregateNodeOutstandingLoadsRejectsEndpointMismatch(t *testing.T) {
	outstanding := []int{1}

	_, err := aggregateNodeOutstandingLoads(
		map[string][]int{"svcA": {1, 2}},
		map[string]*[]int{"svcA": &outstanding},
		map[string]float64{"svcA": 8},
	)
	if err == nil {
		fatalf := "expected endpoint-count mismatch to return an error"
		t.Fatal(fatalf)
	}
}

func TestCPUWeightsCanChangeTheLeastLoadedNode(t *testing.T) {
	dstOutstanding := []int{0, 0}
	heavyOutstanding := []int{2}
	lightOutstanding := []int{10}

	svcNodes := map[string][]int{
		"dst":   {1, 2},
		"heavy": {1},
		"light": {2},
	}
	svcOutstandingReqs := map[string]*[]int{
		"dst":   &dstOutstanding,
		"heavy": &heavyOutstanding,
		"light": &lightOutstanding,
	}

	requestCounts, err := aggregateNodeOutstandingLoads(
		svcNodes,
		svcOutstandingReqs,
		map[string]float64{"dst": 1, "heavy": 1, "light": 1},
	)
	if err != nil {
		t.Fatalf("request-count aggregation returned an error: %v", err)
	}
	requestCountCandidates := []float64{requestCounts[1], requestCounts[2]}
	if got := getNodalLeastLoadedEndpoint(&requestCountCandidates); got != 0 {
		t.Fatalf("request-count mode selected endpoint %d, want 0", got)
	}

	cpuLoads, err := aggregateNodeOutstandingLoads(
		svcNodes,
		svcOutstandingReqs,
		map[string]float64{"dst": 8, "heavy": 10, "light": 1},
	)
	if err != nil {
		t.Fatalf("CPU-load aggregation returned an error: %v", err)
	}
	cpuLoadCandidates := []float64{cpuLoads[1], cpuLoads[2]}
	if got := getNodalLeastLoadedEndpoint(&cpuLoadCandidates); got != 1 {
		t.Fatalf("CPU-load mode selected endpoint %d, want 1", got)
	}
}
