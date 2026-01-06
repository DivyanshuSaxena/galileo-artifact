# Galileo Artifact Evaluation

This repository contains the artifact for **Galileo**, a reinforcement learning-based resource management system for microservices that uses performance certificates for efficient adaptation to workload changes.

Galileo will appear as a paper at [NSDI'26](https://www.usenix.org/conference/nsdi26).
To cite this work, please use the citation provided [here](#citation).


## Overview

Galileo is a resource management framework that builds Performance Robustness Certificates (or PeRCs) and combines them with controllers.
A PeRC provides a worst-case bound on end-to-end latency for microservices, using a queuing-theoretic modeling of microservices.
Galileo combines PeRCs with two types of controllers: 
- **Admission Control**: Applied on top of TopFull [SIGCOMM'24], an RL-based rate limiting for API endpoints
- **Resource Allocation**: Applied on top of Autothrottle [NSDI'24], a two-tier adaptive CPU allocation controller for microservices

The artifact supports experiments on two microservice benchmarks from DeathStarBench:
- Hotel Reservation
- Social Network

**Notes for artifact evaluation:** 


## Prerequisites

### Hardware Requirements
- 5 Cloudlab nodes (recommended profile: m510 on Utah cluster)
  - 4 nodes for Kubernetes cluster (1 control + 3 workers)
  - 1 node for workload generation
- Each node: 16 cores, 64 GB RAM

### Software Requirements
- Ubuntu 22.04 recommended
- Python 3.10+
- Kubernetes 1.24+
- Docker
- Go 1.18+ (for proxy components)


## Step 1: Setup Instructions

### Important Notes
1. **All the following steps run on your local terminal** -- each script will automatically run appropriate commands on the Cloudlab nodes.
Just ensure that the local machine has access to Cloudlab experiment nodes.
2. **Different cluster for each application** -- it is recommended to set up a different Cloudlab cluster for each application (i.e., Social Network and Hotel Reservation) to avoid interference between the two applications.

### Step 1a. Setting Environment Variables

First, set up your Cloudlab environment variables in your terminal:

```bash
# Set Cloudlab credentials
export CLOUDLAB_USERNAME=<your_username>
export CLOUDLAB_EXPERIMENT=<experiment_name>
export CLOUDLAB_PROJECT=<project_name>-PG0
export CLOUDLAB_CLUSTER=utah.cloudlab.us
```

or simply run:

```bash
source ./cloudlab/set_env.sh <CLOUDLAB_USERNAME> <CLOUDLAB_EXPERIMENT> <CLOUDLAB_PROJECT>
```

**Where do I find the username, experiment name and project name on Cloudlab?**  
Once you have started a cluster on Cloudlab, on the experiment page, you can find `CLOUDLAB_USERNAME` in the `Creator` field, `CLOUDLAB_EXPERIMENT` in the `Name` field, and `CLOUDLAB_PROJECT` in the `Project` field. 

### Step 1b. Initial Configuration

Setup all dependencies for running experiments:

```bash
./cloudlab/setup_experiment.sh <APPLICATION (reservation/social)>
```

**Note:** Replace `<APPLICATION>` with exactly one of `reservation` (for Hotel Reservation) or `social` (for Social Network) for a cluster.

The above setup is expected to take up to 10 minutes. Once done, check if the cluster is functioning up to the mark by running the following health-check script.

```bash
# Check cluster health
./cloudlab/check_cluster_health.sh $CLOUDLAB_EXPERIMENT <APPLICATION (reservation/social)>
```

If the cluster is not functioning properly, the script will restart the application and/or the cluster accordingly.
Finally, the script should end with an affirmative statement like the following (notably the latency must be below 100ms):

```
CLUSTER HEALTH CHECK PASSED with latency: 2.375 ms.
```

## Step 2: Running Experiments (for Artifact Evaluation)

**This section provides instructions to reproduce the main results from the Galileo paper. To see how to use the provided scripts for running experiments, please refer to [this section of the README](#general-usage).**

In the paper, we construct Galileo controllers for microservice autoscaling and admission control. In particular, we build on top of [Autothrottle](https://www.usenix.org/conference/nsdi24/presentation/wang-zibo) and [TopFull](https://dl.acm.org/doi/10.1145/3651890.3672253). Following are the instructions comparing the Galileo counterparts of each against the vanilla learned controllers.

**The instructions below assume that: (i) you have already set up the Cloudlab cluster and application as per the [Setup Instructions](#setup-instructions) section; and (ii) the Hotel Reservation application is running on the cluster.**

### I. Galileo vs. Autothrottle

#### Executing the controllers

Execute the following set of commands for each of `rps3`, `rps4`, `rps5`, `rps6`, and `rps7`.

```bash
./cloudlab/run_autoscaler.sh $CLOUDLAB_EXPERIMENT autothrottle reservation rps3 0 0 ./autoscaler-results nostress

./cloudlab/check_cluster_health.sh $CLOUDLAB_EXPERIMENT reservation

./cloudlab/run_autoscaler.sh $CLOUDLAB_EXPERIMENT galileo-shield reservation rps3 0.2 16 ./autoscaler-results nostress

./cloudlab/check_cluster_health.sh $CLOUDLAB_EXPERIMENT reservation
```

Important points:
1. The above four commands together will finish in about 2 hours for each workload. If you want to run some quick experiments, you can reduce the duration of the runs for each controller by adding the time duration (in seconds) at the end of the command, as follows:
    ```bash
    ./cloudlab/run_autoscaler.sh $CLOUDLAB_EXPERIMENT autothrottle reservation rps3 0 0 ./autoscaler-results nostress 1200
    ```
2. Once at least one workload has been executed for both Autothrottle and Galileo, you can plot the results using the instructions below. As more workloads are completed, the plots can be re-generated. This will result in the Figure 9a in the paper.
3. Repeating the above commands on the Social Network application cluster will result in Figure 9b.

#### Plotting results

Generate plots from the collected data:

```bash
cd autoscaler/plots
python plot_aggregate_controller_comparison.py galileo_autothrottle 0 ./autoscaler-results/reservation
```

The plot will be available in a file named `galileo_autothrottle.png` in `autoscaler/plots/figures/`. Change the respective argument in the above command to save in a different file.

### II. Galileo vs. TopFull

#### Executing the controllers

Execute the following set of commands for each of `rps3`, `rps4`, `rps5`, `rps6`, and `rps7`.

```bash
./cloudlab/run_admission.sh $CLOUDLAB_EXPERIMENT topfull reservation rps3 ./admission-results ~/admission/checkpoints/reservation/topfull nostress

./cloudlab/check_cluster_health.sh $CLOUDLAB_EXPERIMENT reservation

./cloudlab/run_admission.sh $CLOUDLAB_EXPERIMENT galileo-shield reservation rps3 ./admission-results ~/admission/checkpoints/reservation/galileo-shield nostress

./cloudlab/check_cluster_health.sh $CLOUDLAB_EXPERIMENT reservation
```

Important points:
1. The above four commands together will finish in about 2 hours for each workload. If you want to run some quick experiments, you can reduce the duration of the runs for each controller by adding the time duration (in seconds) at the end of the command, as follows:
    ```bash
    ./cloudlab/run_admission.sh $CLOUDLAB_EXPERIMENT topfull reservation rps3 ./admission-results ~/admission/checkpoints/reservation/topfull nostress 1200
    ```
2. Once at least one workload has been executed for both TopFull and Galileo, you can plot the results using the instructions below. As more workloads are completed, the plots can be re-generated. This will result in the Figure 10a in the paper.
3. Repeating the above commands on the Social Network application cluster will result in Figure 10b.

#### Plotting results

Generate plots from the collected data:

```bash
cd admission/plots
python plot_aggregate_controller_comparison.py galileo_topfull 0 ./admission-results/reservation
```

The plot will be available in a file named `galileo_topfull.png` in `admission/plots/figures/`. Change the respective argument in the above command to save in a different file.


## General Usage

### Autoscaler Experiments

Run autoscaler experiments by simply running the following script:
```bash
./cloudlab/run_autoscaler.sh <exp_name> <controller> <app> <workload> <delta> <eta> <results_dir> [stress] [duration]
```

**Arguments:**

- `exp_name`: Cloudlab experiment name
- `controller`: Controller to use
    - `galileo-shield`: Complete Galileo controller
    - `galileo-sigmoid`: Galileo without the shield (and only using the sigmoid robustness reward)
    - `autothrottle`: Autothrottle baseline
- `app`: Application benchmark
    - `social`: Social Network
    - `reservation`: Hotel Reservation
- `workload`: Workload trace name (one of `rps3`, `rps4`, `rps5`, `rps6`, `rps7`)
- `delta`: Perturbation magnitude (e.g., `0.1`)
- `eta`: Certificate cost weight (e.g., `2`)
- `results_dir`: Directory to store experiment results
- `stress` *(optional)*: Whether to apply stress conditions (`stress` | `nostress`, default: `nostress`)
- `duration` *(optional)*: Experiment duration in seconds (default: `3660`)

**Example:**

```bash
# Run Galileo Autoscaler on Social Network
./cloudlab/run_autoscaler.sh test-exp galileo-shield social rps5 0.1 2 ./results nostress 3660
```

### Admission Control Experiments

#### Run using pre-trained models

Run RL-based admission control with different configurations:

```bash
./cloudlab/run_admission.sh <exp_name> <controller> <app> <workload> [stress]
```

**Arguments:**

- `exp_name`: Cloudlab experiment name
- `controller`: Controller type to use
    - `galileo-shield`: Complete Galileo controller
    - `galileo-sigmoid`: Galileo without the shield (and only using the sigmoid robustness reward)
    - `baseline`: TopFull baseline without certificates
- `app`: Application benchmark
    - `social`: Social Network
    - `reservation`: Hotel Reservation
- `workload`: Workload trace name (one of `rps3`, `rps4`, `rps5`, `rps6`, `rps7`)
- `results_dir`: Directory to store experiment results
- `checkpoint_path`: Path to the trained model checkpoint
    - Model checkpoints are available in the `admission/checkpoints/` directory.
- `stress` *(optional)*: Whether to apply stress conditions (`stress` | `nostress`, default: `nostress`)

**Example:**

```bash
# Run Galileo Admission Controller with Shield on Social Network
./cloudlab/run_admission.sh test-exp galileo-shield social rps3 ./results admission/checkpoints/social/galileo-shield nostress
```

#### Training

Train RL models with performance certificates:

```bash
./cloudlab/perform_topfull_training.sh <exp_name> <app> <workload> <use_certificates> <use_shield> [reward_type]
```

**Arguments:**

- `exp_name`: Cloudlab experiment name
- `app`: Application benchmark
    - `social`: Social Network
    - `reservation`: Hotel Reservation
- `workload`: Workload trace name (e.g., `rps3`)
- `use_certificates`: Whether to use performance certificates
    - `0`: Without certificates
    - `1`: With certificates
- `use_shield`: Whether to enable shield mechanism
    - `0`: Shield disabled
    - `1`: Shield enabled
- `reward_type` *(optional)*: Type of reward function to use
    - `regular`: Standard reward
    - `normalized`: Normalized reward
    - `scaled`: Scaled reward
    - `sigmoid`: Sigmoid-based reward (default)

**Example:**

```bash
# Train with certificates and shield using sigmoid reward
./cloudlab/perform_topfull_training.sh test-exp social rps4 1 1 sigmoid
```


## Citation

If you use this artifact, please cite:

```bibtex
@inproceedings{galileo,
  title={Towards Performance Robustness for Microservices},
  author={Divyanshu Saxena, Gaurav Vipat, Jiaxin Lin, Jingbo Wang, Isil Dillig, Sanjay Shakkottai, Aditya Akella},
  booktitle = {23rd USENIX Symposium on Networked Systems Design and Implementation (NSDI 26)},
  year = {2026},
  publisher = {USENIX Association},
}
```

## Contact

For questions or issues with running this artifact:
- Open an issue in this repository
- Contact: Divyanshu Saxena (`dsaxena@cs.utexas.edu`)
