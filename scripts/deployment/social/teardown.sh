#!/usr/bin/env bash
# Teardown the Social Network benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

pushd DeathStarBench/socialNetwork/
kubectl delete -f kubernetes/all.yaml

# Wait for the pods to be terminated
sleep 1m

popd
