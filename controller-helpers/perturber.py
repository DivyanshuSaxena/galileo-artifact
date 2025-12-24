"""
Implementation of the perturber -- perturbs processing/arrival rates slightly to obtain gradients.
"""

import sys
import grpc
import time
import cosamp
import argparse
import filelock
import numpy as np

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent
sys.path.append(str(helpers_path.resolve()))

import appl_graphs
import certificates
import common_utils

from protos import collector_pb2_grpc


def get_alloc_map(services):
    """
    Returns a map from service names to their current resource allocations.

    Args:
        services (list): List of service names.
    Returns:
        dict: Map from service names to their current resource allocations.
    """
    allocs = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        # Start a future for each service.
        futures = {
            pool.submit(common_utils.get_current_alloc, svc): svc for svc in services
        }

        # Wait for futures to finish.
        for fut in futures:
            svc = futures[fut]
            try:
                alloc = fut.result()
            except Exception as e:
                print(f"[ERROR] Exception getting allocation for {svc}: {e}")
                alloc = -1

            if alloc == -1:
                print(f"[ERROR] Could not get current allocation for {svc}.")
                alloc = 800000  # Default to 0.8 CPU.

            allocs[svc] = alloc / 800000

    return allocs


def get_arrival_rate_map(req_types, latencies, latency_period):
    """
    Returns a map from request types to their current arrival rates.

    Args:
        req_types (list): List of request types.
        latencies (dict): Map from request types to their latency samples.
        latency_period (int): Time period over which the latencies were collected.
    Returns:
        dict: Map from request types to their current arrival rate.
    """
    curr_arrival_rates = {}
    for req_type in req_types:
        # Get the rates from the latencies.
        latency_data = latencies.get(req_type, [])
        if len(latency_data) == 0:
            print(f"[ERROR] Could not get current arrival rate for {req_type}.")
            observed_rate = 1  # Default to 1 req/s.
        else:
            observed_rate = int(len(latency_data) / latency_period)
        curr_arrival_rates[req_type] = observed_rate

    return curr_arrival_rates


def fit_gamma_map(latencies, req_types, curr_params=None):
    """
    Fits a gamma distribution to the given latencies and returns the
    alpha and beta parameters as dictionaries. If there are not enough
    samples for a request type, the corresponding alpha and beta values
    are set to None.

    Args:
        latencies (list): List of latency samples.
        req_types (list): List of request types.
        curr_params (tuple): Tuple of dictionaries -- with current values
            of (alpha, beta) parameters. The fit will be bounded to be
            within (bound) fraction of these values.
    Returns:
        Two dictionaries -- alpha params, beta params per request type.
    """
    alpha = {}
    beta = {}
    num_samples = 0
    for req_type in req_types:
        samples = latencies.get(req_type, [])
        num_samples += len(samples)

        if len(samples) < 10:
            print(f"[WARN] Not enough samples to fit gamma for {req_type}.")
            alpha[req_type] = None
            beta[req_type] = None
            continue

        # Current params -- used for bounding the fit.
        if curr_params is None:
            params = None
            factors = None
        else:
            unperturbed_alpha = curr_params[0][req_type]
            unperturbed_beta = curr_params[1][req_type]
            if unperturbed_alpha is None or unperturbed_beta is None:
                params = None
                factors = None
            else:
                params = {
                    "alpha": unperturbed_alpha,
                    "beta": unperturbed_beta,
                }
                factors = {
                    "alpha": 0.1,
                    "beta": 0.8,
                }

        # Fit a gamma distribution to the latencies.
        # Returns (shape, loc, scale) parameters.
        params = certificates.fit_gamma_distribution(
            samples, initial_guess=params, factors=factors
        )
        alpha[req_type] = params[0]
        beta[req_type] = params[2]

        # Print the 99p latencies -- for debugging purposes.
        # sampled_99p = np.percentile(samples, 99)
        # print(f"[INFO] 99p latency for {req_type}: {sampled_99p}")

    # print(f"[INFO] Over {num_samples} samples, alpha: {alpha}")
    # print(f"[INFO] Over {num_samples} samples, beta: {beta}")
    return alpha, beta


def perturb_and_collect_latencies(stub, perturbed_allocs, sleep_period=10):
    """
    Gets the parameters (alpha, beta parameters of the Gamma distribution) for
    the given resource allocations. We only perturb allocations because arrival
    rates have a natural stochasticity allowing for reasonable perturbations.

    Args:
        stub: gRPC stub to the locust workload executor.
        perturbed_allocs (dict): Map from service names to their perturbed
            resource allocations.
        sleep_period (int): Time period to wait after applying the perturbations
            before collecting latencies.

    Returns:
        latency_data: Dictionary mapping request types to their latency samples.
    """
    # Invoke the allocation enforcer script for each service in parallel.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for svc, alloc in perturbed_allocs.items():
            alloc = int(800000 * alloc)  # Convert to CPU units.
            f = pool.submit(common_utils.change_resource_allocation, svc, alloc)
            futures.append(f)

        # Ensure all tasks complete (propagates exceptions if any)
        for f in futures:
            f.result()

    # Sleep for a bit to allow the system to stabilize.
    time.sleep(5)

    # Next, wait for given period of time and collect latencies.
    time.sleep(sleep_period)

    # Get the latencies.
    latency_data = common_utils.get_current_latencies(stub, sleep_period)
    return latency_data


def estimate_gradients(
    stub, num_samples, appl_graph, curr_params, curr_allocs, curr_rate_limits
):
    """
    Estimates the gradient of the Gamma distribution parameters w.r.t.
    processing and arrival rates.

    Args:
        stub: gRPC stub to the locust workload executor.
        num_samples (int): Number of samples to use for gradient estimation.
        appl_graph (dict): Application graph dictionary.
        curr_params (tuple): Tuple of dictionaries -- with current values
            of (alpha, beta) parameters.
        curr_allocs (dict): Map from service names to their current
            resource allocations.
        curr_rate_limits (dict): Map from request types to their current
            rate limits.

    Returns:
        grad_alpha, grad_beta: Two dictionaries (service: (processing_grad, arrival_grad))
            containing the gradients for alpha and beta w.r.t. allocations and rate limits.
    """
    # We will tweak all allocations and rate limits, but the dimensions we are interested
    # in are the processing rates and arrival rates for each service.
    print(f"[INFO] Starting gradient estimation.")

    # Save the gradients in sorted order of services as this will be used by the shield.
    services = sorted(list(curr_allocs.keys()))
    num_actions = 2 * len(services)  # Processing and arrival rates for each service.

    # Get the request types.
    req_types = appl_graph["request_types"]["by_type"]

    # Construct the perturbation matrix and recovery vector.
    A = np.zeros((num_samples, num_actions))
    y_alpha = {}
    y_beta = {}
    for req_type in req_types:
        y_alpha[req_type] = np.zeros((num_samples, 1))
        y_beta[req_type] = np.zeros((num_samples, 1))

    # Current alpha and beta values -- used for computing y.
    alpha, beta = curr_params

    # Perturbation step size.
    delta = 0.05

    for i in range(num_samples):
        # First, get the perturbed allocations.
        perturbed_allocs = {}
        for svc, curr_alloc in curr_allocs.items():
            perturbation = np.random.normal(0, 1)
            perturbed_allocs[svc] = max(curr_alloc + delta * perturbation, 0.01)

        # Compute the perturbed alpha and beta values.
        sleep_period = 10  # Time period to wait after applying perturbations.
        updated_latencies = perturb_and_collect_latencies(
            stub, perturbed_allocs, sleep_period
        )

        # Process the response to get latencies and compute alpha, beta.
        perturbed_alpha, perturbed_beta = fit_gamma_map(
            updated_latencies, req_types, curr_params=curr_params
        )

        # print(f"[INFO] Sample {i}: alpha values:")
        # for req_type in req_types:
        #     print(f"    {req_type}: {alpha[req_type]} {perturbed_alpha[req_type]}")
        # print(f"[INFO] Sample {i}: beta values:")
        # for req_type in req_types:
        #     print(f"    {req_type}: {beta[req_type]} {perturbed_beta[req_type]}")

        # The allocations and arrival rates may have changed -- so we need to
        # use those final values for which the latencies were collected.
        actual_allocs = get_alloc_map(services)
        actual_rate_limits = get_arrival_rate_map(
            req_types, updated_latencies, sleep_period
        )

        # Fill in the perturbation matrix.
        for j, svc in enumerate(services):
            A[i, j] = (actual_allocs[svc] - curr_allocs[svc]) / curr_allocs[svc]

        for req_type in req_types:
            # Get the services involved for this request type.
            type_index = req_types.index(req_type)
            type_services = appl_graph["request_types"]["by_all_services"][type_index]

            # Update the perturbation matrix -- sum because same service may be involved
            # in multiple request types.
            for svc in type_services:
                perturbation = (
                    actual_rate_limits[req_type] - curr_rate_limits[req_type]
                ) / (curr_rate_limits[req_type] + 1)
                A[i, len(services) + services.index(svc)] += perturbation

        # Print ith perturbation matrix.
        # print(f"[INFO] {i}th Perturbation matrix:")
        # print(A[i, :])

        # Compute the recovery values.
        for req_type in req_types:
            if perturbed_alpha[req_type] is None or perturbed_beta[req_type] is None:
                y_alpha[req_type][i] = 0
                y_beta[req_type][i] = 0
            else:
                base_alpha = alpha[req_type]
                base_beta = beta[req_type]
                if base_alpha is None or base_beta is None:
                    print(
                        f"[WARN] Current alpha/beta for {req_type} is None -- cannot compute gradients."
                    )
                    base_alpha = 0
                    base_beta = 0
                y_alpha[req_type][i] = (perturbed_alpha[req_type] - base_alpha) / delta
                y_beta[req_type][i] = (perturbed_beta[req_type] - base_beta) / delta

    # Use CoSAMP to estimate the sparse gradients.
    # Uses sparsity of 5 -- i.e., only 5 out of the 2*num_services dimensions are non-zero.
    grad_hat_alpha = {}
    grad_hat_beta = {}
    for req_type in req_types:
        alpha_gradients = cosamp.cosamp(A, y_alpha[req_type].flatten(), 10, 0.1, 50)
        beta_gradients = cosamp.cosamp(A, y_beta[req_type].flatten(), 10, 0.1, 50)

        # Clip gradients to [-20, 20]
        alpha_gradients = np.clip(alpha_gradients, -20, 20)
        beta_gradients = np.clip(beta_gradients, -20, 20)
        grad_hat_alpha[req_type] = alpha_gradients
        grad_hat_beta[req_type] = beta_gradients

    print(f"[INFO] Estimated grad alpha: {grad_hat_alpha}")
    print(f"[INFO] Estimated grad beta: {grad_hat_beta}")

    return grad_hat_alpha, grad_hat_beta


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--app",
        help="Application to perturb (reservation or social)",
        choices=["reservation", "social"],
        required=True,
    )
    parser.add_argument(
        "--workload_ip",
        help="IP address of the workload generator",
        type=str,
        default="10.10.1.5",
    )
    parser.add_argument(
        "--num_perturbations",
        help="Number of perturbations to use for gradient estimation",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--compute_certs",
        help="Whether to compute certificates after estimating gradients",
        action="store_true",
    )

    args = parser.parse_args()
    workload_ip = args.workload_ip
    num_perturbations = args.num_perturbations
    compute_certs = args.compute_certs
    if args.app == "reservation":
        appl_graph = appl_graphs.hotel_reservation
    else:
        appl_graph = appl_graphs.social_network

    services = appl_graph["services"]
    request_types = appl_graph["request_types"]["by_type"]

    # Make a gRPC stub to collect the latencies.
    channel = grpc.insecure_channel(f"{workload_ip}:50051")
    stub = collector_pb2_grpc.LatencyCollectorStub(channel)

    # Sleep for the first 30 seconds to allow the workload to ramp up.
    print("[INFO] Sleeping for 30 seconds to allow workload to ramp up.")
    time.sleep(30)

    # Sleep for about 30 seconds to get the initial set of latencies.
    latency_period = 30
    time.sleep(latency_period)

    # Start the perturber as a standalone process.
    while True:
        # Get the current parameters (alpha, beta) by collecting latencies
        # in the last (latency_period) seconds.
        curr_latencies = common_utils.get_current_latencies(stub, latency_period)
        curr_alpha, curr_beta = fit_gamma_map(curr_latencies, request_types)
        curr_params = (curr_alpha, curr_beta)

        # Get the current allocations and rate limits from the controller.
        curr_allocs = get_alloc_map(services)
        curr_rate_limits = get_arrival_rate_map(
            request_types, curr_latencies, latency_period
        )

        # print(f"[INFO] Current allocs: {curr_allocs}")
        # print(f"[INFO] Current rate limits: {curr_rate_limits}")

        grad_alpha, grad_beta = estimate_gradients(
            stub,
            num_perturbations,
            appl_graph,
            curr_params,
            curr_allocs,
            curr_rate_limits,
        )

        # Write the gradients to the pickle file.
        grads_to_write = {"grad_alpha": grad_alpha, "grad_beta": grad_beta}
        try:
            common_utils.write_current_grads(grads_to_write)
        except filelock.Timeout as e:
            print(
                "Could not acquire lock to write gradients -- skipping this iteration."
            )

        # CHECK: Compute the certificates using the current gradients.
        if compute_certs:
            delta = 0.05
            for req_type in request_types:
                samples = curr_latencies.get(req_type, [])
                if len(samples) < 10:
                    print(
                        f"[WARN] Not enough samples to compute certificates for {req_type}."
                    )
                    continue

                params, chain_99p, perturbed_params, perturbed_chain_99p = (
                    certificates.compute_gradient_certificates(samples, req_type, delta)
                )
                print(
                    f"[INFO] For {req_type}, current 99p: {chain_99p}, certificate: {perturbed_chain_99p}"
                )

        # Sleep for a bit before the next iteration.
        time.sleep(10)
