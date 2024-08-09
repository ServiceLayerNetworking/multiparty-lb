sudo apt update && sudo apt -y full-upgrade
[ -f /var/run/reboot-required ] && sudo reboot -f

# Specify the version of Kubernetes to be installed.
VER=1.30

# Then import GPG key and configure APT repository.
curl -fsSL https://pkgs.k8s.io/core:/stable:/v${VER}/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v${VER}/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Then install required packages.
sudo apt update
sudo apt -y install vim git curl wget kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl

# Confirm installation by checking the version of kubectl.
kubectl version --client && kubeadm version

# # Turn off swap.
# sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Now disable Linux swap space permanently in /etc/fstab. Search for a swap line and add # (hashtag) sign in front of the line.
# sudo vim /etc/fstab
sudo cp /etc/fstab /etc/fstab.bak
sudo sed -i.bak '/swap/ s/^/#/' /etc/fstab
sudo cat /etc/fstab

# Confirm setting is correct
sudo swapoff -a
sudo mount -a
free -h

# Enable kernel modules
sudo modprobe overlay
sudo modprobe br_netfilter

# Add some settings to sysctl
sudo tee /etc/sysctl.d/kubernetes.conf<<EOF
net.bridge.bridge-nf-call-ip6tables = 1
net.bridge.bridge-nf-call-iptables = 1
net.ipv4.ip_forward = 1
EOF

# Reload sysctl
sudo sysctl --system

# Install and Use Docker CE runtime:

# Add repo and Install packages
sudo apt update
sudo apt install -y curl gnupg2 software-properties-common apt-transport-https ca-certificates
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/docker-archive-keyring.gpg
sudo add-apt-repository -y "deb [arch=amd64] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable"
sudo apt update
sudo apt install -y containerd.io docker-ce docker-ce-cli

# Create required directories
sudo mkdir -p /etc/systemd/system/docker.service.d

# Create daemon json config file
sudo tee /etc/docker/daemon.json <<EOF
{
  "exec-opts": ["native.cgroupdriver=systemd"],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m"
  },
  "storage-driver": "overlay2"
}
EOF

# Start and enable Services
sudo systemctl daemon-reload 
sudo systemctl restart docker
sudo systemctl enable docker

#download the latest binary package of cri-dockerd
VER=$(curl -s https://api.github.com/repos/Mirantis/cri-dockerd/releases/latest|grep tag_name | cut -d '"' -f 4|sed 's/v//g')
echo $VER
### For Intel 64-bit CPU ###
wget https://github.com/Mirantis/cri-dockerd/releases/download/v${VER}/cri-dockerd-${VER}.amd64.tgz
tar xvf cri-dockerd-${VER}.amd64.tgz
# ### For ARM 64-bit CPU ###
# wget https://github.com/Mirantis/cri-dockerd/releases/download/v${VER}/cri-dockerd-${VER}.arm64.tgz
# cri-dockerd-${VER}.arm64.tgz

# Move cri-dockerd binary package to /usr/local/bin directory
sudo mv cri-dockerd/cri-dockerd /usr/local/bin/

# Validate successful installation
cri-dockerd --version

# Configure systemd units for cri-dockerd:
wget https://raw.githubusercontent.com/Mirantis/cri-dockerd/master/packaging/systemd/cri-docker.service
wget https://raw.githubusercontent.com/Mirantis/cri-dockerd/master/packaging/systemd/cri-docker.socket
sudo mv cri-docker.socket cri-docker.service /etc/systemd/system/
sudo sed -i -e 's,/usr/bin/cri-dockerd,/usr/local/bin/cri-dockerd,' /etc/systemd/system/cri-docker.service

# Start and enable the services
sudo systemctl daemon-reload
sudo systemctl enable cri-docker.service
sudo systemctl enable --now cri-docker.socket

# Login to the server to be used as master and make sure that the br_netfilter module is loaded:
echo "Login to the server to be used as master and make sure that the br_netfilter module is loaded:"
lsmod | grep br_netfilter

# Enable kubelet service.
sudo systemctl enable kubelet

# We now want to initialize the machine that will run the control plane components which includes etcd (the cluster database) and the API Server.

# Pull container images: (Docker)
sudo kubeadm config images pull --cri-socket unix:///run/cri-dockerd.sock 

## ONLY ON MASTER:

### With Docker CE ###
sudo sysctl -p
sudo kubeadm init \
  --pod-network-cidr=172.24.0.0/16 \
  --cri-socket unix:///run/cri-dockerd.sock 

# init the master node
mkdir -p $HOME/.kube
sudo cp -f /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# get calico
curl -O https://raw.githubusercontent.com/projectcalico/calico/v3.27.4/manifests/tigera-operator.yaml
curl -O https://raw.githubusercontent.com/projectcalico/calico/v3.27.4/manifests/custom-resources.yaml 

kubectl create -f tigera-operator.yaml

sed -ie 's/192.168.0.0/172.24.0.0/g' custom-resources.yaml

kubectl create -f custom-resources.yaml

kubectl get pods --all-namespaces

echo "wait for all pods to get into running state"

## on worker node:
# the kubeadm command to join + --cri-socket unix:///run/cri-dockerd.sock 