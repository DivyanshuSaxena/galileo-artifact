#!/usr/bin/env bash
# Arguments:
# 1: Name of the experiment
# 2: Start node
# 3: End node

# Check if there are atleast 3 arguments
if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <experiment_name> <start_node> <end_node>"
  exit 1
fi

# HOSTS_LINES=`./cloudlab/nodes.sh $1 $2 $3 --all`
mapfile -t HOST_LINES < <(./cloudlab/nodes.sh $1 $2 $3 --all)

# Save in a variable -- needed later.
EXP_NAME=$1

# Flag to denote whether the VM cluster is being used.
VM_CLUSTER=0

# Split the elements of HOSTS into HOSTS and PORTS, if ports are provided.
HOSTS=()
SSH_PORTS=()
SCP_PORTS=()
for i in "${!HOST_LINES[@]}"; do
  # If the line contains "-p", then extract the port and host
  if [[ ${HOST_LINES[$i]} == *"-p"* ]]; then
    # Extract the port and host - "-p <port> <host>"
    PORT=`echo ${HOST_LINES[$i]} | awk '{print $2}'`
    HOST=`echo ${HOST_LINES[$i]} | awk '{print $3}'`
    HOSTS+=($HOST)
    SSH_PORTS+=("-p $PORT")
    SCP_PORTS+=("-P $PORT")

    VM_CLUSTER=1
  else
    SSH_PORTS+=("")
    SCP_PORTS+=("")
    HOSTS+=(${HOST_LINES[$i]})
  fi
done

echo ${SSH_PORTS[@]}
echo ${SCP_PORTS[@]}
echo ${HOSTS[@]}

echo "Configuring geni keys access for all nodes"
for host in "${HOSTS[@]}"; do
  echo $host
  ssh -o StrictHostKeyChecking=no $host "tmux new-session -d -s ssh-keys \"
    mkdir -p \$HOME/.ssh && chmod 700 \$HOME/.ssh &&

    geni-get key > \$HOME/.ssh/id_rsa &&
    chmod 600 \$HOME/.ssh/id_rsa &&

    ssh-keygen -y -f \$HOME/.ssh/id_rsa > \$HOME/.ssh/id_rsa.pub &&

    grep -q -f \$HOME/.ssh/id_rsa.pub \$HOME/.ssh/authorized_keys2 || cat \$HOME/.ssh/id_rsa.pub >> \$HOME/.ssh/authorized_keys2
    \""
done

TARBALL=testbed.tar.gz
tar -czf $TARBALL scripts/ admission/ autoscaler/

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Pushing to $host ${SCP_PORTS[$i]}"
  scp ${SCP_PORTS[$i]} -rq -o StrictHostKeyChecking=no $TARBALL $host:~/ >/dev/null 2>&1 &
done
wait

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "tar -xzf $TARBALL 2>&1" &
done
wait

rm -f $TARBALL

# Increase space on the nodes, if not VM cluster.
if [[ ${VM_CLUSTER} -eq 0 ]]; then
  for host in "${HOSTS[@]}" ; do
    echo "Configuring dependencies for $host"
    ssh -o StrictHostKeyChecking=no $host "tmux new-session -d -s config \"
      sudo mkdir -p /mydata &&
      sudo /usr/local/etc/emulab/mkextrafs.pl -f /mydata &&

      pushd /mydata/local &&
      sudo chmod 775 -R . &&
      popd\""

  done
fi

# Get the control node (first node in the first line of $HOSTS)
# CONTROL_NODE=$(echo $HOSTS | head -1 | awk '{print $1}')
CONTROL_NODE=${HOSTS[0]}
CONTROL_PORT_SSH=${SSH_PORTS[0]}
CONTROL_PORT_SCP=${SCP_PORTS[0]}

# Setup control node
echo "Building on control node ${CONTROL_NODE} ${CONTROL_PORT_SSH}"
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_NODE} "cd \$HOME; ./scripts/install_docker.sh --init --control --cni flannel > install_docker.log 2>&1"

# Get the join command
scp ${CONTROL_PORT_SCP} -rq -o StrictHostKeyChecking=no ${CONTROL_NODE}:~/command.txt command${EXP_NAME}.txt >/dev/null 2>&1

# Get the admin.conf file
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_NODE} "cd \$HOME; sudo cp /etc/kubernetes/admin.conf .; sudo chmod 644 admin.conf"
scp ${CONTROL_PORT_SCP} -rq -o StrictHostKeyChecking=no ${CONTROL_NODE}:~/admin.conf admin${EXP_NAME}.conf >/dev/null 2>&1

# Setup worker nodes
for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  if [[ $i != 0 ]]; then
    echo "Preparing $host ${SCP_PORTS[$i]} ..."
    scp ${SCP_PORTS[$i]} -rq -o StrictHostKeyChecking=no command${EXP_NAME}.txt $host:~/command.txt >/dev/null 2>&1
    scp ${SCP_PORTS[$i]} -rq -o StrictHostKeyChecking=no admin${EXP_NAME}.conf $host:~/admin.conf >/dev/null 2>&1

    if [[ ${VM_CLUSTER} -eq 0 ]]; then
      ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "cd \$HOME; sudo ./scripts/install_docker.sh --init > install_docker.log 2>&1" &
    else
      ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "cd \$HOME; sudo ./scripts/install_docker_vm.sh --init > install_docker.log 2>&1" &
    fi
  fi
done
wait

rm command${EXP_NAME}.txt
rm admin${EXP_NAME}.conf

# After joining the nodes, make a rollout restart of coredns on control node.
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_NODE} "kubectl -n kube-system rollout restart deployment coredns"

# Also install kubernetes metrics server
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_NODE} "kubectl apply -f \$HOME/admission/TopFull_master/deployments/metric-server-latest.yaml"

for i in "${!HOSTS[@]}" ; do
  host=${HOSTS[$i]}
  echo "Configuring dependencies for $host ${SSH_PORTS[$i]}"
  ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "tmux new-session -d -s config \"
    cd \$HOME &&
    sudo apt-get update &&
    sudo apt-get install -y clang llvm gcc-multilib libelf-dev libpcap-dev build-essential libssl-dev &&
    sudo apt-get install -y jq &&
    
    curl https://bootstrap.pypa.io/pip/3.6/get-pip.py -o get-pip.py &&
    python3 get-pip.py &&
    python3 -m pip install --upgrade pip &&
    python3 -m pip install psutil asyncio aiohttp &&
    python3 -m pip install grpcio requests &&
    python3 -m pip install scipy gym vowpalwabbit &&
    python3 -m pip install matplotlib &&
    python3 -m pip install --upgrade 'protobuf<=3.20.1' &&
    python3 -m pip install --upgrade 'grpcio-tools<=1.49.0' &&
    python3 -m pip install -r \$HOME/admission/TopFull_master/requirements.txt &&
    
    wget https://go.dev/dl/go1.20.7.linux-amd64.tar.gz &&
    sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.20.7.linux-amd64.tar.gz &&
    echo 'export PATH=\$PATH:/usr/local/go/bin' >> ~/.bashrc &&
    rm go1.20.7.linux-amd64.tar.gz &&

    pushd \$HOME/admission/TopFull_master &&
    kubectl kustomize cadvisor | kubectl apply -f - &&
    popd &&

    mkdir -p \$HOME/out &&
    mkdir -p \$HOME/logs\""

done
