"""
Implementation of the baseline autothrottle algorithm.
"""

import os
import sys
import time
import numpy
import pickle
import random
import statistics
import subprocess
import collections
import vowpalwabbit

from pathlib import Path

# Include the controller-helpers directory in the path.
helpers_path = Path(__file__).parent / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import common_utils


def invoke_scaler(service, scaler, event):
    """
    Invoke the CaptainScaler for a service.
    Args:
        service (str): The service to invoke the scaler for.
        scaler (CaptainScaler): The CaptainScaler object for the service.
        event (threading.Event): The event to check for completion.
    """
    # Invoke the statistics functions get the throttle and usage values for the service.
    usage_history = []
    last_time = time.perf_counter()
    logs_dir = os.path.join(os.environ["HOME"], "logs")

    last_action = None
    last_stats = None

    while True:
        statistics = common_utils.get_service_stats(service)
        if statistics == "":
            time.sleep(0.1)
            continue

        # Read all lines that start with "Stats" and get the throttle and usage values.
        nr_throttled = 0
        usage = 0
        count = 0
        for line in statistics.split("\n"):
            if line.startswith("Stats"):
                parts = line.split()
                nr_throttled += int(parts[1])
                usage += int(parts[2]) / 1e6
                count += 1

        if count > 1:
            print(f"Multiple stats for {service}")
        elif count == 0:
            print(f"############# No stats for {service}")

        # Calculate the average values.
        stats = {}
        if count > 0:
            stats["cpu_stat.nr_throttled"] = nr_throttled / count
            stats["cpu_usage"] = usage / count
            last_stats = stats
        else:
            if last_stats is not None:
                stats["cpu_stat.nr_throttled"] = last_stats["cpu_stat.nr_throttled"]
                stats["cpu_usage"] = last_stats["cpu_usage"]
            else:
                stats["cpu_stat.nr_throttled"] = 0
                stats["cpu_usage"] = 0

        # Invoke the CaptainScaler to get the new limit.
        # Time calculation as per the original code of Autothrottle -- makes sure we invoke in multiples of 100ms.
        t = time.perf_counter()
        tt = (0.097 - t) * 1000 % 100 / 1000
        t += tt
        time.sleep(tt)

        limit = scaler(t, stats)
        action = int(limit * 800000) if limit < 1 else 800000

        # Check if the action is the same as the last action.
        if action != last_action:
            # Call the change_resources.sh script to change the resources.
            with open(os.path.join(logs_dir, f"{service}_scaler.log"), "a") as log_file:
                log_file.write(f"{service}: Changing resources from {last_action} to {action}\n")
            common_utils.change_resource_allocation(service, action)
            last_action = action

        # Write the usage to a pickle file every 30 seconds.
        curr_time = time.perf_counter()
        if curr_time - last_time > 30:
            usage_history.append(last_stats["cpu_usage"])
            with open(os.path.join(logs_dir, f"{service}_usage.pkl"), "wb") as f:
                pickle.dump(usage_history, f)
            last_time = curr_time

        # Check if the completion event is set.
        if event.is_set():
            break


class CaptainScaler:
    def __init__(self, service, target, initial_limit=1):
        # read-only parameters
        self.service = service
        self.target = target
        self.period = 1

        # state
        self.limit = initial_limit
        self.last_limit = initial_limit
        self.throttled_history = [0 for _ in range(int(10 * self.period))]
        self.usage_history = [0.0 for _ in range(50)]
        self.margin = 3
        self.scale_down_cd = 0
        self.last_scale_down = False

        self.last_t = None
        self.last_stats = None
        self.last_scale_t = None

    def __call__(self, t, stats):
        if self.last_t is None:
            self.last_t = t
            self.last_stats = stats
            self.last_scale_t = t
            return self.limit

        new_throttled = (
            stats["cpu_stat.nr_throttled"] - self.last_stats["cpu_stat.nr_throttled"]
        ) / (t - self.last_t)
        new_throttled = min(1, new_throttled)  # cap throttled rate at 1

        self.throttled_history.append(new_throttled)
        self.throttled_history.pop(0)
        new_usage = (stats["cpu_usage"] - self.last_stats["cpu_usage"]) / (
            t - self.last_t
        )
        self.usage_history.append(new_usage)
        self.usage_history.pop(0)
        self.last_t = t
        self.last_stats = stats
        throttled_rate = statistics.mean(self.throttled_history)

        if throttled_rate > 3 * self.target and self.last_scale_down:
            print(
                f"{self.service}: throttled rate: {throttled_rate} and target: {self.target}"
            )
            self.limit = 2 * self.last_limit - self.limit
            self.margin += throttled_rate - self.target
            self.throttled_history = [0 for _ in range(int(10 * self.period))]
            self.last_scale_down = False

        if t < self.last_scale_t + self.period - 0.0001:
            return self.limit
        self.last_limit = self.limit
        throttled_rate = statistics.mean(self.throttled_history)
        usage_max = max(self.usage_history)
        usage_std = statistics.stdev(self.usage_history)

        self.margin += throttled_rate - self.target
        self.margin = max(0, self.margin)
        self.last_scale_down = False
        if throttled_rate > 3 * self.target:
            self.limit *= 1 + (throttled_rate - 3 * self.target)
            print(
                f"Scale up action for {self.service}: new: {self.limit}, last: {self.last_limit}, tr: {throttled_rate}, target: {self.target}"
            )
        else:
            usage_limit = usage_max + usage_std * self.margin
            if usage_limit <= self.limit * 0.9 and self.scale_down_cd == 0:
                self.limit = max(self.limit * 0.5, usage_limit)
                self.last_scale_down = True
                # print(f"Scale down action for {self.service}: new: {self.limit}, last: {self.last_limit}, usage_limit: {usage_limit}, limit: {self.limit}")
        self.throttled_history = [0 for _ in range(int(10 * self.period))]
        self.limit = max(0.01, self.limit)
        self.last_scale_t = t
        return self.limit

    def update(self, target):
        if target != self.target:
            print(f"{self.service}: target changed from {self.target} to {target}")

        self.target = target


class AutothrottleController:
    learning_rate = 0.5

    def __init__(
        self,
        scaler,
        targets,
        target1components,
        slo,
        eta,
        samples=(),
        explore=0.1,
        drop_samples=0,
        aggregate_samples=100,
        use_certificates=False,
        reward_type="normalized",
    ):
        self.scaler = scaler
        self.targets = targets
        self.target1components = target1components
        self.slo = slo
        self.eta = eta
        self.samples = list(samples)
        self.explore = explore
        self.drop_samples = drop_samples
        self.aggregate_samples = aggregate_samples
        self.last_rps = None
        self.last_action = None
        self.last_action_p = None
        self.use_certificates = use_certificates
        self.reward_type = reward_type

        print(f"AutothrottleController: Setting seed 0")
        numpy.random.seed(0)

    def __call__(self, t, stats, scalers):
        if self.last_rps is not None:
            if self.drop_samples:
                self.drop_samples -= 1
            else:
                latency = stats["_tower"]["p99_latency"]
                allocation = stats["_tower"]["allocation"]
                cert_reward = stats["_tower"]["cert_reward"]
                if "penalty" in stats["_tower"]:
                    cert_reward += stats["_tower"]["penalty"]
                self.samples.append(
                    (
                        self.last_rps,
                        self.last_action,
                        self.last_action_p,
                        latency,
                        allocation,
                        cert_reward,
                    )
                )

        train_samples = list(self.samples)

        try:
            min_allocation = min(i[4] for i in train_samples if i[3] <= self.slo)
            max_allocation = max(i[4] for i in train_samples if i[3] <= self.slo)
        except ValueError:
            min_allocation = None
            max_allocation = None
        try:
            min_latency = min(i[3] for i in train_samples if i[3] > self.slo)
            max_latency = max(i[3] for i in train_samples if i[3] > self.slo)
        except ValueError:
            min_latency = None
            max_latency = None
        try:
            min_cert_reward = min(i[5] for i in train_samples if i[5] > self.slo)
            max_cert_reward = max(i[5] for i in train_samples if i[5] > self.slo)
        except ValueError:
            min_cert_reward = None
            max_cert_reward = None

        # Optinally replace latencies with certificates
        replace = self.reward_type == "replace"
        if replace:
            min_indicator, max_indicator = (
                min_cert_reward,
                max_cert_reward,
            )  # Replace cert_reward == cert
        else:
            min_indicator, max_indicator = min_latency, max_latency

        for i, (rps, action, action_p, latency, allocation, cert_reward) in enumerate(
            train_samples
        ):
            # If replace, then cert_reward is the certificate and we want to use that.
            indicator = cert_reward if replace else latency
            if indicator <= self.slo:
                try:
                    cost = (allocation - min_allocation) / (
                        max_allocation - min_allocation
                    )
                    if self.use_certificates and not replace:
                        cost += self.eta * cert_reward
                except ZeroDivisionError:
                    cost = 0.5
            else:
                try:
                    cost = (indicator - min_indicator) / (
                        max_indicator - min_indicator
                    ) + 2
                    if self.use_certificates and not replace:
                        cost += self.eta * cert_reward
                except ZeroDivisionError:
                    cost = 2.5

            train_samples[i] = (rps, action, action_p, cost)

        def median(l):
            l = sorted(l)
            if not l:
                return None
            if len(l) % 2:
                return l[len(l) // 2]
            else:
                return (l[len(l) // 2 - 1] + l[len(l) // 2]) / 2

        sample_categories = collections.defaultdict(
            lambda: collections.defaultdict(list)
        )
        for i in train_samples:
            action = i[1]
            rps = round(i[0] / self.aggregate_samples) * self.aggregate_samples
            sample_categories[action][rps].append(i)
        aggregated_samples = []
        for action in sample_categories:
            for rps in sample_categories[action]:
                aggregated_samples.append(
                    (
                        rps,
                        action,
                        1 / len(self.targets) ** 2,
                        median(i[3] for i in sample_categories[action][rps]),
                    )
                )
        train_samples = []
        if aggregated_samples:
            for i in range(10000):
                train_samples.append(random.choice(aggregated_samples))

        vw = vowpalwabbit.Workspace(
            f"--cb_explore {len(self.targets) ** 2} --epsilon 0 -l {self.learning_rate} --nn 3 --quiet"
        )
        for rps, action, action_p, cost in train_samples:
            vw.learn(f"{action+1}:{cost}:{action_p} | rps:{rps}")

        rps = stats["_tower"]["rps"]
        distribution = vw.predict(f"| rps:{rps}")
        action = numpy.random.choice(
            len(distribution), p=numpy.array(distribution) / sum(distribution)
        )
        action_p = distribution[action]

        vw.finish()

        if action_p == 1:
            stats["_tower"]["explore"] = action
            distribution = [0] * len(self.targets) ** 2
            distribution[action] += 1 - self.explore
            explore_actions = []
            x = action // len(self.targets)
            y = action % len(self.targets)
            if x - 1 >= 0:
                explore_actions.append(action - len(self.targets))
            if x + 1 < len(self.targets):
                explore_actions.append(action + len(self.targets))
            if y - 1 >= 0:
                explore_actions.append(action - 1)
            if y + 1 < len(self.targets):
                explore_actions.append(action + 1)
            for i in explore_actions:
                distribution[i] += self.explore / len(explore_actions)
            action = numpy.random.choice(
                len(distribution), p=numpy.array(distribution) / sum(distribution)
            )
            action_p = distribution[action]

        stats["_tower"]["action"] = action
        stats["_tower"]["action_p"] = action_p
        self.last_rps = rps
        self.last_action = action
        self.last_action_p = action_p

        target1 = self.targets[action // len(self.targets)]
        target2 = self.targets[action % len(self.targets)]
        updates = {}
        for k, v in scalers.items():
            if v["type"] == self.scaler:
                if k in self.target1components:
                    updates[k] = target1
                else:
                    updates[k] = target2

        return updates
