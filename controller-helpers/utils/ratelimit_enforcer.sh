#!/bin/bash
# Enforce the rate limit for a particular request type.

showHelp() {
cat << EOF
Usage: <script_name> [-a] [-r]
Enforce rate limit for a particular API.

-h, -help,      --help        Display help
-a, -api,       --api         API name
-r, -rate,      --rate        Rate limit (requests per second)

EOF
}

API_NAME=""
RATE_LIMIT=""

options=$(getopt -l "help,api:,rate:" -o "ha:r:" -a -- "$@")
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
	-r|--rate)
			shift
			RATE_LIMIT=$1
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

# Check if rate limit is provided
if [[ -z $RATE_LIMIT ]]; then
	echo "Rate limit is required."
	exit 1
fi

# If TESTBED is not set, set it to $HOME
: "${TESTBED:=$HOME}"

PROXY_DIR="$TESTBED/controller-helpers/proxy/limits"

echo ${RATE_LIMIT} > ${PROXY_DIR}/${API_NAME}