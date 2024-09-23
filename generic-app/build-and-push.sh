set -e

go build -o generic_app .
docker build -t ghcr.io/talha-waheed/generic-app:latest .
docker push ghcr.io/talha-waheed/generic-app:latest
