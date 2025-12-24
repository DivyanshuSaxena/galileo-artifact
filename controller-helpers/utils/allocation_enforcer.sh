#!/bin/bash
# Enforce the CPU allocation for the pod of the given service.
# 1: service name
# 2: CPU allocation
# 3: whether running the script on the control node (0 or 1)

SERVICE=$1
CPU_ALLOC=$2
CONTROL_NODE=$3

KUBECTL="kubectl"
if [ $CONTROL_NODE -eq 0 ]; then
  KUBECTL="kubectl --kubeconfig=$HOME/admin.conf"
fi

NODE=$(hostname | cut -d'.' -f1)
CGROUP_PATH="/sys/fs/cgroup/kubepods.slice"

# <=========== Change CPU allocation for the pod of the given service ===========>
# Get the CPU allocation file in the container cgroup.
POD_IPS=$($KUBECTL get endpoints $SERVICE -o=jsonpath='{.subsets[*].addresses[*].ip}')
CMD="$KUBECTL get pods -o custom-columns=PodName:.metadata.name,PodUID:.metadata.uid,PodIP:.status.podIP,Node:.spec.nodeName"

$CMD | grep $SERVICE | while read -r POD_INFO; do
  POD_IP=$(echo $POD_INFO | awk '{print $3}')
  POD_NODE=$(echo $POD_INFO | awk '{print $4}' | cut -d'.' -f1)

  # Check if: (i) the pod is of the correct service, (ii) the pod is on the current node.
  if [[ ! $POD_IPS =~ $POD_IP ]] || [[ $NODE != $POD_NODE ]]; then
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
    echo "$POD_IP was found in $POD_IPS but no cgroup found for $SERVICE on $NODE ..."
    continue
  fi

  # Change the CPU allocation for the pod.
  CPU_MAX=$(cat $CGROUP_PATH/$POD_CGROUP/cpu.max)
  CPU_PERIOD=$(echo $CPU_MAX | awk '{print $2}')

  # echo "Changing CPU allocation for $SERVICE to $CPU_ALLOC ..."
  echo "$CPU_ALLOC $CPU_PERIOD" | sudo tee $CGROUP_PATH/$POD_CGROUP/cpu.max >/dev/null

done
