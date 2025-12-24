"""
Execute the locust workload.
Args:
    temp_dir (Path): Temporary directory.
    locustfile (str): Path to the locustfile.
    url (str): URL of the target system.
    workers (int): Number of workers.
"""

import os
import sys
import grpc
import json
import time
import socket
import threading
import subprocess
import numpy as np
import google.protobuf.empty_pb2

from concurrent import futures

from protos import collector_pb2
from protos import collector_pb2_grpc


class LatencyCollectorServicer(collector_pb2_grpc.LatencyCollectorServicer):

    def __init__(self, logfile, completion_event):
        self.logfile = logfile
        self.completion_event = completion_event

        # Store all request latencies in a cache and remove entries that are more than max_query_period old.
        self.request_cache = []
        self.max_query_period = 120
        self.cache_lock = threading.Lock()

        # Start the socket listener thread
        self.socket_thread = threading.Thread(target=self.listen_unix_socket, daemon=True)
        self.socket_thread.start()

        # Start the cache eviction thread
        self.eviction_thread = threading.Thread(target=self.evict_cache_periodically, daemon=True)
        self.eviction_thread.start()

    def listen_unix_socket(self):
        sock_path = "/tmp/locust_log.sock"
        if os.path.exists(sock_path):
            os.remove(sock_path)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(100)  # allow backlog of 100
        server.settimeout(1.0)

        def handle_connection(conn):
            buffer = b""
            with conn:
                while not self.completion_event.is_set():
                    try:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        while b"\n" in buffer:
                            line, buffer = buffer.split(b"\n", 1)
                            if line:
                                try:
                                    entry = json.loads(line.decode())
                                    with self.cache_lock:
                                        self.request_cache.append(entry)
                                except Exception as e:
                                    print(f"Error parsing socket data: {e}")
                    except Exception as e:
                        print(f"Socket recv error: {e}")
                        break

        while not self.completion_event.is_set():
            try:
                conn, _ = server.accept()
                threading.Thread(target=handle_connection, args=(conn,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Socket error: {e}")
                break

        server.close()
        if os.path.exists(sock_path):
            os.remove(sock_path)

    def evict_cache_periodically(self):
        while not self.completion_event.is_set():
            time.sleep(5)
            curr_time = time.time()
            with self.cache_lock:
                self.request_cache = [
                    e for e in self.request_cache
                    if curr_time - e["time"] < self.max_query_period
                ]

    def read_request_log(self, start_time, period=60, max_wait=10, poll_interval=0.2):
        """
        Reads request entries from the cache, waiting for new entries if needed.
        Returns as soon as all required entries are found or max_wait is exceeded.
        """
        latency_data = {}
        num_added = 0
        found_all = False
        first_added = None
        last_added = None

        # Set a deadline to avoid waiting indefinitely for new entries.
        deadline = time.time() + max_wait

        # Track the last processed index in the cache
        # Needed if not all entries are found in the first read.
        last_index = 0
        while not found_all and time.time() < deadline:
            # Make a copy of the cache to minimize lock holding time.
            with self.cache_lock:
                cache_copy = list(self.request_cache)

            # Only process new entries since last_index.
            for i in range(last_index, len(cache_copy)):
                entry = cache_copy[i]
                if entry["time"] >= start_time:
                    request_type = entry["context"]["type"]
                    if request_type not in latency_data:
                        latency_data[request_type] = {
                            "latencies": [],
                            "num_fails": 0,
                            "total": 0
                        }

                    latency = entry["latency"]
                    is_failed = entry["failed"]
                    if is_failed == "True":
                        latency_data[request_type]["num_fails"] += 1
                    else:
                        latency_data[request_type]["latencies"].append(latency)
                    latency_data[request_type]["total"] += 1
                    num_added += 1
                    if first_added is None:
                        first_added = entry["time"]
                    last_added = entry["time"]

                # If we've reached the end of the required period, stop collecting
                if entry["time"] > start_time + period:
                    found_all = True
                    break

            # Update last_index to avoid reprocessing entries
            last_index = len(cache_copy)

            # If not all entries found, wait for more data to arrive
            if not found_all:
                time.sleep(poll_interval)

        # Print debug info
        print(f"Number reads from cache: {num_added}")
        print(f"Time of first added: {first_added}, Time of last added: {last_added}")
        curr_time = time.time()
        print(f"Provided start time: {start_time}, period: {period}, curr_time: {curr_time}, Added: {num_added}")
        return latency_data

    def CollectAllLatencies(self, request, context):
        # Get the period from the request.
        period = request.period
        start_time = request.start_time
        print(f"Received request for start time: {start_time}, period: {period}")

        # Read request.log, construct the AllLatenciesResponse object and return as response.
        num_latencies = 0
        latency_data = self.read_request_log(start_time, period)
        response = collector_pb2.AllLatenciesResponse()
        for type, latency_data in latency_data.items():
            lat_obj = collector_pb2.LatencyData()
            lat_obj.type = type
            lat_obj.latencies.extend(latency_data["latencies"])
            lat_obj.total_rps = latency_data["total"] / period
            lat_obj.failed_rps = latency_data["num_fails"] / period
            response.data.append(lat_obj)

            num_latencies += len(latency_data["latencies"])

        print(f"Responding back with {num_latencies} latencies.")
        return response

    def GetLatencyStats(self, request, context):
        # Get the period from the request.
        period = request.period
        start_time = request.start_time
        print(f"Received request for start time: {start_time}, period: {period}")

        # Read request.log, construct the LatencyStatsResponse object and return as response.
        latency_data = self.read_request_log(start_time, period)
        response = collector_pb2.LatencyStatsResponse()
        for type, latency_data in latency_data.items():
            lat_obj = collector_pb2.LatencyStatsData()
            lat_obj.type = type
            if len(latency_data["latencies"]) == 0:
                lat_obj.p95 = 0
                lat_obj.p99 = 0
            else:
                lat_obj.p95 = float(np.percentile(latency_data["latencies"], 95))
                lat_obj.p99 = float(np.percentile(latency_data["latencies"], 99))
            lat_obj.total_rps = latency_data["total"] / period
            lat_obj.failed_rps = latency_data["num_fails"] / period            
            lat_obj.num_violations = len([lat for lat in latency_data["latencies"] if lat > 100])
            print(f"Type: {type}, failed: {lat_obj.failed_rps}, total: {lat_obj.total_rps}")
            response.data.append(lat_obj)

        return response

    def EndCollector(self, request, context):
        self.completion_event.set()
        return google.protobuf.empty_pb2.Empty()


def serve(logfile):
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # Add a threading event to wait for completion.
    completion_event = threading.Event()
    latency_collector = LatencyCollectorServicer(logfile, completion_event)
    collector_pb2_grpc.add_LatencyCollectorServicer_to_server(
        latency_collector, grpc_server
    )
    grpc_server.add_insecure_port("[::]:50051")
    grpc_server.start()

    completion_event.wait()
    grpc_server.stop(0)


def with_locust(temp_dir, locustfile, url, workers, use_proxy=False):
    if use_proxy:
        args = [
            'locust',
            '--worker',
            '-f', locustfile,
            '--use-proxy=True'
        ]
    else:
        args = [
            'locust',
            '--worker',
            '-f', locustfile,
        ]

    worker_ps = []
    for i in range(workers):
        worker_ps.append(subprocess.Popen(args))

    if use_proxy:
        args = [
            'locust',
            '--master',
            '--expect-workers', f'{workers}',
            '--headless',
            '-H', url,
            '--csv', f'{temp_dir}/locust',
            '--csv-full-history',
            '-f', locustfile,
            '--use-proxy=True'
        ]
    else:
        args = [
            'locust',
            '--master',
            '--expect-workers', f'{workers}',
            '--headless',
            '-f', locustfile,
            '-H', url,
            '--csv', f'{temp_dir}/locust',
            '--csv-full-history',
        ]

    master_p = subprocess.Popen(args)

    time.sleep(1)
    return master_p, worker_ps

if __name__ == '__main__':
    # Check the number of arguments.
    if len(sys.argv) != 10:
        print('Usage: python execute_workload.py <temp_dir> <locustfile> <url> <workers> <multiplier> <rps (fixed_* or path to rps file)> <use_proxy (0/1)> <for_training (0/1)> <start_grpc (0/1)>')
        sys.exit(1)

    # Workload being used by the locustfile.
    locustfile = sys.argv[2]
    workload = locustfile.split('.')[0].split('_')[-1][-1]

    # Check if workload is an integer.
    try:
        workload = int(workload)
        logfile = f"request{workload}.log"
        rpsfile = f"rps{workload}.txt"
    except:
        logfile = f"request.log"
        rpsfile = f"rps.txt"

    # Multiply the rps by the given factor.
    rps = sys.argv[6]
    multiplier = int(sys.argv[5])
    new_file = os.path.join(os.getcwd(), rpsfile)

    # Duration is 1 hour if for eval, 8 hours if for training.
    for_training = int(sys.argv[8]) == 1
    duration = 8 if for_training else 1

    # If the rps is simply "fixed_*", then use a fixed workload.
    if "fixed" in rps:
        # Get the rate from rps - fixed_<rate>
        rate = int(rps.split('_')[1])
        with open(new_file, 'w') as f:
            for _ in range(duration*3600):
                f.write(f"{rate * multiplier}\n")
    else:
        with open(rps, 'r') as f:
            lines = f.readlines()

        new_lines = [str(int(line) * multiplier) for line in lines]

        with open(new_file, 'w') as f:
            for _ in range(duration):
                f.write('\n'.join(new_lines))
                f.write('\n')

    # Start the gRPC server, if flag is 1.
    start_grpc = int(sys.argv[9])
    if start_grpc == 1:
        serve_thread = threading.Thread(target=serve, args=(logfile,))
        serve_thread.start()

    # Remove request.log file -- will be used to read the latencies.
    if os.path.exists(logfile):
        os.remove(logfile)

    # Whether to use proxy
    use_proxy = int(sys.argv[7]) == 1

    # Execute the workload - reads the rps.txt file (new_file variable above).
    p, worker_ps = with_locust(sys.argv[1], locustfile, sys.argv[3], int(sys.argv[4]), use_proxy)
    p.wait()

    for worker_p in worker_ps:
        worker_p.wait()

    serve_thread.join()
