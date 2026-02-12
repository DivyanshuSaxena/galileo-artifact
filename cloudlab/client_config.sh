#!/usr/bin/env bash
# Arguments:
# 1: Name of the experiment
# 2: Client node

# HOSTS=`./cloudlab/nodes.sh $1 $2 $2 --all`
if builtin mapfile 2>/dev/null; then
  mapfile -t HOST_LINES < <(./cloudlab/nodes.sh $1 $2 $2 --all)
else
  HOST_LINES=()
  while IFS= read -r l; do HOST_LINES+=("$l"); done \
    < <(./cloudlab/nodes.sh $1 $2 $2 --all)
fi

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
  else
    SSH_PORTS+=("")
    SCP_PORTS+=("")
    HOSTS+=(${HOST_LINES[$i]})
  fi
done

TARBALL=testbed.tar.gz
tar -czf $TARBALL admission/ autoscaler/ scripts/ client/

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Pushing to $host ..."
  scp ${SCP_PORTS[$i]} -rq -o StrictHostKeyChecking=no $TARBALL $host:~/ >/dev/null 2>&1 &
done
wait

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "tar -xzf $TARBALL 2>&1" &
done
wait

rm -f $TARBALL

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Configuring dependencies for $host"
  ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "tmux new-session -d -s config \"
    cd \$HOME &&
    sudo apt-get update &&
    sudo apt install -y clang llvm gcc-multilib libelf-dev libpcap-dev libssl-dev build-essential &&
    
    pushd scripts/deployment &&
    cp -r /proj/wisr-PG0/galileo/traces . &&
    popd &&

    curl https://bootstrap.pypa.io/pip/3.6/get-pip.py -o get-pip.py &&
    python3 get-pip.py &&
    python3 -m pip install psutil asyncio aiohttp &&
    python3 -m pip install locust &&
    python3 -m pip install numpy &&
    python3 -m pip install --upgrade 'protobuf<=3.20.1' &&
    python3 -m pip install --upgrade 'grpcio-tools<=1.49.0' &&

    sudo apt install -y luarocks &&
    sudo luarocks install luasocket &&

    git clone -b galileo https://github.com/DivyanshuSaxena/DeathStarBench.git &&
    pushd DeathStarBench/wrk2 &&
    make -j 4 &&
    popd &&

    pushd \$HOME/client &&
    python3 -m grpc_tools.protoc -I=. --python_out=. --grpc_python_out=. protos/collector.proto &&
    popd &&

    mkdir -p \$HOME/out &&
    mkdir -p \$HOME/logs\""

done
