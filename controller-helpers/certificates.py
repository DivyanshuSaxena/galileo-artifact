import sys
import numpy

from pathlib import Path
from scipy import stats, optimize

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent
sys.path.append(str(helpers_path.resolve()))

import common_utils


def _bounded_optimizer_gamma_floc(bounds_dict, method="L-BFGS-B", options=None):
    """
    Create an optimizer(func, x0, args=(), disp=0) that enforces bounds on alpha and beta
    parameters of the Gamma distribution. This function keeps the location fixed at 0.

    Args:
        bounds_dict (dictionary): Dictionary storing (low, high) values for "a" and "scale".
    """
    bounds = [bounds_dict["a"], bounds_dict["scale"]]
    opts = {"maxiter": 1000, "ftol": 1e-6}
    if options:
        opts.update(options)

    def optimizer(func, x0, args=(), disp=0):
        # 1) try L-BFGS-B
        res = optimize.minimize(
            func,
            x0,
            args=args,
            method=method,
            bounds=bounds,
            options={**opts, "disp": bool(disp)},
        )
        # 2) fallback if line-search fails or any other failure
        if not res.success:
            res = optimize.minimize(
                func,
                x0,
                args=args,
                method="Powell",
                bounds=bounds,
                options={**opts, "disp": bool(disp)},
            )
        if not res.success:
            print(f"[INFO] Optimization failed: {res.message}. Returning start.")
            return x0
        return res.x

    return optimizer


def compute_perturbed_params(
    curr_alpha,
    curr_beta,
    grad_alpha,
    grad_beta,
    delta,
    alloc_changes=None,
    arrival_changes=None,
):
    """
    Compute the perturbed distribution parameters, under a delta perturbation and
    given allocation or arrival rate changes.

    Args:
        curr_alpha (float): Current value of the alpha parameter.
        curr_beta (float): Current value of the beta parameter.
        grad_alpha (list): Gradients of alpha with respect to the perturbation.
        grad_beta (list): Gradients of beta with respect to the perturbation.
        delta (float): Magnitude of the perturbation to apply.
        alloc_changes (list, optional): Change in allocation, if applicable. Defaults to None.
        arrival_changes (list, optional): Change in arrival rate, if applicable. Defaults to None.
    Returns:
        tuple: Perturbed values of (alpha, beta) after applying the delta and any allocation/arrival changes.
    """
    perturbed_alpha = curr_alpha
    perturbed_beta = curr_beta
    num_dims = len(grad_alpha)
    num_services = num_dims / 2
    for i in range(num_dims):
        if grad_alpha[i] < 0:
            # Likely processing rate -- add (-delta * grad)
            perturbed_alpha += -delta * grad_alpha[i]
            perturbed_beta += -delta * grad_beta[i]
        else:
            # Likely arrival rate -- add (delta * grad)
            perturbed_alpha += delta * grad_alpha[i]
            perturbed_beta += delta * grad_beta[i]

        if alloc_changes:
            # Only the first len(services) dimensions will be affected by the action.
            if i < num_services:
                perturbed_alpha += alloc_changes[i] * grad_alpha[i]
                perturbed_beta += alloc_changes[i] * grad_beta[i]

        if arrival_changes:
            # Only the last len(services) dimensions will be affected by the action.
            if i >= num_services:
                perturbed_alpha += arrival_changes[i - num_services] * grad_alpha[i]
                perturbed_beta += arrival_changes[i - num_services] * grad_beta[i]

    return perturbed_alpha, perturbed_beta


def fit_gamma_distribution(samples, initial_guess=None, factors=None):
    """
    Fits a Gamma distribution to the given samples using the MLE method.

    The function also includes an optional bounding mechanism to restrict the
    parameter search space around an initial guess -- this is useful for perturbation
    scenarios where we expect the parameters to not change drastically. In this case,
    both initial_guess and factors must be specified.

    Args:
        samples (list): The latency samples.
        initial_guess (dictionary, optional): Initial guess for the parameters (shape, scale).
        factors (dictionary, optional): The factor of change allowed in the parameters.

    Returns:
        params (tuple): The fitted parameters (shape, loc, scale) of the Gamma distribution.
    """
    if initial_guess is not None:
        a0 = float(initial_guess["alpha"])
        s0 = float(initial_guess["beta"])
    else:
        y = numpy.array(samples)
        m, v = y.mean(), y.var(ddof=0)
        a0 = max((m * m) / v, 1e-8)
        s0 = max(v / m, 1e-12)

    if factors is not None:
        bounds_dict = {
            "a": (
                max(1e-3, a0 * (1 - factors["alpha"])),
                a0 * (1 + factors["alpha"]),
            ),
            "scale": (
                max(1e-3, s0 * (1 - factors["beta"])),
                max(1e-3, s0 * (1 + factors["beta"])),
            ),
        }
    else:
        bounds_dict = {"a": (1e-3, 200), "scale": (1e-3, 100)}

    opt = _bounded_optimizer_gamma_floc(bounds_dict)
    params = stats.gamma.fit(
        samples,
        a0,
        method="MM",
        floc=0,
        scale=s0,
        optimizer=opt,
    )

    # For debugging purposes.
    # Compute the Wasserstein distance between the empirical and fitted distributions.
    # fitted_dist = stats.gamma(*params)
    # wass_dist = stats.wasserstein_distance(samples, fitted_dist.rvs(size=len(samples)))
    # print(f"[INFO] Fitted Gamma params: {params}, Wasserstein distance: {wass_dist}")

    return params


def compute_gamma_certificates(samples, delta, alpha):
    # Fit a Gamma distribution to the chain samples.
    params = fit_gamma_distribution(samples)
    chain_99p = stats.gamma(*params).ppf(0.99)

    # Perturbation to the params -- multiply each param by alpha * (1 + delta).
    perturbed_params = [alpha * (1 + delta) * param for param in params]
    # print(f"[INFO] Chain params: {params}, Perturbed: {perturbed_params}")

    # Find the 99p latency for the perturbed params.
    perturbed_chain_99p = stats.gamma(*perturbed_params).ppf(0.99)

    # Log details.
    sampled_99p = numpy.percentile(samples, 99)
    print(
        f"[INFO] 99p latency: fitted: {chain_99p}, perturbed: {perturbed_chain_99p}, sampled: {sampled_99p}"
    )

    return params, chain_99p, perturbed_params, perturbed_chain_99p


def compute_weak_queueing_certificates(samples, delta):
    """
    Fit a gamma distribution, perturb the parameters and compute the 99th percentile latency.
    Perturbation mechanism: change only the scale parameter of the gamma distribution (therefore, weak).

    Args:
        samples: The samples to fit the gamma distribution.
        delta: The perturbation factor.
    Returns:
        tuple: (fitted params, 99p latency for fitted params,
            perturbed params, 99p latency for perturbed params)
    """

    # Fit a Gamma distribution to the chain samples.
    # Returns (shape, loc, scale) parameters.
    params = fit_gamma_distribution(samples)
    chain_99p = stats.gamma(*params).ppf(0.99)

    # Compute the rate parameter (beta), and perturb it.
    # Worse latencies occur when the rate parameter decreases.
    rate = 1 / params[2]
    perturbed_rate = (1 - delta) * rate

    # Perturbation to the params -- change the scale parameter only.
    # We want to decrease the rate parameter => increase the scale parameter.
    perturbed_params = [params[0], params[1], 1 / perturbed_rate]
    # print(f"[INFO] Chain params: {params}, Perturbed: {perturbed_params}")

    # Find the 99p latency for the perturbed params.
    perturbed_chain_99p = stats.gamma(*perturbed_params).ppf(0.99)
    # print(f"[INFO] 99th percentile latency for perturbed distribution: {perturbed_chain_99p}")

    return params, chain_99p, perturbed_params, perturbed_chain_99p


def compute_gradient_certificates(samples, request_type, delta, grad_dict=None):
    """
    Fit a gamma distribution, and use the gradients to perturb the parameters.
    Then compute the 99th percentile latency. If gradients not available, uses weak queueing certificates.

    Args:
        samples: The samples to fit the gamma distribution.
        request_type: The request type of interest.
        delta: The perturbation factor.
        grad_dict (optional): Dictionary of gradients for alpha and beta.
            If not provided, reads using utility function in common_utils.
    Returns:
        tuple: (fitted params, 99p latency for fitted params, perturbed params, 99p latency for perturbed params)
    """

    # Fit a Gamma distribution to the chain samples.
    # Returns (shape, loc, scale) parameters.
    params = fit_gamma_distribution(samples)
    chain_99p = numpy.percentile(samples, 99)
    curr_alpha = params[0]
    loc = params[1]
    curr_beta = params[2]

    grads = grad_dict
    if not grads:
        grads = common_utils.read_current_grads()

        # If not provided and could not read, use the weak queueing perturbation.
        if not grads:
            print("[INFO] Gradients not available -- using weak queueing perturbation.")
            return compute_weak_queueing_certificates(samples, delta)

    grad_alpha = grads["grad_alpha"][request_type]
    grad_beta = grads["grad_beta"][request_type]

    perturbed_alpha, perturbed_beta = compute_perturbed_params(
        curr_alpha, curr_beta, grad_alpha, grad_beta, delta
    )

    perturbed_params = [perturbed_alpha, loc, perturbed_beta]
    # print(f"[INFO] Original params: {params}, Perturbed: {perturbed_params}")

    # Find the 99p latency for the perturbed params.
    perturbed_chain_99p = stats.gamma(*perturbed_params).ppf(0.99)
    # print(f"[INFO] 99th percentile latency for perturbed distribution: {perturbed_chain_99p}")

    if numpy.isnan(perturbed_chain_99p) or perturbed_chain_99p < chain_99p:
        print(f"[INFO] Certificates are not correct. Using the 99p latency.")
        perturbed_chain_99p = chain_99p

    return params, chain_99p, perturbed_params, perturbed_chain_99p
