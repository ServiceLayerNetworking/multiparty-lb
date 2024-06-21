set -e

# for cloudlab
GOARCH=wasm GOOS=js /usr/local/bin/tinygo build -o wasm-out/routing_plugin.wasm  -target=wasi main.go

# # from slate's repo:
# GOARCH=wasm GOOS=js /usr/local/bin/tinygo build -o wasm-out/routing_plugin.wasm -gc=custom -tags="custommalloc nottinygc_envoy" -scheduler=none -target=wasi main.go
# for aditya: tinygo location is different
#  GOARCH=wasm GOOS=js $HOME/go/bin/tinygo build -o wasm-out/routing_plugin.wasm -gc=custom -tags="custommalloc nottinygc_envoy" -scheduler=none -target=wasi main.go


docker build -t ghcr.io/talha-waheed/routing-plugin:latest .
docker push ghcr.io/talha-waheed/routing-plugin:latest
