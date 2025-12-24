#!/bin/bash
# Change the CPU allocation for the pod of the given service.

showHelp() {
cat << EOF
Usage: <script_name> [-s] [-a]
Change CPU allocation for the pod of the given service.

-h, -help,      --help        Display help
-s, -service,   --service     Service name
-a, -alloc,     --alloc       CPU allocation

EOF
}

SERVICE=""
CPU_ALLOC=""

options=$(getopt -l "help,service:,alloc:" -o "hs:a:" -a -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -h|--help)
      showHelp
      exit 0
      ;;
  -s|--service)
      shift
      SERVICE=$1
      ;;
  -a|--alloc)
      shift
      CPU_ALLOC=$1
      ;;
  --)
      shift
      break;;
  esac
  shift
done

# Check if service is provided
if [[ -z $SERVICE ]]; then
  echo "Service name is required."
  exit 1
fi

# Check if CPU allocation is provided
if [[ -z $CPU_ALLOC ]]; then
  echo "CPU allocation is required."
  exit 1
fi

# Get the nodes on which the service pods are running.
NODES=$(kubectl get pods -o custom-columns=PodName:.metadata.name,Node:.spec.nodeName | grep $SERVICE | awk '{print $2}' | sort | uniq)

# Iterate through the nodes and change the CPU allocation for the pods.
for NODE in $NODES; do
  # Run the allocation_enforcer.sh script on the node.
  if [[ $NODE == *"node0"* ]]; then
    pushd $HOME/controller-helpers/utils > /dev/null
    ./allocation_enforcer.sh $SERVICE $CPU_ALLOC 1
    popd > /dev/null
  else
    ssh -o StrictHostKeyChecking=no $NODE "cd \$HOME/controller-helpers/utils; ./allocation_enforcer.sh $SERVICE $CPU_ALLOC 0" &
  fi
done
wait