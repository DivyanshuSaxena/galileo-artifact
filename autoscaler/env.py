"""
Implementation for a gym environment for the autothrottle controller.
"""

import gym
import sys
import grpc
import time
import threading
import google.protobuf.empty_pb2

from pathlib import Path
from autothrottle import CaptainScaler, invoke_scaler

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import common_utils
from protos import collector_pb2_grpc

# Include jaeger collector in the path.
jaeger_collector_path = Path(__file__).parent / ".." / "jaeger-collector"
sys.path.append(str(jaeger_collector_path.resolve()))

import query_jaeger


class AutothrottleEnv(gym.Env):

    def __init__(
        self,
        period,
        use_samples,
        workload_ip,
        services,
        request_types,
        frontend_service,
    ):
        super(AutothrottleEnv, self).__init__()

        self.services = services
        self.request_types = request_types
        self.frontend = frontend_service
        self.period = period
        self.use_samples = use_samples

        # Get the Jaeger IP address.
        self.jaeger_ip = common_utils.get_jaeger_ip()
        if self.jaeger_ip == "localhost":
            print("[ERROR] Jaeger IP not found.")

        # Initialize the gRPC client to collect latency from the locust workload executor.
        if not use_samples:
            channel = grpc.insecure_channel(f"{workload_ip}:50051")
            self.stub = collector_pb2_grpc.LatencyCollectorStub(channel)
            self.last_query_time = time.time()

        # Invoke separate scalers for each service.
        self.scaler_threads = []
        self.scalers = {}
        self.completion_event = threading.Event()
        for service in self.services:
            scaler = CaptainScaler(service, 0.1)
            self.scalers[service] = scaler

            thread = threading.Thread(
                target=invoke_scaler,
                args=(
                    service,
                    scaler,
                    self.completion_event,
                ),
            )
            self.scaler_threads.append(thread)
            thread.start()

    def step(self, throttle_targets):
        """
        The step function takes in the throttle targets for the services and changes the resources accordingly.
        Args:
            throttle_targets (dict): The throttle targets for the services.
        """
        # Iterate over all services in the graph and change their resources.
        for service in self.services:
            if service not in throttle_targets:
                continue

            # Get the throttle target for the service and set in the respective scaler.
            target = throttle_targets[service]
            self.scalers[service].update(target)

        type_latencies = []
        for _ in range(len(self.request_types["by_type"])):
            type_latencies.append([])

        # Check whether to get sampled latencies from jaeger or all latencies from the client.
        if self.use_samples:
            # Get the per-request-type latency -- sleeps for the period.
            type_latencies = query_jaeger.get_latencies_by_type(
                self.period,
                self.jaeger_ip,
                self.frontend,
                self.request_types["by_service"],
            )
        else:
            # Sleep for the period.
            sleep_period = self.period - (time.time() - self.last_query_time)
            if sleep_period > 0:
                print(f"Sleeping for {sleep_period} seconds.")
                time.sleep(sleep_period)
            else:
                print("Sending request to collector.")

            # Get the per-request-type latency from the client -- using the gRPC client.
            latency_data = common_utils.get_current_latencies(self.stub, self.period)

            num_latencies = 0
            for req_type, latencies in latency_data.items():
                index = self.request_types["by_type"].index(req_type)
                type_latencies[index] = latencies
                num_latencies += len(latencies)
            print(f"Received {num_latencies} latencies.")

            self.last_query_time = time.time()

        # Get the current allocations for each service.
        allocations = {}
        for service in self.services:
            limit = self.scalers[service].limit
            allocations[service] = limit

        return allocations, type_latencies, False, False, {}

    def reset(self):
        # Set the CPU levels to the maximum.
        for service in self.services:
            common_utils.change_resource_allocation(service, 800000)

        allocations = {}
        for service in self.services:
            allocations[service] = 1

        # Sleep for a "settling period" before returning.
        time.sleep(self.period)

        # Return RPS 0 and allocation 1 for the initial state.
        return (0, 1), None

    def render(self, mode="human"):
        pass

    def close(self):
        # Stop all the threads and force close them.
        self.completion_event.set()

        for thread in self.scaler_threads:
            thread.join()

        # Send the EndCollector rpc to the gRPC server.
        if not self.use_samples:
            self.stub.EndCollector(google.protobuf.empty_pb2.Empty())
