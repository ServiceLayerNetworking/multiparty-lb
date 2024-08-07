#!/bin/bash

NODES=4

# Command to be run
command="minikube start --nodes $((NODES+1)) --cpus 2 --memory 4096 --driver=virtualbox"

# Loop until the command succeeds
until $command; do
	echo "Command failed, retrying..."
	minikube delete --all
	sleep 1 # Optional: wait for a second before retrying
done

echo "Command succeeded."

