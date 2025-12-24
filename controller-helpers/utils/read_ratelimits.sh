#!/bin/bash
# Read the rate limits for the given API and print them.

showHelp() {
cat << EOF
Usage: <script_name> [-a]
Read rate limit for a particular API.

-h, -help,      --help        Display help
-a, -api,       --api         API name

EOF
}

API_NAME=""

options=$(getopt -l "help,api:" -o "ha:" -a -- "$@")
eval set -- "$options"

while true; do
    case "$1" in
    -h|--help)
            showHelp
            exit 0
            ;;
    -a|--api)
            shift
            API_NAME=$1
            ;;
    --)
            shift
            break;;
    esac
    shift
done

# Check if API name is provided
if [[ -z $API_NAME ]]; then
    echo "API name is required."
    exit 1
fi

# If TESTBED is not set, set it to $HOME
: "${TESTBED:=$HOME}"

PROXY_DIR="$TESTBED/controller-helpers/proxy/limits"

if [[ ! -f ${PROXY_DIR}/${API_NAME} ]]; then
    echo "No rate limit set for API: $API_NAME"
    exit 1
fi

cat ${PROXY_DIR}/${API_NAME}