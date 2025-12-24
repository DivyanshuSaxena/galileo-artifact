#!/usr/bin/env bash
# Arguments:
# 1: Name of the experiment
# 2: Start node of experiment
# 3: End node of experiment
# 4: -a/--all to denote that all nodes have to be used

NUM_NODE=$3
NODE_PREFIX="node"
EXP_NAME=$1
PROJECT_EXT=${CLOUDLAB_PROJECT}
DOMAIN=${CLOUDLAB_CLUSTER}
USER_NAME=${CLOUDLAB_USERNAME}
VM_PORT=${CLOUDLAB_VM_PORT}
VM_NODE=${CLOUDLAB_VM_NODE}

i=$2
while [ $i -le $NUM_NODE ]; do
  skip=0
  if [ "$4" != "-a" ] && [ "$4" != "--all" ]; then
    for node in $SKIP_NODES; do
      if [ "$i" -eq "$node" ]; then
        skip=1
        break
      fi
    done
  fi

  # If VM_PORT is set, then add $i to the port
  if [ -n "$VM_PORT" ]; then
    # Add $i to the port number.
    PORT=$((VM_PORT + i))
    echo "-p $PORT $USER_NAME@$VM_NODE.$DOMAIN"
  else
    echo "$USER_NAME@$NODE_PREFIX$i.$EXP_NAME.$PROJECT_EXT.$DOMAIN"
  fi

  let i=$i+1
done
