#!/bin/bash
# Get the CPU throttle ratio for the pod of the given service.
# 1: service name
# 2: whether running the script on the control node (0 or 1)

SERVICE=$1
CONTROL_NODE=$2

KUBECTL="kubectl"
if [ $CONTROL_NODE -eq 0 ]; then
  KUBECTL="kubectl --kubeconfig=$HOME/admin.conf"
fi

CGROUP_PATH="/sys/fs/cgroup/kubepods.slice"

# <=========== Change CPU throttle ratio for the pod of the given service ===========>
# Get the CPU throttle ratio file in the container cgroup.
POD_IPS=$($KUBECTL get endpoints $SERVICE -o=jsonpath='{.subsets[*].addresses[*].ip}')
CMD="$KUBECTL get pods -o custom-columns=PodName:.metadata.name,PodUID:.metadata.uid,PodIP:.status.podIP"

$CMD | grep $SERVICE | while read -r POD_INFO; do
  POD_IP=$(echo $POD_INFO | awk '{print $3}')
  if [[ ! $POD_IPS =~ $POD_IP ]]; then
    continue
  fi

  # Extract Pod UID and replace '-' with '_' in the Pod UID.
  POD_UID=$(echo $POD_INFO | awk '{print $2}' | sed 's/-/_/g')

  # Get the cgroup path for the pod.
  POD_CGROUP="kubepods-burstable.slice/kubepods-burstable-pod${POD_UID}.slice"

  # Check if the POD_CGROUP exists.
  if [ ! -d "$CGROUP_PATH/$POD_CGROUP" ]; then
    # Use the besteffort cgroup if burstable is not found.
    POD_CGROUP="kubepods-besteffort.slice/kubepods-besteffort-pod${POD_UID}.slice"
  fi

  # If neither burstable nor besteffort is found, then skip this pod.
  if [ ! -d "$CGROUP_PATH/$POD_CGROUP" ]; then
    echo "No cgroup found for $SERVICE ..."
    continue
  fi

  # Read the CPU nr_throttled value from the cpu.stat file.
  CPU_THROTTLED=$(cat $CGROUP_PATH/$POD_CGROUP/cpu.stat | grep nr_throttled | awk '{print $2}')
  NR_PERIODS=$(cat $CGROUP_PATH/$POD_CGROUP/cpu.stat | grep nr_periods | awk '{print $2}')
  
  # Read the CPU usage from the cpu.stat file.
  CPU_USAGE=$(cat $CGROUP_PATH/$POD_CGROUP/cpu.stat | grep usage_usec | awk '{print $2}')
  
  echo "Stats: $CPU_THROTTLED $CPU_USAGE $NR_PERIODS"
done
