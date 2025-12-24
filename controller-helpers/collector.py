"""
Invoke the autothrottle controller.
Args:
    logs_path (str): The path to the logs directory.
"""

import os
import sys
import grpc
import time
import argparse

# Include the controller-helpers directory in the path.
from pathlib import Path
helpers_path = Path(__file__).parent
sys.path.append(str(helpers_path.resolve()))

from protos import collector_pb2
from protos import collector_pb2_grpc

parser = argparse.ArgumentParser()
parser.add_argument("--logs_dir", type=str, required=True)
parser.add_argument("--app", type=str, required=True)
parser.add_argument("--workload", type=str, required=True)
parser.add_argument("--workload_ip", type=str, default="10.10.1.5")

args = parser.parse_args()
logs_path = args.logs_dir
app = args.app
workload = args.workload
workload_ip = args.workload_ip

log_file = os.path.join(
    logs_path, f"motivation-{workload}-{time.strftime('%m%d-%H%M')}.log"
)

if app == "reservation":
    request_types = ["user", "recommend", "search", "reserve"]
elif app == "social":
    request_types = ["compose_post", "read_home_timeline", "read_user_timeline"]

num_types = len(request_types)
start_time = time.time()

logs = []
num_iterations = 0
curr_time = time.time()
last_query_time = curr_time

total_requests = [0] * num_types
total_violations = [0] * num_types

# Make a gRPC stub to collect the latencies.
channel = grpc.insecure_channel(workload_ip + ":50051")
stub = collector_pb2_grpc.LatencyCollectorStub(channel)

# Run for an hour (since the workload is for an hour).
while curr_time - start_time < 3600:
    # Get the per-request-type latency stats from locust -- using the gRPC client.
    curr_time = time.time()
    period = 30
    sleep_time = period - (curr_time - last_query_time)
    if sleep_time > 0:
        print(f"Sleeping for {sleep_time} seconds.")
        time.sleep(sleep_time)

    print(f"Querying latency stats for period {period} seconds.")
    latency_request = collector_pb2.LatencyRequest()
    latency_request.period = period
    latency_request.start_time = int(last_query_time)
    last_query_time = time.time()

    # Query only the statistics - used by the metric collector, when all latencies are not needed.
    response = stub.GetLatencyStats(latency_request)

    # Construct the stats to report
    latencies = [0] * num_types
    workload = [0] * num_types

    for data in response.data:
        index = request_types.index(data.type)
        latencies[index] = data.p99
        workload[index] = data.total_rps
        total_requests[index] += data.total_rps * period
        total_violations[index] += data.num_violations        

    violation_fraction = [total_violations[i] / total_requests[i] if total_requests[i] else 0 for i in range(num_types)]
    print(
        f"Timestamp: {curr_time}, Workload: {workload}, Latencies: {latencies}, Violations: {violation_fraction}", flush=True
    )
    logs.append((curr_time, workload, latencies, violation_fraction))

    # Write to logs_path every 1 minute.
    print("<=======================================>")
    print("Writing logs to file.")
    with open(log_file, "a") as f:
        for log in logs:
            f.write(f"{log[0]}, {log[1]}, {log[2]}, {log[3]}\n")
            f.flush()
    logs = []

    num_iterations += 1
    if num_iterations % 10 == 0:
        print(f"Iteration {num_iterations}, Time: {curr_time - start_time}")

print("Complete")
