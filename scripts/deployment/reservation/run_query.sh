#!/usr/bin/env bash
# Run query for the Hotel Reservation benchmark

showHelp() {
cat << EOF  
Usage: <script_name> [-lj] [-I <ip>] [-p <port>] [-r <rate>] [-t <type>] [-D <dist>]
Run query for the Hotel Reservation benchmark

-h, -help,      --help        Display help
-l, -log,       --log         Whether to log the output
-I, -ip,        --ip          IP address of the stats server
-p, -port,      --port        Port of the application
-r, -rate,      --rate        Rate of requests per second
-t, -type,      --type        Type of the workload (search/user/reserve/mixed)
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

options=$(getopt -l "help,jaeger,log,type:,ip:,port:,rate:,dist:" -o "hljt:I:p:r:D:" -a -- "$@")

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
pushd DeathStarBench/hotelReservation
../wrk2/wrk -D exp -t 5 -c 5 -d 20 -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R 10

sleep 10

# Run queries to log timings
if [[ $LOG -eq 1 ]]; then
  echo "Logging the output to $TESTBED/out" 
  if [[ $TYPE == "search" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/search-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_search_${RATE}.run 2>&1
  elif [[ $TYPE == "user" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/user-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_user_${RATE}.run 2>&1
  elif [[ $TYPE == "reserve" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/reserve-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_reserve_${RATE}.run 2>&1
  elif [[ $TYPE == "recommend" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/recommend-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_recommend_${RATE}.run 2>&1
  else
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_reservation_${RATE}.run 2>&1
  fi
else
  if [[ $TYPE == "search" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/search-workload.lua http://$GATEWAY_URL -R $RATE
  elif [[ $TYPE == "user" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/user-workload.lua http://$GATEWAY_URL -R $RATE
  elif [[ $TYPE == "reserve" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/reserve-workload.lua http://$GATEWAY_URL -R $RATE
  elif [[ $TYPE == "recommend" ]]; then
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/recommend-workload.lua http://$GATEWAY_URL -R $RATE
  else
    ../wrk2/wrk -D ${DIST} -t 10 -c 10 -d ${PERIOD} -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R $RATE
  fi
fi

popd
