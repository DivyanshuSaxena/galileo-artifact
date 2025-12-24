#!/usr/bin/env bash
# Teardown the Social Network benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

helm uninstall train-ticket -n train-ticket

# Wait for the pods to be terminated
sleep 1m

popd
