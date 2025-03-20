package main

import (
	"io"
	"log"
	"net/http"
)

func echoServer() {

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
