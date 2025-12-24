if [[ $# != 3 ]]; then
    echo "Usage: $0 <cloudlab_username> <cloudlab_experiment_name> <app>"
    exit 1
fi

export CLOUDLAB_USERNAME=$1
export CLOUDLAB_EXPERIMENT=$2
export CLOUDLAB_PROJECT=wisr-PG0
export CLOUDLAB_CLUSTER=utah.cloudlab.us