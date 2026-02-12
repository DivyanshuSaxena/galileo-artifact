#!/usr/bin/env bash
# Arguments:
# 1: Name of the experiment
# 2: Start node
# 3: End node

# HOSTS_LINES=`./cloudlab/nodes.sh $1 $2 $3 --all`
if builtin mapfile 2>/dev/null; then
  mapfile -t HOST_LINES < <(./cloudlab/nodes.sh $1 $2 $3 --all)
else
  HOST_LINES=()
  while IFS= read -r l; do HOST_LINES+=("$l"); done \
    < <(./cloudlab/nodes.sh $1 $2 $3 --all)
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

for i in "${!HOSTS[@]}"; do
  host=${HOSTS[$i]}
  echo "Setting cpu frequency limits on $host ..."
  ssh -t ${SSH_PORTS[$i]} -o StrictHostKeyChecking=no $host "cd bg_stress; sudo bash fix_cpu_freq.sh"
done