#!/usr/bin/env bash
# Teardown the Hotel Reservation benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

pushd DeathStarBench/hotelReservation
kubectl delete -Rf kubernetes/
popd

# Wait for the pods to be terminated
sleep 30s

popd
