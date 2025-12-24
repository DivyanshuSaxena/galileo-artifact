"""
Implementation of the shield library that can validate actions and propose new action
if the controller action leads to certificates violating the SLOs.
"""

import sys

from scipy import stats
from pathlib import Path

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent / ".." / ".." / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs
import certificates
import common_utils

log_file = Path(__file__).parent / "log.txt"


def verify_and_propose_ratelimit_action(
    curr_params, curr_rls, proposed_rls, delta, slo, app
):
    """
    Verify whether the action produced by the controller will lead to robust control.
    This implementation assumes a linear relationship between rate limits and arrival
    rates (i.e., a rate limit increase of 0.2 can be achieved by a 0.2 increase in
    arrival rates.)

    If the action is not robust, this function returns minimal change in the actions
    so as to achieve robustness.

    Args:
        curr_params (dictionary): Mapping request types to (shape, loc, scale) parameters.
        curr_rls (dictionary): Mapping request_types to current rate limits.
        proposed_rls (dictionary): Mapping request_types to proposed rate limits.
        delta (float): The perturbation factor for robustness.
        slo (int): The latency objective being targeted.
        app (string): Which application we are working with (social/reservation).
    Returns:
        bool, map: Returns a tuple of (bool, map)
            The bool is True if the action is verified to be correct or if gradients
            are unavailable.
            The map is the updated rate limit map in case the action is not robust,
            and a safe action could be computed.
    """
    # Get the application graph of interest.
    if app == "reservation":
        appl_graph = appl_graphs.hotel_reservation
    else:
        appl_graph = appl_graphs.social_network

    # Get the services and request type of the application.
    services = sorted(appl_graph["services"])
    request_types = appl_graph["request_types"]["by_type"]
    type_to_services = appl_graph["request_types"]["by_all_services"]

    # Read the current grads pkl file.
    grads = common_utils.read_current_grads()
    if not grads:
        return True, proposed_rls

    # Construct the map of services to rate limits.
    curr_limits_svc = {}
    proposed_limits_svc = {}
    for index, req_type in enumerate(request_types):
        relevant_services = type_to_services[index]
        for svc in relevant_services:
            if svc in curr_limits_svc:
                curr_limits_svc[svc] += curr_rls[req_type]
                proposed_limits_svc[svc] += proposed_rls[req_type]
            else:
                curr_limits_svc[svc] = curr_rls[req_type]
                proposed_limits_svc[svc] = proposed_rls[req_type]

    # Save the rate limits in a new map.
    updated_rls = {}
    for req_type in request_types:
        updated_rls[req_type] = proposed_rls[req_type]

    # Compute the candidate request types in case of violations.
    candidate_req_types = {}
    for req_type in request_types:
        grad_alpha = grads["grad_alpha"][req_type]
        candidate_req_types[req_type] = []

        for j, rt in enumerate(request_types):
            # A request type is a candidate if it has an overall positive gradient
            # for arrival rates.
            overall_grad = 0
            relevant_services = type_to_services[j]
            for svc in relevant_services:
                overall_grad += grad_alpha[services.index(svc)]
            if overall_grad > 0:
                candidate_req_types[req_type].append(rt)

    # Iteratively decrease rate limits until there are no violations (until max tries).
    max_tries = 2
    num_tries = 0
    while True:
        violation_found = False
        num_tries += 1

        # Verify the correctness of each request type separately.
        for req_type in request_types:
            if req_type not in grads or req_type not in curr_params:
                continue

            grad_alpha = grads[req_type]["alpha"]
            grad_beta = grads[req_type]["beta"]
            curr_alpha = curr_params[req_type][0]
            curr_loc = curr_params[req_type][1]
            curr_beta = curr_params[req_type][2]

            # Get the arrival rate changes for the given rate limit changes.
            arrival_changes = [0] * len(services)
            for j, svc in enumerate(services):
                arrival_changes[j] = proposed_limits_svc[svc] - curr_limits_svc[svc]

            perturbed_alpha, perturbed_beta = certificates.compute_perturbed_params(
                curr_alpha,
                curr_beta,
                grad_alpha,
                grad_beta,
                delta,
                arrival_changes=arrival_changes,
            )

            perturbed_params = [perturbed_alpha, curr_loc, perturbed_beta]
            new_99p = stats.gamma(*perturbed_params).ppf(0.99)

            # If action is not robust -- update the rate limit map.
            if new_99p > slo:
                violation_found = True

                # If no candidate request types are found, return the proposed rate limits.
                if not candidate_req_types[req_type]:
                    continue

                # Otherwise, update the rate limits for the candidate request types.
                for rt in candidate_req_types[req_type]:
                    # Decrease the rate limit by 10% of the proposed rate limit.
                    updated_limit = min(int(0.9 * updated_rls[rt]), 10)
                    updated_rls[rt] = updated_limit

                # Update the proposed limits at the service level.
                proposed_limits_svc = {}
                for index, r_type in enumerate(request_types):
                    relevant_services = type_to_services[index]
                    for svc in relevant_services:
                        if svc in proposed_limits_svc:
                            proposed_limits_svc[svc] += updated_rls[r_type]
                        else:
                            proposed_limits_svc[svc] = updated_rls[r_type]

        # If no violations were found, return the updated rate limits.
        if not violation_found or num_tries >= max_tries:
            break

    return False, updated_rls
