package main

import "testing"

func TestAggregateRPSLimitIsNotDividedByGatewayCount(t *testing.T) {
	const controllerLimit = 56.25

	if got, want := getAggregateRPSLimit(controllerLimit), 56; got != want {
		t.Fatalf("getAggregateRPSLimit(%v) = %d, want %d", controllerLimit, got, want)
	}
}

func TestAggregateRPSLimitIncludesConfiguredAllowance(t *testing.T) {
	const controllerLimit = 19.75

	if got, want := getAggregateRPSLimit(controllerLimit), 19+RATE_LIMITER_NUM_OF_REQ_ALLOWED_OVER_CPU_ALLOCATED; got != want {
		t.Fatalf("getAggregateRPSLimit(%v) = %d, want %d", controllerLimit, got, want)
	}
}
