#!/usr/bin/env bash
# NOTE: run with source
# NOTE: the controller's ssh key needs to be added to CloudLab

if [[ $# != 3 ]]; then
    echo "Usage: $0 <cloudlab_username> <cloudlab_experiment_name> <app>"
    exit 1
fi

export CLOUDLAB_USERNAME=$1
export CLOUDLAB_EXPERIMENT=$2
export CLOUDLAB_PROJECT=wisr-PG0
export CLOUDLAB_CLUSTER=utah.cloudlab.us

APP=$3

if [[ $APP != "social" && $APP != "reservation" ]]; then
    echo "Unrecognized application (reservation/social)"
    exit 1
fi

./cloudlab/config.sh $CLOUDLAB_EXPERIMENT 0 3 0 && ./cloudlab/client_config.sh $CLOUDLAB_EXPERIMENT 4
sleep 4m

# pushd scripts/deployment/production
# wget traces.tar.gz
# tar -xf traces.tar.gz
# popd

./cloudlab/ci.sh $CLOUDLAB_EXPERIMENT 0 4
sleep 30

ssh $CLOUDLAB_USERNAME@node0.$CLOUDLAB_EXPERIMENT.wisr-PG0.utah.cloudlab.us "cd scripts/deployment/$APP; ./start.sh"
sleep 180


./cloudlab/set_cpu_freqs.sh $CLOUDLAB_EXPERIMENT 0 3