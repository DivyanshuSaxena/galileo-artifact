#!/bin/bash
# Install Docker, Kubernetes, and other dependencies.

showHelp() {
cat << EOF  
Usage: <script_name> [-ic] [-n]
Install docker, kubernetes and helm.

-h, -help,      --help        Display help
-i, -init,      --init        Whether installing docker for the first time
-c, -control,   --control     Is the node a control node
-n, -cni,       --cni         Install CNI plugin (flannel/calico/cilium)

EOF
}

INIT=0
IS_CONTROL_NODE=0
CNI="flannel"

options=$(getopt -l "help,init,control,cni:" -o "hicn:" -a -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -h|--help) 
      showHelp
      exit 0
      ;;
  -i|--init)
      INIT=1
      ;;
  -c|--control)
      IS_CONTROL_NODE=1
      ;;
  -n|--cni)
      shift
      CNI=$1
      ;;
  --)
      shift
      break;;
  esac
  shift
done

# Check if init
if [[ $INIT -eq 1 ]]; then
  # <=========== Install Docker ===========>
  sudo apt --fix-broken install -y
  sudo apt-get update

  sudo apt-get install -y \
      ca-certificates \
      curl \
      gnupg \
      lsb-release \
      tmux

  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --batch --yes --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    "$(. /etc/os-release && echo "$UBUNTU_CODENAME")" stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update

  sudo apt-get install -y docker-ce=5:25.0.5-1~ubuntu.22.04~jammy docker-ce-cli=5:25.0.5-1~ubuntu.22.04~jammy containerd.io docker-compose-plugin

  # Change the data-root for docker
  mkdir -p /mydata/local/docker
  echo "{ \"data-root\": \"/mydata/local/docker\" }" | sudo tee /etc/docker/daemon.json
  sudo systemctl restart docker

  # Add user to docker group
  sudo groupadd docker
  sudo usermod -aG docker $USER

  # Adding a sleep so that kubernetes can be installed after docker
  sleep 30

  # <============= Prepare for k8s ============>
  # Install CRI-docker, needed by kubeadm to interact with docker engine
  wget https://github.com/Mirantis/cri-dockerd/releases/download/v0.3.13/cri-dockerd_0.3.13.3-0.ubuntu-jammy_amd64.deb
  sudo chmod +x cri-dockerd_0.3.13.3-0.ubuntu-jammy_amd64.deb
  sudo dpkg -i cri-dockerd_0.3.13.3-0.ubuntu-jammy_amd64.deb

  sudo swapoff -a

  # <=========== Install Kubernetes ===========>
  # Install Kubectl
  sudo apt-get update
  sudo apt-get install -y apt-transport-https ca-certificates curl

  curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.30/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
  sudo chmod 644 /etc/apt/keyrings/kubernetes-apt-keyring.gpg
  echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.30/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
  sudo chmod 644 /etc/apt/sources.list.d/kubernetes.list

  sudo apt-get update
  sudo apt-get install -y kubelet kubeadm kubectl

  sudo rm -f /etc/containerd/config.toml

  # Change the root directory for containerd
  sudo mkdir -p /mydata/local/containerd
  echo "root = \"/mydata/local/containerd\"" | sudo tee /etc/containerd/config.toml
  sudo systemctl restart containerd

  # <============== Install Helm ==============>
  curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

  if [[ ${IS_CONTROL_NODE} -eq 1 ]]; then
    # Install CRI Tools
    wget https://github.com/kubernetes-sigs/cri-tools/releases/download/v1.26.0/crictl-v1.26.0-linux-amd64.tar.gz
    sudo tar zxvf crictl-v1.26.0-linux-amd64.tar.gz -C /usr/local/bin
    rm -f crictl-v1.26.0-linux-amd64.tar.gz
  fi
fi

# Reset kubadm, if already present.
sudo kubeadm reset -f --cri-socket=unix:///var/run/cri-dockerd.sock
sudo rm -rf ~/.kube

if [[ ${IS_CONTROL_NODE} -eq 0 ]]; then
  CMD=$(cat command.txt)
  sudo $CMD
else
  echo "Setting up Control Node"
  if [[ $CNI == "calico" ]]; then
    sudo kubeadm init --pod-network-cidr=192.168.0.0/16 --cri-socket=unix:///var/run/cri-dockerd.sock
  else
    sudo kubeadm init --pod-network-cidr=10.244.0.0/16 --cri-socket=unix:///var/run/cri-dockerd.sock
  fi

  mkdir -p $HOME/.kube
  sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
  sudo chown $(id -u):$(id -g) $HOME/.kube/config

  if [[ $CNI == "calico" ]]; then
    sudo kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.3/manifests/tigera-operator.yaml
    sudo kubectl create -f https://raw.githubusercontent.com/projectcalico/calico/v3.27.3/manifests/custom-resources.yaml
    sleep 30
  elif [[ $CNI == "flannel" ]]; then
    sudo kubectl apply -f https://raw.githubusercontent.com/coreos/flannel/master/Documentation/kube-flannel.yml
  fi

  sleep 10
  
  CMD=$(sudo kubeadm token create --print-join-command)
  echo "$CMD --cri-socket=unix:///var/run/cri-dockerd.sock" > ./command.txt

  # Mark this node for scheduling as well
  kubectl taint nodes --all node-role.kubernetes.io/control-plane-
fi
