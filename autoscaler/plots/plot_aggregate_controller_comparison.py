"""
Read the given controller logs and plot their comparison plots.
Args:
    log_dirs (list): List of paths to the log dirs
"""

import os
import sys
import numpy
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.lines import Line2D
from collections import defaultdict

import utils

# Include the controller-helpers directory in the path.
from pathlib import Path

helpers_path = Path(__file__).parent / ".." / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs

if len(sys.argv) < 3:
    print(
        "Usage: python3 plot_aggregate_controller_comparison.py <save_name> <stress(0/1)> <log_dir>"
    )
    sys.exit(1)

save_name = sys.argv[1]
use_stress = int(sys.argv[2]) == 1
log_dir = sys.argv[3]

if "reservation" in log_dir:
    app = "reservation"
    type_names = appl_graphs.hotel_reservation["request_types"]["by_type"]
    # Type order from global_config
    # Type weights from locustfile
    type_weights = [
        0.05,  # user_login
        0.60,  # search_hotel
        0.39,  # recommend
        0.05,  # reserve
    ]
elif "social" in log_dir:
    app = "social"
    type_names = appl_graphs.social_network["request_types"]["by_type"]
    type_weights = [
        0.20,  # compose_post
        0.65,  # read_home_timeline
        0.15,  # read_user_timeline
    ]
else:
    raise ValueError("Unrecognized application")

num_types = len(type_names)

controllers = []

# Prepare a list to collect timeseries data for the dataframe
timeseries_data = []

# Get all relevant log directories.
for d in os.listdir(log_dir):
    if not os.path.isdir(os.path.join(log_dir, d)):
        continue

    is_stress = d.split("-")[-3] == "stress"
    if use_stress and not is_stress:
        continue
    if not use_stress and is_stress:
        continue

    # Extract rps value: Find rpsX in the string.
    rps = None
    for part in d.split("-"):
        if part.startswith("rps"):
            rps = int(part[3:])
            break
    if rps is None:
        raise ValueError("Could not find rps value in directory name: " + d)

    # Extract controller name: Part of the dir before rpsX
    controller = d.split("-rps")[0]

    if controller not in controllers:
        controllers.append(controller)

    # Get the log file: the file that ends with .log in the directory.
    log_file = None
    for f in os.listdir(os.path.join(log_dir, d)):
        if f.endswith(".log") and f.startswith("autothrottle"):
            log_file = os.path.join(log_dir, d, f)
            break
    if log_file is None:
        raise ValueError("Could not find log file in directory: " + d)

    ts, wl, _, lat_99p, alloc, v, _ = utils.read_controller_log(log_file, type_names)

    # Add timeseries data for each time step
    for i in range(len(ts)):
        entry = {
            "controller": controller,
            "rps": rps,
            "timestamp": ts[i],
            "workload": wl[i],
            "allocation": sum(min(1, v) for v in alloc[i].values()) * 8,
        }

        # print(controller, rps, i, v[i])

        # Add latency columns for each type
        for type_idx in range(num_types):
            entry[f"latency_99p_type{type_idx+1}"] = lat_99p[type_idx][i]
            # Add violations columns for each type
            # Sometimes one request type's violation is missing (either type_idx 0 or 3).
            # Match violations to previous timestep to infer which one is dropped.
            if len(v[i]) == num_types:
                # All types present
                for type_idx in range(num_types):
                    entry[f"violation_type{type_idx+1}"] = 100 * v[i][type_idx]
            elif len(v[i]) == num_types - 1 and i > 0:
                # One type missing, try to infer which one
                prev_v = (
                    timeseries_data[-1][f"violation_type1"],
                    timeseries_data[-1][f"violation_type2"],
                )
                if num_types > 2:
                    prev_v += (timeseries_data[-1][f"violation_type3"],)
                if num_types > 3:
                    prev_v += (timeseries_data[-1][f"violation_type4"],)
                missing_idx = None

                # Compare with previous timestep
                if abs(prev_v[0] - v[i][0]) / max(abs(prev_v[0]), 1e-8) < 0.10:
                    missing_idx = num_types - 1
                elif abs(prev_v[-1] - v[i][-1]) / max(abs(prev_v[-1]), 1e-8) < 0.10:
                    missing_idx = 0
                # else:
                #     print(
                #         "Warning: Could not infer missing violation type at controller {}, rps {}, timestep {}".format(
                #             controller, rps, i
                #         )
                #     )
                #     print("Will use the previous timestep's violations for all types.")

                for type_idx in range(num_types):
                    if missing_idx is None:
                        entry[f"violation_type{type_idx+1}"] = prev_v[type_idx]
                    else:
                        # Fill in the missing violation with previous timestep's value
                        if type_idx == missing_idx:
                            entry[f"violation_type{type_idx+1}"] = prev_v[type_idx]
                        else:
                            # Map the remaining values
                            # If missing_idx is 0, v[i][type_idx-1] for type_idx>0
                            # If missing_idx is num_types-1, v[i][type_idx] for type_idx<num_types-1
                            if missing_idx == 0:
                                entry[f"violation_type{type_idx+1}"] = (
                                    100 * v[i][type_idx - 1]
                                )
                            else:
                                entry[f"violation_type{type_idx+1}"] = (
                                    100 * v[i][type_idx]
                                )
            else:
                for type_idx in range(num_types):
                    entry[f"violation_type{type_idx+1}"] = (
                        timeseries_data[-1][f"violation_type{type_idx+1}"]
                        if timeseries_data
                        else 0.0
                    )
        timeseries_data.append(entry)

# Create the dataframe
df_timeseries = pd.DataFrame(timeseries_data)

num_entries = len(df_timeseries)

# Keep only the latest (controller, rps) entry in the dataframe.

# Print the violation for each controller, rps, and last timestamp
for controller in controllers:
    df_ctrl = df_timeseries[df_timeseries["controller"] == controller]
    print(f"Controller: {controller}")
    for rps_val in df_ctrl["rps"].unique():
        df_rps = df_ctrl[df_ctrl["rps"] == rps_val]
        last_row = df_rps[df_rps["timestamp"] == df_rps["timestamp"].max()]
        violations = [
            last_row[f"violation_type{type_idx+1}"].values[0]
            for type_idx in range(num_types)
        ]
        print(f"  RPS: {rps_val}, Violations: {violations}")

# Arrange controllers as follows: autothrottle, atplusplus, galileo-sigmoid, galileo-shield.
ordered_names = ["autothrottle", "atplusplus", "galileo-sigmoid", "galileo-shield"]
controllers = [name for name in ordered_names if name in controllers]
print(controllers)

# Compute averaged statistics over all traces for each controller using the dataframe
average_violations = {}
average_allocations = {}
average_peak_allocations = {}

for controller in controllers:
    df_ctrl = df_timeseries[df_timeseries["controller"] == controller]

    # Average allocations
    average_allocations[controller] = df_ctrl["allocation"].mean()

    # Peak allocations
    average_peak_allocations[controller] = df_ctrl["allocation"].max()

    # For each rps, get the last timestamp's violation values
    last_violations = []
    for rps_val in df_ctrl["rps"].unique():
        df_rps = df_ctrl[df_ctrl["rps"] == rps_val]
        last_row = df_rps[df_rps["timestamp"] == df_rps["timestamp"].max()]
        last_violations.append(
            [
                last_row[f"violation_type{type_idx+1}"].values[0]
                for type_idx in range(num_types)
            ]
        )
    average_violations[controller] = numpy.mean(last_violations, axis=0)

# Compare galileo controllers with baselines
galileo_controllers = [c for c in controllers if "galileo" in c]
baseline_controllers = [c for c in controllers if c in ["autothrottle", "atplusplus"]]

for controller in [c for c in controllers if "galileo" in c]:
    for other_controller in baseline_controllers:
        violations_comparison = (
            average_violations[other_controller] / average_violations[controller]
        )
        allocations_comparison = (
            average_allocations[controller] / average_allocations[other_controller]
        )
        peak_allocations_comparison = (
            average_peak_allocations[controller]
            / average_peak_allocations[other_controller]
        )

        print(f"{controller} vs {other_controller}:")
        print(violations_comparison)
        print(f"\tAverage Violations: {average_violations[other_controller].mean()}%")
        print(
            f"\tViolations: {[(1 - 1/v) * 100 for v in [min(violations_comparison), max(violations_comparison)]]}% less"
        )
        print(f"\tAllocations: {(1 - 1/allocations_comparison) * 100}% more")
        print(f"\tPeak Allocations: {(1 - 1/peak_allocations_comparison) * 100}% more")

# Plot the graphs.
plt.rcParams["font.size"] = 22
fig = plt.figure(figsize=(5.2, 4.8))
gs = fig.add_gridspec(2, 2, height_ratios=[2, 2])
ax1 = fig.add_subplot(gs[0, :])
ax2 = fig.add_subplot(gs[1, 0])
ax3 = fig.add_subplot(gs[1, 1])
axes = [ax1, ax2, ax3]

colors = ["#D5E8D4", "#FFE6CC", "#F8CECC", "#CDD9E9", "#F1E6C6", "#DBCFE1"]
edge_colors = ["#82B366", "#D79B00", "#B85450", "#6C8EBF", "#D6B656", "#9673A6"]
hatches = ["/", "x", "|", "\\", "+", "-"]
markers = ["o", "^", "P", "s", "v", "^"]

legend_labels = {
    "autothrottle": "Autothrottle",
    "atplusplus": "Autothrottle++",
    "galileo-sigmoid": "Galileo w/o Shield",
    "galileo-shield": "Galileo",
    "galileo-replace": "Galileo Replace",
    "galileo-sigmoid-d0.1": "Galileo 0.1",
    "galileo-sigmoid-d0.2": "Galileo 0.2",
    "galileo-sigmoid-d0.5": "Galileo 0.5",
}

num_controllers = len(controllers)
# legend_patches = []
# for i in range(num_controllers):
#     legend_patches.append(
#         mpatches.Patch(
#             facecolor=colors[i],
#             label=legend_labels[controllers[i]],
#             hatch=hatches[i],
#             edgecolor=edge_colors[i],
#         )
#     )

legend_handles = [
    Line2D(
        [0], [0],
        marker=markers[i],
        color='w',
        label=legend_labels.get(controllers[i], controllers[i]),
        markerfacecolor=edge_colors[i],
        markeredgecolor="black",
        markersize=12,
        linewidth=0
    )
    for i in range(num_controllers)
]

xpos = numpy.arange(num_types) / 2 * num_controllers
width = 0.35
# Prepare violations data for boxplot: For each controller, for each request type, collect the violation at the latest timestamp for each rps.
violations = {controller: [[] for _ in range(num_types)] for controller in controllers}

for controller in controllers:
    df_ctrl = df_timeseries[df_timeseries["controller"] == controller]
    for rps_val in df_ctrl["rps"].unique():
        df_rps = df_ctrl[df_ctrl["rps"] == rps_val]
        last_row = df_rps[df_rps["timestamp"] == df_rps["timestamp"].max()]
        for type_idx in range(num_types):
            violations[controller][type_idx].append(
                last_row[f"violation_type{type_idx+1}"].values[0]
            )

# Boxplot for violations per controller per request type
for i in range(num_controllers):
    # Center the scatter points at the xtick positions
    pos = [x + width * (i - (num_controllers - 1) / 2) for x in xpos]
    print(pos)
    for type_idx in range(num_types):
        x = pos[type_idx]
        y_vals = violations[controllers[i]][type_idx]
        print(controllers[i], type_idx, y_vals)
        axes[0].scatter(
            [x] * len(y_vals),
            y_vals,
            color=edge_colors[i],
            marker=markers[i],
            s=140,
            label=legend_labels.get(controllers[i], controllers[i]),
            alpha=0.5,
            edgecolors="black",
            linewidths=1,
        )

axes[0].set_xticks(xpos)
axes[0].set_xticklabels([f"RT {j}" for j in range(1, num_types + 1)])
# axes[0].set_xlabel("Request Types", labelpad=2)
axes[0].set_ylabel("SLO Violations\n(%)")

# Prepare mean and peak allocations for each controller per rps.
rps_values = sorted(df_timeseries["rps"].unique())
print("RPS Values:", rps_values)

mean_allocations = defaultdict(list)
peak_allocations = defaultdict(list)
for controller in controllers:
    df_ctrl = df_timeseries[df_timeseries["controller"] == controller]
    for rps_val in rps_values:
        df_rps = df_ctrl[df_ctrl["rps"] == rps_val]
        mean_allocations[controller].append(df_rps["allocation"].mean())
        peak_allocations[controller].append(df_rps["allocation"].max())

pos = numpy.arange(0, num_controllers / 2, 0.5)
for i in range(num_controllers):
    # Plot all mean allocations as scatter points
    axes[1].scatter(
        [pos[i]] * len(mean_allocations[controllers[i]]),
        mean_allocations[controllers[i]],
        color=edge_colors[i],
        marker=markers[i],
        s=140,
        label=legend_labels.get(controllers[i], controllers[i]),
        alpha=0.5,
        edgecolors="black",
        linewidths=2,
    )

    # Plot all peak allocations as scatter points
    axes[2].scatter(
        [pos[i]] * len(peak_allocations[controllers[i]]),
        peak_allocations[controllers[i]],
        color=edge_colors[i],
        marker=markers[i],
        s=140,
        label=legend_labels.get(controllers[i], controllers[i]),
        alpha=0.5,
        edgecolors="black",
        linewidths=2,
    )

axes[1].set_xticks([])
axes[1].set_xticklabels([])
axes[1].set_xlim(-0.5, pos[-1] + 0.5)
axes[1].set_xlabel("Average")
axes[1].set_ylabel("CPU Core\nAllocations")
# axes[1].set_yscale("log")
if app == "reservation":
    yticks = [0, 5, 10, 15]
elif app == "social":
    yticks = [0, 8, 16, 24]
axes[1].set_yticks(yticks)
axes[1].set_yticklabels(yticks)
axes[1].tick_params(axis="y", which="minor", labelleft=False)

axes[2].set_xticks([])
axes[2].set_xticklabels([])
axes[2].set_xlim(-0.5, pos[-1] + 0.5)
axes[2].set_xlabel("Peak")
# axes[2].set_yscale("log")
if app == "reservation":
    yticks = [0, 5, 10, 15]
elif app == "social":
    yticks = [0, 8, 16, 24]
    # yticks = [0, 15, 30, 45]
axes[2].set_yticks(yticks)
axes[2].set_yticklabels(yticks)
axes[2].tick_params(axis="y", which="minor", labelleft=False)

# Split legend handles into two groups: one-word controllers and longer ones
one_word_handles = []
long_word_handles = []
for i, c in enumerate(controllers):
    label = legend_labels.get(c, c)
    if " " not in label and "-" not in label:
        one_word_handles.append(legend_handles[i])
    else:
        long_word_handles.append(legend_handles[i])

# Place one-word controllers on one line (ncol=2), longer ones on a separate line below (ncol=len(long_word_handles))
if one_word_handles:
    fig.legend(
        handles=one_word_handles,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 1.05),
        columnspacing=0.25,
        handletextpad=0.05,
    )

if long_word_handles:
    fig.legend(
        handles=long_word_handles,
        loc="upper center",
        ncol=len(long_word_handles),
        frameon=False,
        bbox_to_anchor=(0.5, 0.97),
        columnspacing=0.25,
        handletextpad=0.05,
    )

plt.tight_layout()
# plt.subplots_adjust(top=0.95, bottom=0.22, left=0.12, right=0.98, wspace=0.45)
plt.subplots_adjust(
    top=0.85, bottom=0.08, left=0.23, right=0.98, wspace=0.45, hspace=0.35
)
plt.savefig("figures/" + save_name + ".png")
plt.savefig("figures/" + save_name + ".pdf")
