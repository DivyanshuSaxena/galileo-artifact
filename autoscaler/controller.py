"""
Invoke the autothrottle controller.
Args:
    logs_path (str): The path to the logs directory.
"""

import os
import sys
import math
import time
import numpy
import pickle
import argparse
import traceback

import env
import shield
from autothrottle import AutothrottleController

# Include the controller-helpers directory in the path.
from pathlib import Path

helpers_path = Path(__file__).parent / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs
import certificates
import common_utils

parser = argparse.ArgumentParser()
parser.add_argument("--logs_dir", type=str, required=True)
parser.add_argument("--app", type=str, required=True)
parser.add_argument("--workload", type=str, required=True)
parser.add_argument("--cert_type", type=str)
parser.add_argument("--use_shield", action="store_true")
parser.add_argument("--use_samples", action="store_true")
parser.add_argument("--workload_ip", type=str, default="10.10.1.5")
parser.add_argument("--reward_type", type=str, default="normalized")
parser.add_argument("--delta", type=float, default=0.1)
parser.add_argument("--eta", type=float, default=2)

args = parser.parse_args()
logs_path = args.logs_dir
app = args.app
workload = args.workload
cert_type = args.cert_type
use_shield = args.use_shield
use_samples = args.use_samples
workload_ip = args.workload_ip

if cert_type in ["weak", "gradient", "gamma", "latency", "factor"]:
    print(f"[INFO] Using cert type: {cert_type}")
    use_certificates = True
else:
    if cert_type:
        print(f"[WARN] Unsupported cert_type provided: {cert_type}")
    use_certificates = False

if use_certificates:
    log_file = os.path.join(
        logs_path, f"autothrottle-{workload}-{time.strftime('%m%d-%H%M')}-cert.log"
    )
else:
    log_file = os.path.join(
        logs_path, f"autothrottle-{workload}-{time.strftime('%m%d-%H%M')}-no-cert.log"
    )

# Parse application graph
match app:
    case "reservation":
        appl_graph = appl_graphs.hotel_reservation
        target1components = {
            "frontend",
            "geo",
            "profile",
            "rate",
            "reservation",
            "search",
        }
    case "social":
        appl_graph = appl_graphs.social_network
        target1components = {
            "compose-post-service",
            "home-timeline-service",
            "media-frontend",
            "media-service",
            "nginx-thrift",
            "post-storage-service",
            "social-graph-service",
            "text-service",
            "unique-id-service",
            "url-shorten-service",
            "user-mention-service",
            "user-service",
            "user-timeline-service",
        }
    case _:
        raise ValueError("Unsupported workload")

# Initialize the environment and get its state
period = 30
services = appl_graph["services"]
request_types = appl_graph["request_types"]
num_types = len(request_types["by_type"])
frontend_service = appl_graph["frontend_service"]
environment = env.AutothrottleEnv(
    period, use_samples, workload_ip, services, request_types, frontend_service
)
raw_state, _ = environment.reset()

# TODO: Use different SLOs for different request types.
slo = 100

# Hyperparameters for the controller.
tower_targets = [
    0.0,
    0.02,
    0.04,
    0.06,
    0.1,
    0.15,
    0.2,
    0.25,
    0.3,
]  # see section 4 in the paper

controller = AutothrottleController(
    scaler="captain",
    targets=tower_targets,
    target1components=target1components,
    eta=args.eta,
    slo=slo,
    explore=0.1,
    use_certificates=use_certificates,
    reward_type=args.reward_type,
)

# Make the scalers object to be passed to the controller.
scalers_info = {}
for service in services:
    scalers_info[service] = {"type": "captain", "params": (0.0, 32)}

# Get the first action -- construct the stats dictionary.
stats = {
    "_tower": {
        "rps": raw_state[0],
        "allocation": raw_state[1],
        "p99_latency": 0,
        "cert_reward": 0,
    }
}
start_time = time.perf_counter()
updates = controller(start_time, stats, scalers_info)
prev_updates = updates

logs = []
certs = []
type_latencies = None
num_iterations = 0
curr_time = time.perf_counter()
last_log_time = curr_time

total_requests = [0] * num_types
total_violations = [0] * num_types

# Run for an hour (since the workload is for an hour).
if use_certificates:
    print(f"Starting the galileo controller with reward type: {args.reward_type}")

while curr_time - start_time < 3600:
    # Perform the action and invoke the controller again.
    print("Action: ", updates)

    # Check action against the shield.
    shield_activated = False
    if use_shield and type_latencies is not None:
        # First get the current parameters for all request types.
        curr_params = {}
        for index in range(num_types):
            req_type = request_types["by_type"][index]
            samples = type_latencies[index]

            if len(samples) < 10:
                continue

            # Fit a gamma distribution to the latencies.
            # Returns (shape, loc, scale) parameters.
            params = certificates.fit_gamma_distribution(samples)
            curr_params[req_type] = params

        robust, updates = shield.verify_and_propose_autoscale_action(
            curr_params,
            prev_updates,
            updates,
            args.delta,
            slo,
            tower_targets,
            app,
        )

        if not robust:
            shield_activated = True
            print("[INFO] SHIELD ACTIVATED.")

    allocations, type_latencies, _, _, _ = environment.step(updates)

    # Process the observed latencies and feed it to the controller.
    latencies = []
    workload = []
    violations = []

    if use_certificates:
        new_certs = [0] * num_types

        # If need gradients, read them here.
        if cert_type == "gradient":
            grad_dict = common_utils.read_current_grads()

    for index in range(num_types):
        num_requests = len(type_latencies[index])
        if num_requests == 0:
            latencies.append((0, 0))
            workload.append(0)
            continue

        type_latency_50p = float(numpy.percentile(type_latencies[index], 50))
        type_latency_99p = float(numpy.percentile(type_latencies[index], 99))

        # Compute certificates for the request type.
        if use_certificates:
            if len(type_latencies[index]) > 10:
                try:
                    if cert_type == "gradient":
                        _, fitted_99p, _, cert = (
                            certificates.compute_gradient_certificates(
                                type_latencies[index],
                                request_types["by_type"][index],
                                args.delta,
                                grad_dict=grad_dict,
                            )
                        )
                    elif cert_type == "weak":
                        _, fitted_99p, _, cert = (
                            certificates.compute_weak_queueing_certificates(
                                type_latencies[index], args.delta
                            )
                        )
                    elif cert_type == "latency":
                        cert = numpy.percentile(type_latencies[index], 99)
                    elif cert_type == "factor":
                        cert = 2 * numpy.percentile(type_latencies[index], 99)
                except Exception as e:
                    print(f"Certificate computation exception: {str(e)} {type(e)}")
                    # If certificate is NaN, use the 99th percentile latency.
                    cert = numpy.percentile(type_latencies[index], 99)

                    # Print the traceback for debugging.
                    traceback.print_exc()

                new_certs[index] = cert.item()
            else:
                # Continue using the last certificate -- if certificate doesn't exist, use the 99p latency.
                if len(certs) > 0:
                    new_certs[index] = certs[index]
                else:
                    new_certs[index] = type_latency_99p

        latencies.append((type_latency_50p, type_latency_99p))

        # Compute the total requests and SLO violations.
        total_requests[index] += num_requests
        total_violations[index] += len(
            [latency for latency in type_latencies[index] if latency > slo]
        )
        violations.append(total_violations[index] / total_requests[index])

        # Jaeger sampling is 0.01, so multiply by 100 to get an approximation to the actual workload.
        if use_samples:
            workload.append(100 * len(type_latencies[index]) / period)
        else:
            workload.append(len(type_latencies[index]) / period)

    # Construct the stats dictionary.
    # Autothrottle controller uses average RPS, 99th percentile latency and allocation.
    rps = sum(workload)
    allocation = sum(allocations.values()) / len(allocations)
    p99_latency = sum([latency[1] for latency in latencies]) / len(latencies)
    stats["_tower"]["rps"] = rps
    stats["_tower"]["allocation"] = allocation
    stats["_tower"]["p99_latency"] = p99_latency

    # If shield was activated, add a penalty for the tower.
    if shield_activated:
        stats["_tower"]["penalty"] = 10

    # Update the certificates and compute the certificate reward.
    if use_certificates:
        certs = new_certs

        # Compute the certificate reward.
        cert_reward = 0
        for cert in certs:
            if args.reward_type == "absolute":
                cert_reward += max(0, cert - slo)
            elif args.reward_type == "normalized":
                if cert > 0:
                    cert_reward += max(0, 1 - slo / cert)
            elif args.reward_type == "scaled":
                if cert > 0:
                    cert_reward += max(0, 1 - math.pow(slo / cert, 6))
            elif args.reward_type == "sigmoid":
                if cert > 0:
                    cert_reward += 1 / (1 + math.exp(-0.1 * (cert - slo)))
            elif args.reward_type == "replace":
                cert_reward += cert

        cert_reward /= len(certs)
        stats["_tower"]["cert_reward"] = cert_reward
        print(f"Updated Certificates: {certs} Cert Reward: {cert_reward}")

        # Log the certificates and samples in a pickle file.
        # If using gradients, also log the used gradients.
        log_dict = {"certs": certs, "samples": type_latencies}
        if cert_type == "gradient":
            if grad_dict:
                log_dict["gradients"] = grad_dict
        with open(os.path.join(logs_path, f"certs-{num_iterations}.pkl"), "wb") as f:
            pickle.dump(log_dict, f)

    curr_time = time.perf_counter()

    # Save the previous action before calling the controller.
    prev_updates = updates
    updates = controller(curr_time, stats, scalers_info)

    violation_fraction = [
        total_violations[i] / total_requests[i] if total_requests[i] else 0
        for i in range(num_types)
    ]
    print(
        f"Timestamp: {curr_time}, Workload: {workload}, Latencies: {latencies}, Allocations: {allocations}, Violations: {violation_fraction}"
    )
    if use_certificates:
        if shield_activated:
            logs.append(
                (
                    curr_time,
                    workload,
                    latencies,
                    allocations,
                    violations,
                    certs,
                    "SHIELD_ACTIVATED",
                )
            )
        else:
            logs.append(
                (curr_time, workload, latencies, allocations, violations, certs)
            )
    else:
        logs.append((curr_time, workload, latencies, allocations, violations))

    # Write to logs_path every 1 minute.
    if curr_time - last_log_time > 60:
        print("<=======================================>")
        print("Writing logs to file.")
        with open(log_file, "a") as f:
            for log in logs:
                if use_certificates:
                    f.write(
                        f"{log[0]}, {log[1]}, {log[2]}, {log[3]}, {log[4]}, {log[5]}\n"
                    )
                else:
                    f.write(f"{log[0]}, {log[1]}, {log[2]}, {log[3]}, {log[4]}\n")
                f.flush()
        logs = []
        last_log_time = curr_time

    num_iterations += 1
    if num_iterations % 10 == 0:
        print(f"Iteration {num_iterations}, Time: {curr_time - start_time}")

# Close the environment.
environment.close()

print("Complete")
