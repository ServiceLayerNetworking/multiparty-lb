set -x
set -e

echo "[SCRIPT] Installing istio..."
curl -L https://istio.io/downloadIstio | sh -
cd "$(find . -maxdepth 1 -type d -name "istio-*" | head -n 1)"
echo "PATH=$PWD/bin:\$PATH" >> ~/.bashrc && source ~/.bashrc
cd ..

echo "run source ~/.bashrc && istioctl version"