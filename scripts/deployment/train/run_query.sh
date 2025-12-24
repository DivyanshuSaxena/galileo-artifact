#!/usr/bin/env bash
# Run query for the Train Ticket benchmark

showHelp() {
cat << EOF  
Usage: <script_name> [-l] [-I <ip>] [-p <port>] [-r <rate>] [-D <dist>]
Run query for the Train Ticket benchmark

-h, -help,      --help        Display help
-l, -log,       --log         Whether to log the output
-I, -ip,        --ip          IP address of the stats server
-p, -port,      --port        Port of the application
-r, -rate,      --rate        Rate of requests per second
-D, -dist,      --dist        Distribution of the workload (exp/norm/zipf)

EOF
}

LOG=0
IP=""
RATE=2000
PORT=32000
PERIOD=60
DIST="exp"

options=$(getopt -l "help,log,ip:,port:,rate:,dist:" -o "hlI:p:r:D:" -a -- "$@")

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

# Run queries to log timings
pushd client

# Make rps.txt with rate 100 repeated on $PERIOD lines.
echo "$RATE" > rps.txt
for ((i=1; i<$PERIOD; i++)); do
  echo "$RATE" >> rps.txt
done

if [[ $LOG -eq 1 ]]; then
  echo "Logging the output to $TESTBED/out"
  locust -f locust_train.py --headless -u 10 -r 10 -H http://$GATEWAY_URL --run-time ${PERIOD}s --logfile $TESTBED/out/train_ticket.log
else
  locust -f locust_train.py --headless -u 10 -r 10 -H http://$GATEWAY_URL --run-time ${PERIOD}s
fi
popd

popd
