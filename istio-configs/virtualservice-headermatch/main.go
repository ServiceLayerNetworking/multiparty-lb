package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"strings"

	v1alpha32 "istio.io/api/networking/v1alpha3"
	"istio.io/client-go/pkg/apis/networking/v1alpha3"
	versionedistioclient "istio.io/client-go/pkg/clientset/versioned"
	v1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/util/homedir"
)

func main() {
	/*
		For every service,
		1. Get the deployments for each service, and the regions they are in
		2. Create destinationrules for every service, subsetted by region
		3. Create virtualservices for every service, performing header match based on x-slate-routeto header, keyed by region
	*/
	// regions := flag.String("regions", "us-east-1,us-west-1", "regions to check (comma separated, no spaces, like us-east-1,us-west-1)")
	numReplicas := flag.Int("replicas", 3, "max number of replicas for each service")
	services := flag.String("services", "", "services to create vs/drs for. use -exclude to do all except these.")
	exclude := flag.Bool("exclude", false, "exclude the deployments specified in -deployments instead of including them")
	ns := flag.String("namespace", "default", "namespace to check")
	flag.Parse()

	home := homedir.HomeDir()
	kubeconfig := fmt.Sprintf("%s/.kube/config", home)
	config, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
	if err != nil {
		panic(err.Error())
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		panic(err.Error())
	}
	svcClient := clientset.CoreV1().Services(*ns)
	var svcList []string
	if *exclude {
		sList, err := svcClient.List(context.TODO(), v1.ListOptions{})
		if err != nil {
			log.Fatalf("Failed to list services: %s", err)
		}
		var foundMap = make(map[string]struct{})
		for _, svc := range strings.Split(*services, ",") {
			foundMap[svc] = struct{}{}
		}
		for _, svc := range sList.Items {
			if _, ok := foundMap[svc.Name]; !ok {
				svcList = append(svcList, svc.Name)
			}
		}
	} else {
		svcList = strings.Split(*services, ",")
	}

	fmt.Printf("Creating DR/VS for %s\n", svcList)

	restConfig, err := clientcmd.BuildConfigFromFlags("", kubeconfig)
	if err != nil {
		log.Fatalf("Failed to create k8s rest client: %s", err)
	}

	istioclient, err := versionedistioclient.NewForConfig(restConfig)
	if err != nil {
		log.Fatalf("Failed to create istio client: %s", err)
	}
	drClient := istioclient.NetworkingV1alpha3().DestinationRules(*ns)
	vsClient := istioclient.NetworkingV1alpha3().VirtualServices(*ns)

	// Get the list of services
	fmt.Printf("Processing for %s\n", svcList)
	for _, svc := range svcList {
		fmt.Printf("Creating DR/VS for %s\n", svc)
		// first subset by region
		dr := &v1alpha3.DestinationRule{
			ObjectMeta: v1.ObjectMeta{
				Name:      svc + "-dr",
				Namespace: *ns,
			},
			Spec: v1alpha32.DestinationRule{
				Host: svc,
				TrafficPolicy: &v1alpha32.TrafficPolicy{
					LoadBalancer: &v1alpha32.LoadBalancerSettings{
						LbPolicy: &v1alpha32.LoadBalancerSettings_Simple{
							Simple: v1alpha32.LoadBalancerSettings_LEAST_REQUEST,
						},
					},
				},
			},
		}
		for replicaNum := range *numReplicas {
			replicaName := fmt.Sprintf("%s-%d", svc, replicaNum)
			dr.Spec.Subsets = append(dr.Spec.Subsets, &v1alpha32.Subset{
				Name: replicaName,
				Labels: map[string]string{
					"statefulset.kubernetes.io/pod-name": replicaName},
			})
		}
		_, err := drClient.Create(context.Background(), dr, v1.CreateOptions{})
		if err != nil {
			log.Printf("Failed to create destinationrule: %s", err)
		}
		vs := &v1alpha3.VirtualService{
			ObjectMeta: v1.ObjectMeta{
				Name:      svc + "-vs",
				Namespace: *ns,
			},
			Spec: v1alpha32.VirtualService{
				Hosts: []string{svc},
			},
		}
		headerName := "x-lb-endpt"
		// headerName := fmt.Sprintf("x-%s-lb-endpt", svc)
		for replicaNum := range *numReplicas {
			replicaName := fmt.Sprintf("%s-%d", svc, replicaNum)
			// route based on header
			vs.Spec.Http = append(vs.Spec.Http, &v1alpha32.HTTPRoute{
				Match: []*v1alpha32.HTTPMatchRequest{
					{
						Headers: map[string]*v1alpha32.StringMatch{
							headerName: {
								MatchType: &v1alpha32.StringMatch_Exact{
									Exact: replicaName},
							},
						},
					},
				},
				Route: []*v1alpha32.HTTPRouteDestination{
					{
						Destination: &v1alpha32.Destination{
							Host:   svc,
							Subset: replicaName,
						},
					},
				},
			})
		}
		// source label rules, keep traffic local if no header match
		for replicaNum := range *numReplicas {
			replicaName := fmt.Sprintf("%s-%d", svc, replicaNum)
			vs.Spec.Http = append(vs.Spec.Http, &v1alpha32.HTTPRoute{
				Match: []*v1alpha32.HTTPMatchRequest{
					{
						SourceLabels: map[string]string{
							headerName: replicaName,
						},
					},
				},
				Route: []*v1alpha32.HTTPRouteDestination{
					{
						Destination: &v1alpha32.Destination{
							Host:   svc,
							Subset: replicaName,
						},
					},
				},
			})
			vs.Spec.Tcp = append(vs.Spec.Tcp, &v1alpha32.TCPRoute{
				Match: []*v1alpha32.L4MatchAttributes{
					{
						SourceLabels: map[string]string{
							headerName: replicaName,
						},
					},
				},
				Route: []*v1alpha32.RouteDestination{
					{
						Destination: &v1alpha32.Destination{
							Host:   svc,
							Subset: replicaName,
						},
					},
				},
			})
		}
		// final catchall route
		// defaultReplicaName := svc + "-0"
		vs.Spec.Http = append(vs.Spec.Http, &v1alpha32.HTTPRoute{
			Route: []*v1alpha32.HTTPRouteDestination{
				{
					Destination: &v1alpha32.Destination{
						Host: svc,
						// Subset: defaultReplicaName,
					},
				},
			},
		})
		vs.Spec.Tcp = append(vs.Spec.Tcp, &v1alpha32.TCPRoute{
			Route: []*v1alpha32.RouteDestination{
				{
					Destination: &v1alpha32.Destination{
						Host: svc,
						// Subset: defaultReplicaName,
					},
				},
			},
		})
		_, err = vsClient.Create(context.Background(), vs, v1.CreateOptions{})
		if err != nil {
			log.Printf("Failed to create virtualservice: %s", err)
		} else {
			fmt.Printf("Created VS for %s\n", svc)
		}
	}
	fmt.Printf("Done\n")

}
