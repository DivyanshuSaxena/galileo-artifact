#!/usr/bin/env bash
# Note: Expects the cloudlab environment variables are set.

if [[ $# != 1 ]]; then
    echo "Usage: $0 <app>"
    exit 1
fi

APP=$1

if [[ $APP != "social" && $APP != "reservation" ]]; then
    echo "Unrecognized application: choose one of reservation/social"
    exit 1
fi

./cloudlab/config.sh $CLOUDLAB_EXPERIMENT 0 3 0 && ./cloudlab/client_config.sh $CLOUDLAB_EXPERIMENT 4
sleep 4m

./cloudlab/ci.sh $CLOUDLAB_EXPERIMENT 0 4
sleep 30

ssh $CLOUDLAB_USERNAME@node0.$CLOUDLAB_EXPERIMENT.$CLOUDLAB_PROJECT.$CLOUDLAB_CLUSTER "cd scripts/deployment/$APP; ./start.sh"
sleep 180

./cloudlab/set_cpu_freqs.sh $CLOUDLAB_EXPERIMENT 0 3