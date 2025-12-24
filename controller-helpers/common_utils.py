"""
Common utility functions that can be used across different modules.
"""

import sys
import time
import pickle
import filelock
import subprocess

# Include the controller-helpers directory in the path.
from pathlib import Path

helpers_path = Path(__file__).parent
sys.path.append(str(helpers_path.resolve()))

from protos import collector_pb2


def get_rate_limit(api):
    """
    Gets the current rate limit for the given API by running the
    read_ratelimits.sh script.

    Args:
        api (str): The name of the API.
    Returns:
        int: The current rate limit (in requests per second).
    """
    script_path = helpers_path / "utils" / "read_ratelimits.sh"
    script_path = str(script_path.resolve())
    try:
        rate = subprocess.check_output([script_path, "--api", api])
        return int(rate.decode("utf-8").strip())
    except subprocess.CalledProcessError:
        print(f"############# Error getting rate limit for {api}")
        return -1


def get_current_alloc(service):
    """
    Gets the current resource allocation for the given service by running the
    get_curr_alloc.sh script.

    Args:
        service (str): The name of the service.
    Returns:
        int: The current resource allocation (in CPU units).
    """
    script_path = helpers_path / "utils" / "get_curr_alloc.sh"
    script_path = str(script_path.resolve())
    try:
        alloc_str = subprocess.check_output([script_path, "--service", service])

        # Allocation string is of the form "CPU: <value>"
        alloc = alloc_str.decode("utf-8").strip().split()[1]  # Get the CPU allocation
        return int(alloc)
    except subprocess.CalledProcessError:
        print(f"############# Error getting current allocation for {service}")
        return -1


def get_service_stats(service):
    """
    Gets the CPU usage statistics by running the get_stats.sh script.

    Args:
        service (str): The name of the service.
    Returns:
        str: The CPU usage statistics as a string.
    """
    script_path = helpers_path / "utils" / "get_stats.sh"
    script_path = str(script_path.resolve())
    try:
        stats = subprocess.check_output([script_path, "--service", service])
        return stats.decode("utf-8").strip()
    except subprocess.CalledProcessError:
        print(f"############# Error getting stats for {service}")
        return ""


def change_rate_limit(api, rate):
    """
    Changes the rate limit for the given API.

    Args:
        api (str): The name of the API.
        rate (int): The new rate limit (in requests per second).
    """
    script_path = helpers_path / "utils" / "ratelimit_enforcer.sh"
    script_path = str(script_path.resolve())
    try:
        subprocess.call([script_path, "--api", api, "--rate", str(rate)])
    except subprocess.CalledProcessError:
        print(f"############# Error changing rate limit for {api}")

    # Need to inform the proxy about a change in the rate limit.
    pid = subprocess.check_output("ps -ef | grep /exe/proxy | grep go-build | awk '{print $2}' | head -1", shell=True)
    subprocess.call(f"kill -10 {int(pid[:-1])}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def change_resource_allocation(service, alloc):
    """
    Changes the resource allocation for the given service.

    Args:
        service (str): The name of the service.
        alloc (int): The new resource allocation (in CPU units).
    """
    script_path = helpers_path / "utils" / "change_resources.sh"
    script_path = str(script_path.resolve())
    try:
        subprocess.call([script_path, "--service", service, "--alloc", str(alloc)])
    except subprocess.CalledProcessError:
        print(f"############# Error changing resources for {service}")


def get_jaeger_ip():
    """
    Gets the IP address of the Jaeger collector by running the get_jaeger_ip.sh script.

    Returns:
        str: The IP address of the Jaeger collector.
    """
    script_path = helpers_path / "utils" / "get_jaeger_ip.sh"
    script_path = str(script_path.resolve())
    try:
        ip = subprocess.check_output([script_path])
        return ip.decode("utf-8").strip()
    except subprocess.CalledProcessError:
        print("############# Error getting Jaeger IP")
        return "localhost"


def get_current_latencies(stub, period=10):
    """
    Gets the current latencies from the locust workload executor.

    Args:
        stub: gRPC stub to the locust workload executor.
        period (int): The time period (in seconds) for which to collect latencies.

    Returns:
        latencies (dict): Map from request types to their latency samples.
    """
    # Call the stub to get the latencies.
    # print(f"[INFO] Getting latencies for the last {period} seconds.")
    start_time = time.time() - period
    latency_request = collector_pb2.LatencyRequest()
    latency_request.start_time = int(start_time)
    latency_request.period = period  # seconds
    response = stub.CollectAllLatencies(latency_request)

    # Process the response to get latencies.
    latencies = {}
    for latency_data in response.data:
        req_type = latency_data.type
        latencies[req_type] = list(latency_data.latencies)

    return latencies


def read_current_grads():
    """
    Read the current gradients from the current_grads.pkl file.
    If gradient file not available, or lock not available within a second, it returns None.
    
    Returns:
        dictionary: Of the form:
        {
            "grad_alpha": {"req_type": list of gradients},
            "grad_beta": {"req_type": list of gradients},
        }
    """
        # Read the current_grads.pkl file to get the gradients.
    grad_file = helpers_path / "current_grads.pkl"
    lock_file = str(grad_file) + ".lock"
    lock = filelock.FileLock(lock_file, timeout=1)
    try:
        with lock:
            with open(grad_file, "rb") as f:
                grads = pickle.load(f)
    except filelock.Timeout:
        print("[WARN] Could not acquire lock on gradients file. Using zero gradients.")
        grads = None
    except FileNotFoundError:
        print("[WARN] Gradients file not found. Using zero gradients.")
        grads = None
    
    return grads


def write_current_grads(grads):
    """
    Write the current gradients to the current_grads.pkl file.
    If unsuccessful, raises filelock.Timeout Exception.

    Args:
        grads (dictionary): Of the form:
        {
            "grad_alpha": {"req_type": list of gradients},
            "grad_beta": {"req_type": list of gradients},
        }
    """
    grad_file = helpers_path / "current_grads.pkl"
    lock_file = str(grad_file) + ".lock"
    lock = filelock.FileLock(lock_file, timeout=1)
    try:
        with lock:
            with open(grad_file, "wb") as f:
                pickle.dump(grads, f)
    except filelock.Timeout as e:
        raise e
