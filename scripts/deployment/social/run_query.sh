#!/usr/bin/env bash
# Run query for the Social Network benchmark

showHelp() {
cat << EOF  
Usage: <script_name> [-lj] [-I <ip>] [-p <port>] [-r <rate>] [-t <type>] [-D <dist>]

Run query for the Social Network benchmark

-h, -help,      --help        Display help
-l, -log,       --log         Whether to log the output
-I, -ip,        --ip          IP address of the stats server
-p, -port,      --port        Port of the application
-r, -rate,      --rate        Rate of requests per second
-t, -type,      --type        Type of the workload (compose/home/user/mixed)
-j, -jaeger,    --jaeger      Workload should be long running for jaeger queries
-D, -dist,      --dist        Distribution of the workload (exp/norm/zipf)

EOF
}

LOG=0
IP=""
TYPE="mixed"
RATE=2000
PORT=32000
PERIOD=60
DIST="exp"

options=$(getopt -l "help,log,jaeger,ip:,port:,type:,dist:" -o "hljI:r:p:D:" -a -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -h|--help) 
      showHelp
      exit 0
      ;;
  -l|--log)
      LOG=1
      ;;
  -I|--ip)
      shift
      IP=$1
      ;;
  -p|--port)
      shift
      PORT=$1
      ;;
  -r|--rate)
      shift
      RATE=$1
      ;;
  -t|--type)
      shift
      TYPE=$1
      ;;
  -j|--jaeger)
      PERIOD=60000
      ;;
  -D|--dist)
      shift
      DIST=$1
      ;;
  --)
      shift
      break;;
  esac
  shift
done

: "${TESTBED:=$HOME}"
pushd $TESTBED

GATEWAY_URL="$IP:$PORT"
echo "Starting the test with GATEWAY_URL=$GATEWAY_URL"

# Warm-up
pushd DeathStarBench/socialNetwork
../wrk2/wrk -D exp -t 5 -c 5 -d 10 -L -s ./wrk2/scripts/social-network/compose-post.lua http://$GATEWAY_URL/wrk2-api/post/compose -R 10

sleep 30

# Run queries to log timings
if [[ $LOG -eq 1 ]]; then
  echo "Logging the output to $TESTBED/out" 
  if [[ $TYPE == "compose" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/compose-post.lua http://$GATEWAY_URL/wrk2-api/post/compose -R $RATE >> $TESTBED/out/time_soc_compose_${RATE}.run 2>&1
  elif [[ $TYPE == "home" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/read-home-timeline.lua http://$GATEWAY_URL/wrk2-api/home-timeline/read -R $RATE >> $TESTBED/out/time_soc_home_${RATE}.run 2>&1
  elif [[ $TYPE == "user" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/read-user-timeline.lua http://$GATEWAY_URL/wrk2-api/user-timeline/read -R $RATE >> $TESTBED/out/time_soc_user_${RATE}.run 2>&1
  else
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/mixed-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_social_${RATE}.run 2>&1
  fi
else
  if [[ $TYPE == "compose" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/compose-post.lua http://$GATEWAY_URL/wrk2-api/post/compose -R $RATE
  elif [[ $TYPE == "home" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/read-home-timeline.lua http://$GATEWAY_URL/wrk2-api/home-timeline/read -R $RATE
  elif [[ $TYPE == "user" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/read-user-timeline.lua http://$GATEWAY_URL/wrk2-api/user-timeline/read -R $RATE
  else
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/social-network/mixed-workload.lua http://$GATEWAY_URL -R $RATE
  fi
fi

popd