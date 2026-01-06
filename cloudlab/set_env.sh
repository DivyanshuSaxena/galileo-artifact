#!/usr/bin/env bash
# Note: Expects three arguments:
# 1: cloudlab username
# 2: cloudlab experiment name
# 3: cloudlab project name
#
# IMPORTANT: This script must be sourced, not executed!
# Usage: source ./cloudlab/set_env.sh <username> <experiment> <project>
#    or: . ./cloudlab/set_env.sh <username> <experiment> <project>

# Check if script is being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "ERROR: This script must be sourced to set environment variables in your current shell."
    echo "Usage: source $0 <cloudlab_username> <cloudlab_experiment_name> <cloudlab_project_name>"
    echo "   or: . $0 <cloudlab_username> <cloudlab_experiment_name> <cloudlab_project_name>"
    exit 1
fi

if [[ $# != 3 ]]; then
    echo "Usage: source $0 <cloudlab_username> <cloudlab_experiment_name> <cloudlab_project_name>"
    return 1
fi

export CLOUDLAB_USERNAME=$1
export CLOUDLAB_EXPERIMENT=$2
export CLOUDLAB_PROJECT=$3-PG0
export CLOUDLAB_CLUSTER=utah.cloudlab.us

echo "Environment variables set:"
echo "  CLOUDLAB_USERNAME=$CLOUDLAB_USERNAME"
echo "  CLOUDLAB_EXPERIMENT=$CLOUDLAB_EXPERIMENT"
echo "  CLOUDLAB_PROJECT=$CLOUDLAB_PROJECT"
echo "  CLOUDLAB_CLUSTER=$CLOUDLAB_CLUSTER"