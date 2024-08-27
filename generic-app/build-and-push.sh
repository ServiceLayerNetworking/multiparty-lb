set -e

docker build -t ghcr.io/talha-waheed/generic-app:latest .
docker push ghcr.io/talha-waheed/generic-app:latest
