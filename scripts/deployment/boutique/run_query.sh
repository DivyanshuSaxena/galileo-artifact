#!/usr/bin/env bash
# Run query for the Boutique benchmark
# Arguments:
# --init: whether first time install
# --stats: whether to start the stats server
# --client: whether to start the stats client
# --ip: IP address of the stats server
# --port: port of the stats server

showHelp() {
cat << EOF  
Usage: <script_name> [-isc] [-I <ip>] [-r <rate>]
Run query for the Online Boutique benchmark

-h, -help,      --help        Display help
-i, -init,      --init        Whether first time install
-s, -stats,     --stats       Whether to collect CPU-memory stats from the nodes
-c, -client,    --client      Whether to start the stats client
-I, -ip,        --ip          IP address of the stats server
-p, -port,      --port        Port of the application
-r, -rate,      --rate        Rate of requests per second

EOF
}

INIT=0
STATS=0
CLIENT=0
IP=""
RATE=500
PORT=32000

options=$(getopt -l "help,init,stats,client,ip:,port:,rate:" -o "hiscI:p:r:" -a -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -h|--help) 
      showHelp
      exit 0
      ;;
  -i|--init)
      INIT=1
      ;;
  -c|--client)
      CLIENT=1
      ;;
  -s|--stats)
      STATS=1
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
  --)
      shift
      break;;
  esac
  shift
done

: "${TESTBED:=$HOME}"

if [[ $INIT -eq 1 ]]; then
  # Init
  pushd $TESTBED/scripts
  kubectl apply -f deployment/boutique/kubernetes-manifests.yaml
  popd

  # Wait for the pods to get running
  sleep 1m
fi

if [[ $STATS -eq 1 ]]; then
  # Start the stats server
  echo "Starting the stats server with IP=$IP"
  sudo python3 $TESTBED/scripts/utils/stats_server.py $IP > $TESTBED/logs/python.log 2>&1 &
  wait
fi

if [[ $CLIENT -eq 1 ]]; then
  GATEWAY_URL="$IP:$PORT"
  if [[ $STATS -eq 1 ]]; then
    INGRESS_HOST=$(kubectl get svc frontend -o jsonpath='{.spec.clusterIP}')
    INGRESS_PORT=$(kubectl get svc frontend -o jsonpath='{.spec.ports[?(@.protocol=="TCP")].port}')

    GATEWAY_URL=$INGRESS_HOST:$INGRESS_PORT
  fi

  echo "Starting the test with GATEWAY_URL=$GATEWAY_URL"

  # Run queries to log timings
  TIMEFORMAT=%R
  
  # Warm-up
  for i in $(seq 1 20); do
    { time curl -s -o /dev/null -w "%{http_code}" "http://$GATEWAY_URL"; } 2>&1
  done

  # Start the stats client
  if [[ $STATS -eq 1 ]]; then
    sudo python3 $TESTBED/scripts/utils/stats_client.py $TESTBED/scripts/utils/config boutique > $TESTBED/logs/python.log 2>&1 &
  fi
  
  sleep 30

  # Run queries to log timings
  pushd $TESTBED/DeathStarBench/wrk2
  ../wrk2/wrk -D exp -t 20 -c 20 -d 60000 -L http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_boutique_${RATE}.run 2>&1
  popd

  if [[ $STATS -eq 1 ]]; then
    # Kill CPU and Memory measurement
    pid=$(pgrep -f stats_client)
    sudo kill -SIGINT $pid
  fi
fi