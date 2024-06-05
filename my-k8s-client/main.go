package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
)

func main() {

	currTime := time.Now()

	// Define flags for kubeconfig and node name
	kubeconfig := flag.String("kubeconfig", filepath.Join(homeDir(), ".kube", "config"), "(optional) absolute path to the kubeconfig file")
	nodeName := flag.String("node", "", "The name of the Kubernetes node")
	flag.Parse()

	elapsedTime := time.Since(currTime)
	fmt.Println("Time elapsed (1): ", elapsedTime)

	currTime = time.Now()

	// Build the configuration from the kubeconfig file
	config, err := clientcmd.BuildConfigFromFlags("", *kubeconfig)
	if err != nil {
		fmt.Printf("Error building kubeconfig: %s\n", err.Error())
		return
	}

	elapsedTime = time.Since(currTime)
	fmt.Println("Time elapsed (2): ", elapsedTime)

	currTime = time.Now()

	// Create the clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		fmt.Printf("Error creating Kubernetes client: %s\n", err.Error())
		return
	}

	elapsedTime = time.Since(currTime)
	fmt.Println("Time elapsed (3): ", elapsedTime)

	currTime = time.Now()

	// List all pods in the cluster
	pods, err := clientset.CoreV1().Pods("").List(context.TODO(), metav1.ListOptions{})
	if err != nil {
		fmt.Printf("Error listing pods: %s\n", err.Error())
		return
	}

	elapsedTime = time.Since(currTime)
	fmt.Println("Time elapsed (4): ", elapsedTime)

	currTime = time.Now()

	nodeToPods := make(map[string]map[string]string)

	// Iterate through the pods and print the UIDs of pods on the specified node
	fmt.Printf("Pods on node %s:\n", *nodeName)
	for _, pod := range pods.Items {
		if nodeToPods[pod.Spec.NodeName] != nil {
			nodeToPods[pod.Spec.NodeName][pod.Name] = string(pod.UID)
		} else {
			nodeToPods[pod.Spec.NodeName] = make(map[string]string)
			nodeToPods[pod.Spec.NodeName][pod.Name] = string(pod.UID)
		}
		if pod.Spec.NodeName == *nodeName {
			fmt.Printf("Pod Name: %s, UID: %s\n", pod.Name, pod.UID)
		}
	}

	fmt.Println(nodeToPods)

	elapsedTime = time.Since(currTime)
	fmt.Println("Time elapsed (5): ", elapsedTime)
}

// homeDir returns the home directory for the executing user.
func homeDir() string {
	if h := home(); h != "" {
		return h
	}
	return "/"
}

// home returns the value of the HOME environment variable
func home() string {
	return os.Getenv("HOME") // replace with os.Getenv("HOME") in a real application
}
