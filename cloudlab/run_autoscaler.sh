#!/bin/bash
# Arguments:
# $1: experiment name
# $2: experiment type (galileo-norm/galileo-scaled/autothrottle/atplusplus)
# $3: application (reservation/social)
# $4: workload
# $5: delta (change in environment)
# $6: eta (regulate weight of certificate cost)
# $7: results directory
# $8: if stress (stress/nostress) - Optional
# $9: duration in seconds - Optional (default: 3660s)
# $10: multiplier for the workload - Optional (default: 1)

# Check if there are at least 7 arguments
if [[ $# -lt 7 ]]; then
  echo "Usage: $0 <experiment_name> <experiment_type> <application> <workload> <delta> <eta> <results_dir> [if_stress] [duration (S)]"
  exit 1
fi

EXP_NAME=$1
EXP_TYPE=$2
APP=$3
WORKLOAD=$4
DELTA=$5
ETA=$6
IF_STRESS=${8:-"nostress"}
TIME=${9:-3660}
MULTIPLIER=${10:-1}

# Results directory depends on the experiment type
if [[ $EXP_TYPE == *"galileo"* ]]; then
  RESULTS_DIR=${APP}/${EXP_TYPE}-${WORKLOAD}-d${DELTA}-e${ETA}-${IF_STRESS}-$(date +%d%m-%H%M)
elif [[ $EXP_TYPE == "atplusplus" ]]; then
  RESULTS_DIR=${APP}/${EXP_TYPE}-${WORKLOAD}-e${ETA}-${IF_STRESS}-$(date +%d%m-%H%M)
else
  RESULTS_DIR=${APP}/${EXP_TYPE}-${WORKLOAD}-${IF_STRESS}-$(date +%d%m-%H%M)
fi
LOCAL_RESULTS_DIR=$7/${RESULTS_DIR}
CLOUDLAB_RESULTS_DIR=/proj/wisr-PG0/galileo/${RESULTS_DIR}

if builtin mapfile 2>/dev/null; then
  mapfile -t HOSTS < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)
else
  HOSTS=()
  while IFS= read -r l; do HOSTS+=("$l"); done \
    < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)
fi

CONTROL_NODE=${HOSTS[0]}
CLIENT_NODE=${HOSTS[4]}

# Start the controller on the control node
if [[ $EXP_TYPE == *"galileo"* ]]; then
  echo "Starting galileo controller"

  REWARD_TYPE="scaled"
  if [[ $EXP_TYPE == "galileo-norm" ]]; then
    REWARD_TYPE="normalized"
  elif [[ $EXP_TYPE == "galileo-sigmoid" || $EXP_TYPE == "galileo-shield" ]]; then
    REWARD_TYPE="sigmoid"
  elif [[ $EXP_TYPE == "galileo-replace" ]]; then
    REWARD_TYPE="replace"
  fi

  USE_SHIELD=""
  if [[ $EXP_TYPE == "galileo-shield" ]]; then
    USE_SHIELD="--use_shield"
  fi

  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s controller \"
    cd \$HOME/autoscaler &&
    rm -rf ~/logs/* &&
    python reset_allocations.py --app ${APP} &&
    sleep 60 &&
    python controller.py --logs_dir ~/logs/ --app ${APP} --workload ${WORKLOAD} --cert_type gradient --delta ${DELTA} --eta ${ETA} --reward_type ${REWARD_TYPE} ${USE_SHIELD} > ~/out/controller.out 2>&1
  \""
elif [[ $EXP_TYPE == "atplusplus" ]]; then
  echo "Starting autothrottle++ controller"
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s controller \"
    cd \$HOME/autoscaler &&
    rm -rf ~/logs/* &&
    python reset_allocations.py --app ${APP} &&
    sleep 60 &&
    python controller.py --logs_dir ~/logs/ --app ${APP} --workload ${WORKLOAD} --cert_type latency --delta ${DELTA} --eta ${ETA} --reward_type sigmoid > ~/out/controller.out 2>&1
  \""
elif [[ $EXP_TYPE == "autothrottle" ]]; then
  echo "Starting vanilla autothrottle controller -- values of delta and eta will be ignored"
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s controller \"
    cd \$HOME/autoscaler &&
    rm -rf ~/logs/* &&
    python reset_allocations.py --app ${APP} &&
    sleep 60 &&
    python controller.py --logs_dir ~/logs/ --app ${APP} --workload ${WORKLOAD} > ~/out/controller.out 2>&1
  \""
else
  echo "Experiment type not recognized as a controller -- skipping controller start"
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cd \$HOME/autoscaler; rm -rf ~/logs/*; python reset_allocations.py --app ${APP}"
  sleep 60
fi

# Start the perturber process that estimates gradients.
# Only needed for galileo and atplusplus type experiments.
if [[ $EXP_TYPE == *"galileo"* || $EXP_TYPE == "atplusplus" ]]; then
  echo "Starting perturber process on control node"
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s perturber \"
    cd \$HOME/controller-helpers &&
    rm -f current_grads.pkl &&
    python perturber.py --app ${APP} > ~/out/perturber.out 2>&1
  \""
fi

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

# Sleep for sometime for the controller to reset the allocations.
sleep 10

# Run the workload on the client node
echo "Running the workload on client node $CLIENT_NODE"

# If the WORKLOAD has rps in it, then use the traces file, else simply use the WORKLOAD variable.
if [[ $WORKLOAD == *"rps"* ]]; then
  echo "Using traces file for workload"
  WORKLOAD="~/scripts/deployment/production/traces/${WORKLOAD}.txt"
else
  echo "Using a fixed workload"
fi
ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux new-session -d -s workload \"
  export PATH=\$HOME/.local/bin:\$PATH &&
  cd \$HOME/client &&
  rm -f request.log &&
  python3 execute_workload.py ~/logs/ locust_${APP}.py http://10.10.1.1:32000 10 ${MULTIPLIER} ${WORKLOAD} 0 0 1 > ~/out/workload.out 2>&1
\""

# Sleep for an hour.
echo "Sleeping for ${TIME}s"
sleep $TIME

if [[ $IF_STRESS == "stress" ]]; then
  echo "Kill cpu stress on all nodes"
  for host in "${HOSTS[@]:0:4}" ; do
    echo "Kill the CPU stress processes on $host"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_monitor"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_bg"
  done
fi

# Check if the controller is still running
CONTROLLER_STATUS=$(ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux list-sessions | grep controller")
if [[ -n $CONTROLLER_STATUS ]]; then
  echo "Controller is still running. Killing it and any autothrottle processes."
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t controller"
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "ps aux | grep controller | awk '{print \$2}' | xargs kill -9"
fi

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
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/out/controller.out controller.out
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/logs/*.log .

mkdir usage
pushd usage
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/logs/*_usage.pkl .
popd

if [[ $IF_STRESS == "stress" ]]; then
  # Get the CPU usage logs from the nodes
  index=0
  for host in "${HOSTS[@]:0:4}" ; do 
    echo "Copying CSV file from $host to cpu_$index.csv"
    scp -o StrictHostKeyChecking=no "$host:~/bg_stress/*.csv" "./cpu_$index.csv"
    ((index++))
  done
fi

# Get the certificates -- only for galileo and autothrottle++
if [[ $EXP_TYPE == *"galileo"* || $EXP_TYPE == "atplusplus" ]]; then
  mkdir certs
  pushd certs
  scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/logs/certs-* .
  popd
fi
popd

# Also copy the logs to the Cloudlab results directory.
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "mkdir -p ${CLOUDLAB_RESULTS_DIR}; cp -r ~/logs/*.log ${CLOUDLAB_RESULTS_DIR}"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cp ~/logs/*_usage.pkl ${CLOUDLAB_RESULTS_DIR}"
if [[ $EXP_TYPE == *"galileo"* || $EXP_TYPE == "atplusplus" ]]; then
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cp -r ~/logs/certs-* ${CLOUDLAB_RESULTS_DIR}"
fi
