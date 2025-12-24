#!/usr/bin/env bash
# Start the Hotel Reservation benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

# Pull docker image
docker pull divyanshus/hotelreservation

if [ ! -d "$TESTBED/DeathStarBench" ]; then
  sudo apt install -y luarocks
  sudo luarocks install luasocket

  git clone https://github.com/DivyanshuSaxena/DeathStarBench.git

  # Make wrk2 executable
  pushd DeathStarBench
  git checkout galileo
  popd
fi

pushd DeathStarBench/hotelReservation
kubectl apply -Rf kubernetes/
popd

# Wait for the pods to get running
sleep 1m

popd
