#!/usr/bin/env bash
# Start the Social Network benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

if [ ! -d "$TESTBED/DeathStarBench" ]; then
  sudo apt install -y luarocks
  sudo luarocks install luasocket

  git clone https://github.com/DivyanshuSaxena/DeathStarBench.git

  pushd DeathStarBench
  git checkout galileo
  popd
fi

pushd DeathStarBench/socialNetwork/
kubectl apply -f kubernetes/all.yaml

# Wait for the pods to get running
sleep 1m

# Initialize the social network
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --port=32000 --ip=10.10.1.1
popd
