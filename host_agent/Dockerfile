FROM --platform=linux/amd64 golang:1.22.2

# Set the Current Working Directory inside the container
WORKDIR /app/host_agent

# We want to populate the module cache based on the go.{mod,sum} files.
COPY go.mod .

RUN go mod download

COPY . .

# Build the Go app
RUN go build -o ./host_agent .

# This container exposes port 9988 to the outside world
EXPOSE 9988

# Run the binary program produced by `go install`
CMD ["./host_agent"]
