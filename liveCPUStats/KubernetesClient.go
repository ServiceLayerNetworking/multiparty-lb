package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	v1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
)

type KubernetesClient struct {
	clientset *kubernetes.Clientset
}

func (k8sClient *KubernetesClient) Initialize() {

	// Build the configuration from the kubeconfig file
	config, err := clientcmd.BuildConfigFromFlags(
		"", filepath.Join(getHomeDir(), ".kube", "config"))
	if err != nil {
		slog.Error(
			fmt.Sprintf("Error building kubeconfig: %s\n", err.Error()))
	}

	// Create the clientset
	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		slog.Error(
			fmt.Sprintf("Error creating Kubernetes client: %s\n", err.Error()))
	}

	// Set the clientset
	k8sClient.clientset = clientset
}

func getAppName(pod v1.Pod) string {
	for _, owner := range pod.OwnerReferences {
		if owner.Kind == "StatefulSet" ||
			owner.Kind == "Deployment" ||
			owner.Kind == "ReplicaSet" {
			return owner.Name
		}
	}
	return pod.Name
}

func (k8sClient *KubernetesClient) GetNodesToPodMap() map[string]map[string]Pod {

	// List all pods in the cluster
	pods, err := k8sClient.clientset.CoreV1().Pods("default").List(
		context.TODO(), metav1.ListOptions{})
	if err != nil {
		slog.Error(
			fmt.Sprintf("Error listing pods: %s\n", err.Error()))
	}

	nodeToPods := make(map[string]map[string]Pod)

	// Iterate through the pods and print the UIDs of pods on the specified node
	for _, pod := range pods.Items {

		parentCgroupFolder := strings.ToLower(string(pod.Status.QOSClass)) + "/"
		if parentCgroupFolder == "guaranteed/" {
			parentCgroupFolder = ""
		}

		if nodeToPods[pod.Spec.NodeName] != nil {
			nodeToPods[pod.Spec.NodeName][pod.Name] = Pod{
				Name:           pod.Name,
				AppName:        getAppName(pod),
				FShare:         0.0,
				CGroupFilePath: parentCgroupFolder + "pod" + string(pod.UID),
			}
		} else {
			nodeToPods[pod.Spec.NodeName] = make(map[string]Pod)
			nodeToPods[pod.Spec.NodeName][pod.Name] = Pod{
				Name:           pod.Name,
				AppName:        getAppName(pod),
				FShare:         0.0,
				CGroupFilePath: parentCgroupFolder + "pod" + string(pod.UID),
			}
		}
	}

	for _, pod := range pods.Items {
		numPods := len(nodeToPods[pod.Spec.NodeName])
		nodeToPods[pod.Spec.NodeName][pod.Name] = Pod{
			Name:           nodeToPods[pod.Spec.NodeName][pod.Name].Name,
			AppName:        nodeToPods[pod.Spec.NodeName][pod.Name].AppName,
			FShare:         1 / float64(numPods),
			CGroupFilePath: nodeToPods[pod.Spec.NodeName][pod.Name].CGroupFilePath,
		}
	}

	return nodeToPods
}

func (k8sClient *KubernetesClient) GetNodes() []Node {

	// List all nodes in the cluster
	nodes, err := k8sClient.clientset.CoreV1().Nodes().List(
		context.TODO(), metav1.ListOptions{})
	if err != nil {
		slog.Error(
			fmt.Sprintf("Error listing nodes: %s\n", err.Error()))
	}

	nodesToPods := k8sClient.GetNodesToPodMap()

	nodeList := make([]Node, 0)

	// Print the names of the nodes
	for _, node := range nodes.Items {

		nodeNum := getNodeNum(node)
		cpuCapacity := node.Status.Capacity[v1.ResourceCPU]
		cpuMilliCores := int(cpuCapacity.MilliValue())
		nodeList = append(nodeList,
			Node{
				Num:               nodeNum,
				Name:              node.Name,
				IP:                getNodeInternalIP(node),
				HostAgentNodePort: k8sClient.getHostAgentNodePort(node),
				Pods:              nodesToPods[node.Name],
				MilliCores:        cpuMilliCores,
			})
	}

	return nodeList
}

func (k8sClient *KubernetesClient) getHostAgentNodePort(node v1.Node) int {

	serviceName := "hostagent-" + node.Labels["node-role.kubernetes.io/worker"]
	if node.Labels["node-role.kubernetes.io/worker"] == "" {
		serviceName = "hostagent-node0"
	}

	// Get the specified service
	service, err := k8sClient.clientset.CoreV1().Services("default").Get(
		context.TODO(), serviceName, metav1.GetOptions{})
	if err != nil {
		slog.Error(
			fmt.Sprintf(
				"Error getting service %s: %s\n", serviceName, err.Error()))
	}

	// Find and print the NodePort
	nodePort := 0
	for _, port := range service.Spec.Ports {
		if port.Name == "cc" {
			nodePort = int(port.NodePort)
			break
		}
	}

	if nodePort == 0 {
		slog.Error(
			fmt.Sprintf("No cc NodePort for service %s\n", serviceName))
	}

	return nodePort
}

func getNodeNum(node v1.Node) int {

	if node.Labels["node-role.kubernetes.io/worker"] == "" {
		return 0
	}

	nodeNumStr := node.Labels["node-role.kubernetes.io/worker"][4:]
	nodeNum, err := strconv.Atoi(nodeNumStr)
	if err != nil {
		slog.Error(
			fmt.Sprintf("Error converting node number: %s\n", err.Error()))
	}
	return nodeNum
}

func getNodeInternalIP(node v1.Node) string {
	for _, addr := range node.Status.Addresses {
		if addr.Type == v1.NodeInternalIP {
			return addr.Address
		}
	}
	return ""
}

func extractIntFromString(s string) (int, error) {
	num, err := strconv.Atoi(s)
	if err == nil {
		return num, nil
	}
	return 0, err
}

// homeDir returns the home directory for the executing user.
func getHomeDir() string {
	if h := getHome(); h != "" {
		return h
	}
	return "/"
}

// home returns the value of the HOME environment variable
func getHome() string {
	return os.Getenv("HOME")
}
