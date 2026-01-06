#!/bin/bash
# Arguments:
# $1: experiment name
# $2: application (reservation/social)

# Check if there are exactly 2 arguments
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <experiment_name> <application>"
  exit 1
fi

EXP_NAME=$1
APP=$2

mapfile -t HOSTS < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)

CONTROL_NODE=${HOSTS[0]}
CLIENT_NODE=${HOSTS[4]}

CONTROL_IP_ADDR="10.10.1.1"

MAX_RESTARTS=3
RESTART_SLEEP_INTERVAL=30
RATE=100

PODS=$(ssh -o StrictHostKeyChecking=no $CONTROL_NODE "kubectl get pods --no-headers 2>/dev/null")
POD_COUNT=$(echo "$PODS" | grep -c '^')
RUNNING=$(echo "$PODS" | grep -c ' Running ')

if [ "$POD_COUNT" -lt 1 ] && [ "$POD_COUNT" -ne "$RUNNING" ]; then
  echo "Cluster health check failed: $POD_COUNT pods found, $RUNNING Running."
  exit 1
fi

RESTART_COUNT=0
CLUSTER_HEALTH=0

while [ $RESTART_COUNT -lt $MAX_RESTARTS ]; do
  # Run the workload from client node, and check the latencies.
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "
    rm -f \$HOME/out/time_${APP}_${RATE}.run &&
    cd \$HOME/scripts/deployment/${APP} &&
    ./run_query.sh -I ${CONTROL_IP_ADDR} -r ${RATE} -l
  "

  # Extract the mean latency from the output file.
  LATENCY=$(ssh -o StrictHostKeyChecking=no $CLIENT_NODE "grep -oP 'Mean\s+=\s+\K[0-9.]+' \$HOME/out/time_${APP}_${RATE}.run")

  # If latency is higher than 100ms, fail the health check -- restart the application.
  if (( $(echo "$LATENCY > 100" | bc -l) )); then
    echo "High latency detected: $LATENCY ms. Restarting application..."
    # Delete the pods and then restart the application.
    ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cd \$HOME/scripts/deployment/${APP}; ./teardown.sh" > /dev/null
    ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cd \$HOME/scripts/deployment/${APP}; ./start.sh" > /dev/null

    ((RESTART_COUNT++))
    sleep ${RESTART_SLEEP_INTERVAL}
  else
    echo "CLUSTER HEALTH CHECK PASSED with latency: $LATENCY ms."
    CLUSTER_HEALTH=1
    break
  fi
done

# If cluster health is not good after max restarts, reset the Kubernetes cluster.
if [ $CLUSTER_HEALTH -eq 0 ]; then
  echo "Cluster health check failed after $MAX_RESTARTS restarts. Resetting Kubernetes cluster..."
  
  # First remove the pods, then call the reset script.
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cd \$HOME/scripts/deployment/${APP}; ./teardown.sh" > /dev/null
  ./cloudlab/reset_k8s.sh ${EXP_NAME} 0 3

  # Finally, restart the application.
  ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cd \$HOME/scripts/deployment/${APP}; ./start.sh" > /dev/null
fi