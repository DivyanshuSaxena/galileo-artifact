#!/usr/bin/env bash
# $1: Name of the experiment
# $2: Experiment type (galileo/...)
# $3: application (reservation/social)
# $4: workload
# $5: results directory
# $6: checkpoint to use - Optional (if not provided, use the base checkpoint)
# $7: if stress (stress/nostress) - Optional
# $8: duration in seconds - Optional (default: 3660s)

# Check if there are at least 5 arguments
if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <experiment_name> <experiment_type> <application> <workload> <results_dir> [checkpoint_path] [if_stress] [duration (S)]"
  exit 1
fi

EXP_NAME=$1
EXP_TYPE=$2
APP=$3
WORKLOAD=$4
CHECKPOINT_PATH=${6:-""}
IF_STRESS=${7:-"nostress"}
TIME=${8:-3660}

# If CHECKPOINT_PATH is not "", split by '/' and get the third last element.
if [[ $CHECKPOINT_PATH != "" ]]; then
  CHECKPOINT=$(echo $CHECKPOINT_PATH | tr "/" "\n" | tail -3 | head -1)
  # If CHECKPOINT_PATH starts with a '~', replace it with $HOME
  if [[ $CHECKPOINT_PATH == ~* ]]; then
    CHECKPOINT_PATH="\$HOME${CHECKPOINT_PATH:1}"
  fi
else
  CHECKPOINT="base"
fi

# Choose the right files based on the application.
if [[ $APP == "reservation" ]]; then
  PROXY="proxy_hotel_reservation.go"
elif [[ $APP == "social" ]]; then
  PROXY="proxy_social_network.go"
fi

RESULTS_DIR=${APP}/${EXP_TYPE}-${WORKLOAD}-${IF_STRESS}-$(date +%d%m-%H%M)
LOCAL_RESULTS_DIR=$5/${RESULTS_DIR}-${CHECKPOINT}
CLOUDLAB_RESULTS_DIR=/proj/wisr-PG0/galileo/${RESULTS_DIR}-${CHECKPOINT}

mapfile -t HOSTS < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)

CONTROL_NODE=${HOSTS[0]}
CLIENT_NODE=${HOSTS[4]}

# Start the background stress jobs.
if [[ $IF_STRESS == "stress" ]]; then
  echo "Start cpu stress on nodes 0-3"
  for host in "${HOSTS[@]:1:3}" ; do
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

# Start tmux sessions on the control node - one for the proxy, another for rl, and third for metrics collection.
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s proxy \"
  rm \$HOME/out/* &&
  cd \$HOME/controller-helpers/proxy &&
  export PATH=\$PATH:/usr/local/go/bin &&
  export GLOBAL_CONFIG_PATH=~/admission/TopFull_master/src/global_config_${APP}.json &&
  go run ${PROXY} > \$HOME/out/proxy.out 2>&1
\""

sleep 5

USE_SHIELD=""
if [[ $EXP_TYPE == "galileo-shield" ]]; then
  USE_SHIELD="--use_shield"
fi

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s rl \"
  cd \$HOME/admission/TopFull_master/src &&
  export GLOBAL_CONFIG_PATH=~/admission/TopFull_master/src/global_config_${APP}.json &&
  python3 deploy_rl.py --checkpoint ${CHECKPOINT_PATH} ${USE_SHIELD} > \$HOME/out/rl.out 2>&1
\""

sleep 5

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s metrics \"
  cd \$HOME/admission/TopFull_master/src &&
  export GLOBAL_CONFIG_PATH=~/admission/TopFull_master/src/global_config_${APP}.json &&
  python3 metric_collector.py > \$HOME/out/metrics.out 2>&1
\""

# Start the perturber process that estimates gradients.
# Only needed for galileo-shield.
if [[ $EXP_TYPE == "galileo-shield" ]]; then
  echo "Starting perturber process on control node"
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s perturber \"
    cd \$HOME/controller-helpers &&
    rm -f current_grads.pkl &&
    python perturber.py --app ${APP} > ~/out/perturber.out 2>&1
  \""
fi

# Run the workload on the client node
echo "Running the workload on client node $CLIENT_NODE"

# If the WORKLOAD has rps in it, then use the traces file, else simply use the WORKLOAD variable.
if [[ $WORKLOAD == *"rps"* ]]; then
  echo "Using traces file for workload"
  WORKLOAD="~/scripts/deployment/production/traces/${WORKLOAD}.txt"
else
  echo "Using a fixed workload"
fi

# Start tmux session on the client node -- for workload generation.
ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux new-session -d -s workload \"
  rm \$HOME/out/* &&
  export PATH=\$HOME/.local/bin:\$PATH &&
  cd \$HOME/client &&
  python3 execute_workload.py ~/out/ locust_${APP}.py http://10.10.1.1:32000 10 3 ${WORKLOAD} 1 0 1 > ~/out/workload.out 2>&1
\""

# Sleep for an hour.
echo "Sleeping for ${TIME}s"
sleep $TIME

# Kill any running stress jobs.
if [[ $IF_STRESS == "stress" ]]; then
  echo "Kill cpu stress on all nodes"
  for host in "${HOSTS[@]:1:3}" ; do
    echo "Kill the CPU stress processes on $host"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_monitor"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_bg"
  done
fi

# Check if any of the tmux sessions are still running - and close them.
echo "Killing control node tmus sessions and any topfull processes."
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t metrics"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep metric_collector | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t rl"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep deploy_rl | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t proxy"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep proxy_hotel_reservation | awk '{print \$2}' | xargs kill -9"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep proxy_social_network | awk '{print \$2}' | xargs kill -9"

# Check if the workload is still running
WORKLOAD_STATUS=$(ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux list-sessions | grep workload")
if [[ -n $WORKLOAD_STATUS ]]; then
  echo "Workload is still running. Killing it and any execute_workload processes."
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux kill-session -t workload"
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "ps aux | grep execute | awk '{print \$2}' | xargs kill -9"
fi

# Get logs from the control node.
echo "Getting logs from the control node"
mkdir -p ${LOCAL_RESULTS_DIR}
pushd ${LOCAL_RESULTS_DIR}
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/admission/TopFull_master/src/logs/* .

if [[ $IF_STRESS == "stress" ]]; then
  # Get the CPU usage logs from the nodes
  index=0
  for host in "${HOSTS[@]:1:3}" ; do 
    echo "Copying CSV file from $host to cpu_$index.csv"
    scp -o StrictHostKeyChecking=no "$host:~/bg_stress/*.csv" "./cpu_$index.csv"
    ((index++))
  done
fi

# Also get all the out/* files from the control node and the client node.
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/out/* .
scp -o StrictHostKeyChecking=no $CLIENT_NODE:~/out/* .
popd