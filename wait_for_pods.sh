#!/bin/bash

NAMESPACE=default  # Specify the namespace you want to check, default is "default"
CHECK_INTERVAL=5   # Time interval between checks in seconds

# Function to check if all pods are running
check_pods() {
  # Get the status of all pods in the specified namespace
  POD_STATUSES=$(kubectl get pods -n $NAMESPACE --no-headers -o custom-columns=:status.phase)

  # Check if there are any pods that are not in "Running" state
  for STATUS in $POD_STATUSES; 
  do
    if [ "$STATUS" != "Running" ]; then
      return 1
    fi
  done

  return 0
}

# Loop until all pods are running
while true; do
  check_pods
  if [ $? -eq 0 ]; then
    echo "All pods are running."
    exit 0
  else
    echo "Not all pods are running. Checking again in $CHECK_INTERVAL seconds..."
    sleep $CHECK_INTERVAL
  fi
done
