set -e

docker build -t ghcr.io/talha-waheed/hostagent:latest .
docker push ghcr.io/talha-waheed/hostagent:latest
