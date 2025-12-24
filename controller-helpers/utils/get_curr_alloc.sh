#!/bin/bash
# Get the current CPU allocations for the given service.
# Meant to be run from the control node.

showHelp() {
cat << EOF
Usage: <script_name> [-s]
Get current CPU allocations for the given service.

-h, -help,      --help        Display help
-s, -service,   --service     Service name

EOF
}

SERVICE=""

options=$(getopt -l "help,service:" -o "hs:" -a -- "$@")

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

# Get the nodes on which the service pods are running.
NODES=$(kubectl get pods -o custom-columns=PodName:.metadata.name,Node:.spec.nodeName | grep $SERVICE | awk '{print $2}' | sort | uniq)

# Iterate through the nodes and change the CPU allocation for the pods.
for NODE in $NODES; do
  # Run the curr_alloc_helper.sh script on the node.
  if [[ $NODE == *"node0"* ]]; then
    pushd $HOME/controller-helpers/utils > /dev/null
    ./curr_alloc_helper.sh $SERVICE 1
    popd > /dev/null
  else
    ssh -o StrictHostKeyChecking=no $NODE "cd \$HOME/controller-helpers/utils; ./curr_alloc_helper.sh $SERVICE 0" &
  fi
done
wait