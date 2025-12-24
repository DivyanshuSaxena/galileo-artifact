import gym, ray
from ray.rllib.algorithms import ppo

import os
import sys
import math
import numpy as np
from skeleton_simulator import *

# from multi_api_simulator import *
from metric_collector import *
from overload_detection import *
import time


SLO = 100
MAX_STEPS = 10

# Parameters not used - only for compatibility with the original code.
addstep = 5
mulstep = 0.1


class MyEnv(gym.Env):
    def __init__(self, env_config):
        self.action_space = gym.spaces.Box(
            low=np.array([-0.5]), high=np.array([0.5]), dtype=np.float32
        )
        self.observation_space = gym.spaces.Box(
            low=np.array([-2000.0, -1000.0]),
            high=np.array([2000.0, 50000.0]),
            dtype=np.float32,
        )
        self.MAX_STEPS = MAX_STEPS
        self.application = env_config["application"]
        self.target_api = env_config["target_api"]
        self.period = env_config["period"]
        self.use_certificates = env_config["use_certificates"]
        self.reward_type = env_config["reward_type"]
        self.use_shield = env_config.get("use_shield", False)
        self.threshold = 1000

    def reset(self):
        self.detector = Detector(use_shield=self.use_shield)
        self.collector = Collector(
            code=self.application, type="grpc", use_certificates=self.use_certificates
        )
        self.ts = Simulator(addstep, mulstep)
        self.detector.apis[self.target_api]["threshold"] = 1000
        self.detector.reset([self.target_api])
        time.sleep(5)

        self.count = 0
        metric = self.collector.query_grpc(only_stats=True)
        if self.target_api not in metric:
            self.state = np.array([0, 100])
            self.reward = 0
            self.done = False
            self.info = {}
            return self.state

        # rps, fail, init_latency = metric[self.target_api]
        init_latency = metric[self.target_api][1]
        fail = metric[self.target_api][2]
        rps = metric[self.target_api][3]

        self.detector.apis[self.target_api]["threshold"] = rps
        self.threshold = rps
        self.detector.reset([self.target_api])
        self.goodput = rps - fail

        self.state = np.array([(rps - fail) / rps, init_latency])
        self.reward = 0
        self.done = False
        self.info = {}
        return self.state

    def step(self, action):
        if self.done:
            print("EPISODE DONE!!!")
        elif self.count == self.MAX_STEPS:
            print("Setting done to True.")
            self.done = True
        else:
            self.count += 1
            print(f"Step {self.count} completed.")

            # This first query is just to get the initial stats -- query only for stats.
            metric = self.collector.query_grpc(only_stats=True)
            if self.target_api in metric:
                latency = metric[self.target_api][1]
                fail = metric[self.target_api][2]
                rps = metric[self.target_api][3]
                tmpGoodput = rps - fail
            else:
                rps = 1000
                tmpGoodput = -1

            new_threshold = (1 + float(action)) * self.threshold
            if new_threshold <= 10:
                new_threshold = 10
            if new_threshold > rps * 1.1:
                new_threshold = rps * 1.1

            self.detector.apis[self.target_api]["threshold"] = new_threshold
            self.detector.curr_limits, shield_activated = apply_threshold_proxy(
                self.detector.curr_limits,
                [self.detector.apis[self.target_api]],
                use_shield=self.detector.use_shield,
            )

            time.sleep(self.period)

            metric = self.collector.query_grpc()
            if self.target_api in metric:
                latency = metric[self.target_api][1]
                fail = metric[self.target_api][2]
                rps = metric[self.target_api][3]

                self.goodput = rps - fail
                if tmpGoodput == -1:
                    deltaGoodput = 0
                else:
                    deltaGoodput = self.goodput - tmpGoodput

                self.threshold = self.detector.apis[self.target_api]["threshold"]
                goodputPerThres = self.goodput / self.threshold

                if self.use_certificates:
                    cert = metric[self.target_api][4]
                    print(f"Lat/Cert Comparison: {goodputPerThres}, {latency}, {cert}")
            else:
                goodputPerThres = 1
                deltaGoodput = 0
                latency = SLO
                cert = SLO

            self.state = np.array([goodputPerThres, latency])
            self.reward = deltaGoodput

            if self.use_shield and shield_activated:
                print("Shield activated!!! Adding a negative reward.")
                self.reward -= 200

            if self.use_certificates:
                if self.reward_type == "regular":
                    if cert > SLO:
                        self.reward -= cert * 0.01
                elif self.reward_type == "sigmoid":
                    if latency > SLO:
                        self.reward -= latency * 0.01
                    self.reward -= 1 / (1 + math.exp(-0.1 * (cert - SLO)))
            else:
                if latency > SLO:
                    self.reward -= latency * 0.01

        return self.state, self.reward, self.done, self.info


# Get the application from the command line.
if len(sys.argv) < 4:
    print(
        "Usage: python transfer_learning.py <application> <period> <use_certificates (0/1)> <use_shield (0/1)> <reward_type>"
    )
    sys.exit(1)

application = sys.argv[1]
period = int(sys.argv[2])
use_certificates = int(sys.argv[3]) == 1
use_shield = int(sys.argv[4]) == 1

# Reward type is an optional parameter.
# Only used for the certificate-based reward. For regular fine-tuning, keep it as "regular".
if len(sys.argv) == 6:
    reward_type = sys.argv[5]
else:
    reward_type = "regular"

# If the application is reservation, change it to hotel_reservation.
if application == "reservation":
    application = "hotel_reservation"
    popular_apis = ["search", "recommend"]
elif application == "social":
    application = "social_network"
    popular_apis = ["compose_post"]

global_config_path = os.environ["GLOBAL_CONFIG_PATH"]
with open(global_config_path, "r") as f:
    global_config = json.load(f)

# Read all target_apis from the config and redo the training for each of them.
target_apis = global_config["record_target"]

for target_api in target_apis:
    # Only execute for the popular APIs (search and recommend)
    if target_api not in popular_apis:
        continue

    ray.init()
    algo = ppo.PPO(
        env=MyEnv,
        config={
            "env_config": {
                "application": application,
                "target_api": target_api,
                "period": period,
                "use_certificates": use_certificates,
                "reward_type": reward_type,
                "use_shield": use_shield,
            },  # config to pass to env class
            "num_workers": 1,
            "train_batch_size": 32,
            "sgd_minibatch_size": 16,
        },
    )
    checkpoint_path = "./checkpoint_000701"
    algo.restore(checkpoint_path)

    save_path = f"./training/checkpoint_{application}_{target_api}_{period}"
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    total_eps = 25

    _ = 0
    while True:
        if _ % 5 == 0:
            algo.save(save_path)
            print("Model saved.")

        if _ == total_eps:
            print("Training completed.")
            break

        _ += 1
        print("Training step started.")
        print(algo.train()["episode_reward_mean"])
        print(f"{_} training step completed.")

    ray.shutdown()
