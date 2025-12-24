#!/usr/bin/env bash
# Query jaeger for all services one by one.
# Arguments:
# --rate: Rate of requests per second
# --samples: Number of samples to collect

showHelp() {
cat << EOF
Usage: <script_name> [-r <rate>] [-s <samples>]
Query jaeger for all services one by one.

-h, --help        Display help
-r, --rate        Rate of requests per second
-s, --samples     Number of samples to collect

EOF
}

RATE=2000
SAMPLES=100

options=$(getopt -l "rate:,samples:,help" -o "r:s:h" -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -r|--rate)
      shift
      RATE=$1
      ;;
  -s|--samples)
      shift
      SAMPLES=$1
      ;;
  --)
      shift
      break
      ;;
  esac
  shift
done

: "${TESTBED:=$HOME}"
pushd $TESTBED

# Get jaeger ip address
JAEGER_IP=$(kubectl get svc jaeger -o jsonpath='{.spec.clusterIP}')

pushd collector
echo "python query_jaeger.py ${JAEGER_IP} ${RATE} ${SAMPLES}"
python query_jaeger.py ${JAEGER_IP} ${RATE} ${SAMPLES}
popd

popd