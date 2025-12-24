#!/usr/bin/env bash
# Arguments:
# 1: Name of the experiment
# 2: Start node
# 3: End node

# HOSTS_LINES=`./cloudlab/nodes.sh $1 $2 $3 --all`
mapfile -t HOST_LINES < <(./cloudlab/nodes.sh $1 $2 $3 --all)

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

# Tar the scripts, autoscaler and admission directories excluding figures/ and *.pkl
tar -czf $TARBALL --exclude='*.pkl' --exclude='figures/' scripts/ autoscaler/ admission/ bg_stress/ client/ controller-helpers/ jaeger-collector/

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Pushing to $host ..."
  scp ${SCP_PORTS[$i]} -rq -o StrictHostKeyChecking=no $TARBALL $host:~/ >/dev/null 2>&1 &
done
wait

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Building on $host ..."
  ssh ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "tar -xzf $TARBALL 2>&1; cd \$HOME/bg_stress; make" &
done
wait

# Generate gRPC files on control node.
ssh ${SSH_PORTS[0]} -o StrictHostKeyChecking=no ${HOSTS[0]} "cd \$HOME/controller-helpers; python3 -m grpc_tools.protoc -I=. --python_out=. --grpc_python_out=. protos/collector.proto"

# Check if $3 is 4, then generate gRPC files on the client node.
if [ $3 -eq 4 ]; then
  ssh ${SSH_PORTS[4]} -o StrictHostKeyChecking=no ${HOSTS[4]} "cd \$HOME/client; python3 -m grpc_tools.protoc -I=. --python_out=. --grpc_python_out=. protos/collector.proto"
fi

rm -f $TARBALL
echo "Done"
