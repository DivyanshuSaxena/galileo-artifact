#!/bin/bash
# Add nodes to the social graph

pushd $HOME/DeathStarBench/socialNetwork
python3 scripts/init_social_graph.py --graph=socfb-Reed98 --port=32000

# Warm-up workload - Add posts now! Query them later.
../wrk2/wrk -D exp -t 10 -c 10 -d 120 -L -s ./wrk2/scripts/social-network/compose-post.lua http://localhost:32000/wrk2-api/post/compose -R 200

# Read users workload
../wrk2/wrk -D exp -t 10 -c 10 -d 30 -L -s ./wrk2/scripts/social-network/read-user-timeline.lua http://localhost:32000/wrk2-api/user-timeline/read -R 20
popd
