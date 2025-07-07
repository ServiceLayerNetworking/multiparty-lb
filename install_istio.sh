set -x
set -e

echo "[SCRIPT] Installing istio..."
curl -L https://istio.io/downloadIstio | sh -
cd "$(find . -maxdepth 1 -type d -name "istio-*" | head -n 1)"
echo "export PATH=$PWD/bin:$PATH" >> ~/.bashrc && source ~/.bashrc
cd ..