#!/usr/bin/env bash
# Run all profile experiments for different rate and workload combinations.
# Arguments:
# 1: Name of the experiment
# 2: Application to profile (social/reservation)
# 3: Directory to put the output files
# 4: Distribution to use for the workload (zipf/exp/norm)
# 5: if stress (stress/nostress) - Optional

# Check arguments
if [ $# -lt 4 ]; then
  echo "Usage: <script_name> <appl_name> <experiment_name> <output_dir> <dist> <if_stress>"
  exit 1
fi

APPL=$2
IF_STRESS=${5:-""}

# Is APPL is social, then set a particular WORKLOAD and RATES, else set another WORKLOAD and RATES
if [ "$APPL" == "social" ]; then
  WORKLOADS=("compose_home_user" "compose" "home" "user" "compose_home" "home_user" "user_compose")
  RATES=(200 300 500 600 700 800 1000)
elif [ "$APPL" == "reservation" ]; then
  WORKLOADS=("user_search_reserve_recommend" "search" "user" "reserve" "recommend" "search_user" "user_reserve" "search_recommend")
  RATES=(200 300 500 600 700 800)
fi

# Start the experiments.
for WORKLOAD in "${WORKLOADS[@]}"; do
  for RATE in "${RATES[@]}"; do
    # If RATE is less than 500, set samples to 500 else 1000
    if [ $RATE -lt 500 ]; then
      SAMPLES=500
    else
      SAMPLES=1000
    fi
    ./cloudlab/profiles/${APPL}_profiles.sh $1 $RATE $SAMPLES $WORKLOAD $WORKLOAD $4 $3 ${IF_STRESS}
    sleep 2m
  done
done