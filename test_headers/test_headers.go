package main

import (
	"fmt"
	"net/http"
)

func handler(w http.ResponseWriter, r *http.Request) {
	// Access all headers
	fmt.Println("Headers in the HTTP Request:")
	for name, values := range r.Header {
		// Loop over all values for the name
		for _, value := range values {
			fmt.Printf("%s: %s\n", name, value)
		}
	}

	// Access a specific header (e.g., "User-Agent")
	userAgent := r.Header.Get("User-Agent")
	fmt.Printf("\nUser-Agent: %s\n", userAgent)
}

func main() {
	http.HandleFunc("/", handler)
	http.ListenAndServe(":8080", nil)
}
