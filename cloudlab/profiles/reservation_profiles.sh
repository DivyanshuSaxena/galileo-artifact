#!/usr/bin/env bash
# Starts the experiment to run a long running workload and 
# Arguments:
# 1: Name of the experiment
# 2: Workload rate to use for the experiment
# 3: Number of samples to collect
# 4: Name for the log
# 5: Workload to use (search/user/reserve/recommend/search_user/user_reserve/search_recommend/all)
# 6: Distribution to use for the workload (zipf/exp/norm)
# 7: Directory to put the output files
# 8: if stress (stress/nostress) - Optional

# Check arguments
if [ $# -lt 7 ]; then
  echo "Usage: <script_name> <experiment_name> <rate> <num_samples> <name> <workload> <dist> <output_dir> <if_stress>"
  exit 1
fi

START_NODE=0
END_NODE=4

mapfile -t HOST_LINES < <(./cloudlab/nodes.sh $1 ${START_NODE} ${END_NODE} --all)

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

# Set the control host and ports
CONTROL_HOST=${HOSTS[${START_NODE}]}
CONTROL_PORT_SSH=${SSH_PORTS[${START_NODE}]}
CONTROL_PORT_SCP=${SCP_PORTS[${START_NODE}]}

# Set the client host and ports
CLIENT_HOST=${HOSTS[${END_NODE}]}
CLIENT_PORT_SSH=${SSH_PORTS[${END_NODE}]}
CLIENT_PORT_SCP=${SCP_PORTS[${END_NODE}]}

echo "Control host: ${CONTROL_HOST} ${CONTROL_PORT_SSH} ${CONTROL_PORT_SCP}"
echo "Client host: ${CLIENT_HOST} ${CLIENT_PORT_SSH} ${CLIENT_PORT_SCP}"

RATE=$2
SAMPLES=$3
NAME=$4
WORKLOAD=$5
DIST=$6
IF_STRESS=${8:-"nostress"}

# List of ip addresses of the nodes
IP_ADDR=(10.10.1.1 10.10.1.2 10.10.1.3 10.10.1.4)

# Start a long running workload generation on the client host.
echo "Starting workload generation on ${CLIENT_HOST} ..."

# Split WORKLOAD at "_" and get the workloads to run.
LOADS=$(echo $WORKLOAD | tr "_" "\n")

# Execute each workload in the list.
for load in $LOADS; do
  echo "Starting workload ${load} ..."
  ssh ${CLIENT_PORT_SSH} -o StrictHostKeyChecking=no ${CLIENT_HOST} "tmux new-session -d -s workload${load} \"
    pushd \$HOME/scripts/deployment/reservation &&
    ./run_query.sh -I ${IP_ADDR[${START_NODE}]} -r $RATE -l -t $load -D ${DIST} -j &&
    popd\""
done

if [[ $IF_STRESS == "stress" ]]; then
  echo "Start cpu stress on nodes 0-3"
  for host in "${HOSTS[@]:0:4}" ; do
    ssh -o StrictHostKeyChecking=no $host "tmux new-session -d -s cpu_bg \"
      cd \$HOME/bg_stress &&
      make &&
      ./cpu_stress 16
    \""
    ssh -o StrictHostKeyChecking=no $host "tmux new-session -d -s cpu_monitor \"
      cd \$HOME/bg_stress &&
      python3 CPU_usage.py --no-plot
    \""
  done
fi

sleep 30

# Run the jaeger query on the control node.
echo "Starting jaeger query on ${CONTROL_HOST} ..."
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_HOST} "pushd \$HOME/scripts/utils; ./query_jaeger.sh -r $RATE -s $SAMPLES; popd"

# Stop the workload generation on the client host.
echo "Stopping workload generation on ${CLIENT_HOST} ..."
for load in $LOADS; do
  ssh ${CLIENT_PORT_SSH} -o StrictHostKeyChecking=no ${CLIENT_HOST} "tmux kill-session -t workload${load}"
done

# Killing the cpu stress processes.
if [[ $IF_STRESS == "stress" ]]; then
  echo "Kill cpu stress on all nodes"
  for host in "${HOSTS[@]:0:4}" ; do
    echo "Kill the CPU stress processes on $host"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_monitor"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_bg"
  done
fi

# Get the stats from the control node.
mkdir -p $7/reservation_rate${RATE}_${DIST}_${NAME}_${IF_STRESS}
pushd $7/reservation_rate${RATE}_${DIST}_${NAME}_${IF_STRESS}
echo "Getting stats from ${CONTROL_HOST} ..."
scp ${CONTROL_PORT_SCP} -o StrictHostKeyChecking=no ${CONTROL_HOST}:~/out/traces*.pkl .

# Also get the stats from the client node.
echo "Getting stats from ${CLIENT_HOST} ..."
scp ${CLIENT_PORT_SCP} -o StrictHostKeyChecking=no ${CLIENT_HOST}:~/out/*.run .

if [[ $IF_STRESS == "stress" ]]; then
  # Get the CPU usage logs from the nodes
  index=0
  for host in "${HOSTS[@]:0:4}" ; do 
    echo "Copying CSV file from $host to cpu_$index.csv"
    scp -o StrictHostKeyChecking=no "$host:~/bg_stress/*.csv" "./cpu_$index.csv"
    ((index++))
  done
fi
popd

# Remove the pkl files from the control node and the run files from the client node.
ssh ${CONTROL_PORT_SSH} -o StrictHostKeyChecking=no ${CONTROL_HOST} "rm -f ~/out/traces*.pkl"
ssh ${CLIENT_PORT_SSH} -o StrictHostKeyChecking=no ${CLIENT_HOST} "rm -f ~/out/*.run"
