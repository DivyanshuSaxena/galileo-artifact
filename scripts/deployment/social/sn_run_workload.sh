#!/bin/bash
# Run a workload on the social graph

pushd $HOME/scripts/deployment/socialNetwork

# # Read home timeline workload
# ../wrk2/wrk -D exp -t 10 -c 10 -d 30 -L -s ./wrk2/scripts/social-network/read-home-timeline.lua http://localhost:8080/wrk2-api/home-timeline/read -R 500

# # Read users workload
# ../wrk2/wrk -D exp -t 10 -c 10 -d 30 -L -s ./wrk2/scripts/social-network/read-user-timeline.lua http://localhost:8080/wrk2-api/user-timeline/read -R 500

# Compose Post workload
../wrk2/wrk -D exp -t 10 -c 10 -d 60 -L -s ./wrk2/scripts/social-network/compose-post.lua http://localhost:8080/wrk2-api/post/compose -R 400

popd
