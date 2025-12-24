"""
Implementation of the shield library that can validate actions and propose new action
if the controller action leads to certificates violating the SLOs.
"""

import sys

from scipy import stats
from pathlib import Path

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs
import certificates
import common_utils


def verify_and_propose_autoscale_action(
    curr_params, curr_trs, proposed_trs, delta, slo, throttle_targets, app
):
    """
    Verify whether the action produced by the controller will lead to robust control.
    This implementation assumes a negative linear relationship between throttle ratios
    and allocation (i.e., a throttle ratio increase of 0.2 can be achieved by a
    0.2 CPU decrease in allocation.)

    If the action is not robust, this function returns minimal change in the actions
    so as to achieve robustness.

    Args:
        curr_params (dictionary): Mapping request types to (shape, loc, scale) parameters.
        curr_trs (dictionary): Mapping services to current throttle ratios.
        proposed_trs (dictionary): Mapping services to proposed throttle ratios.
        delta (float): The perturbation factor for robustness.
        slo (int): The latency objective being targeted.
        throttle_targets (list): List of possible throttle targets.
        app (string): Which application we are working with (social/reservation).
    Returns:
        bool, map: Returns a tuple of (bool, map)
            The bool is True if the action is verified to be correct or if gradients
            are unavailable.
            The map is the updated throttle ratio map in case the action is not robust,
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

    # Read the current grads pkl file.
    grads = common_utils.read_current_grads()
    if not grads:
        print("[INFO] Gradients not available. Cannot activate shield.")
        return True, proposed_trs

    # Save the throttle ratios in a new map.
    updated_trs = proposed_trs.copy()

    # Verify the correctness of each request type separately.
    for req_type in request_types:
        grad_alpha = grads["grad_alpha"][req_type]
        grad_beta = grads["grad_beta"][req_type]

        if req_type not in curr_params:
            continue

        curr_alpha = curr_params[req_type][0]
        curr_loc = curr_params[req_type][1]
        curr_beta = curr_params[req_type][2]

        # Get the alloc changes for the given throttle ratio changes.
        # We use a negative relationship.
        alloc_changes = [0] * len(services)
        for j, svc in enumerate(services):
            alloc_changes[j] = -(proposed_trs[svc] - curr_trs[svc])

        perturbed_alpha, perturbed_beta = certificates.compute_perturbed_params(
            curr_alpha,
            curr_beta,
            grad_alpha,
            grad_beta,
            delta,
            alloc_changes=alloc_changes,
        )

        perturbed_params = [perturbed_alpha, curr_loc, perturbed_beta]
        new_99p = stats.gamma(*perturbed_params).ppf(0.99)

        # If action is not robust -- update the throttle ratio map.
        if new_99p > slo:
            # Find candidate services that have negative gradients for allocation.
            # Increase their throttle ratios one-by-one.
            candidate_services = []
            for j, svc in enumerate(services):
                # A service is a candidate if it has a negative gradient for allocation.
                if grad_alpha[j] < 0:
                    candidate_services.append(svc)

            # If no candidate services are found, return the proposed throttle ratios.
            if not candidate_services:
                print(
                    f"[INFO] No candidate services found for {req_type}. Returning proposed throttle ratios."
                )
                continue

            # Otherwise, update the throttle ratios for the candidate services.
            for svc in candidate_services:
                # Find the next highest throttle target for the service.
                next_target = None
                for target in throttle_targets:
                    if target > updated_trs[svc]:
                        next_target = target
                        break

                # If a next target is found, update the throttle ratio.
                if next_target is not None:
                    updated_trs[svc] = next_target

    return False, updated_trs
