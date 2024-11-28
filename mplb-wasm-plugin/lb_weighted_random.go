package main

import (
	"errors"
	"math/rand"
)

func getNextDstEndpointWeightedRandom(weights []float64) (int, error) {
	coin := rand.Float64()
	total := 0.0

	for endpointNum, weight := range weights {
		pct := weight
		total += pct / 100.0
		if coin <= total {
			return endpointNum, nil
		}
	}

	return -1, errors.New("No endpoint found [Likely cause: sum of weights != 100]")
}
