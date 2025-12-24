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

import utils

if len(sys.argv) < 3:
    print(
        "Usage: python3 plot_controller_comparison.py <save_name> <if_stress (0/1)> <results_dir>"
    )
    sys.exit(1)

save_name = sys.argv[1]
use_stress = int(sys.argv[2]) == 1
results_dir = sys.argv[3]

if "reservation" in results_dir:
    app = "reservation"
    type_names = ["user", "recommend", "search", "reserve"]
elif "social" in results_dir:
    app = "social"
    type_names = ["compose_post", "read_home_timeline", "read_user_timeline"]
else:
    raise ValueError("Unrecognized application")

num_types = len(type_names)

controllers = []

# Read the controller logs and store in a dataframe.
data = []

drop_rps = [1, 2]

# Get all relevant log dirs.
for d in os.listdir(results_dir):
    if not os.path.isdir(os.path.join(results_dir, d)):
        continue

    # Extract rps value: Find rpsX in the string.
    rps = None
    for part in d.split("-"):
        if part.startswith("rps"):
            rps = int(part[3:])
            break
    if rps is None:
        raise ValueError("Could not find rps value in directory name: " + d)

    if rps in drop_rps:
        continue

    # Extract controller name: part of the dir before rpsX
    controller = d.split("-rps")[0]
    if controller not in controllers:
        controllers.append(controller)

    # Extract stress or normal: part of the dir after -rpsX-
    is_stress = d.split(f"-rps{rps}-")[-1].split("-")[0] == "stress"
    if use_stress and not is_stress:
        continue
    if not use_stress and is_stress:
        continue

    log_dir = os.path.join(results_dir, d)

    # Get the directory creation timestamp
    stat_info = os.stat(log_dir)
    creation_time = stat_info.st_ctime

    # Check if total.csv exists in the log_dir
    if not os.path.exists(os.path.join(log_dir, "total.csv")):
        print(f"Warning: total.csv not found in {log_dir}. Skipping this directory.")
        continue

    failed, goodput, violations, latencies = utils.read_csv_files(log_dir, type_names)

    if numpy.isnan(numpy.mean(goodput)):
        print("Error: ", log_dir, goodput, violations)
        continue

    row = {
        "rps": rps,
        "controller": controller,
        "dir": log_dir,
        "average_goodput": numpy.mean(goodput),
        "peak_goodput": numpy.max(goodput),
        "creation_time": creation_time,
    }
    for j in range(num_types):
        row[f"violation_type{j+1}"] = 100 * max(1e-2, violations[j][-1])
    data.append(row)

df = pd.DataFrame(data)

# Get the number of controllers.
num_controllers = len(controllers)

# Sort controllers in the following order: none, galileo, galileo-shield
controllers.sort(key=lambda x: (x != "none", x != "galileo", x))

num_entries = len(df)

# If any (controller, rps) pair has multiple entries, print the violations, average goodput and peak goodput for each entry.
duplicates = df[df.duplicated(subset=["controller", "rps"], keep=False)]
if not duplicates.empty:
    print("Found duplicate entries for the following (controller, rps) pairs:")
    for _, row in duplicates.iterrows():
        if "none" in row["controller"]:
            continue
        print(
            f"Controller: {row['controller']}, RPS: {row['rps']}, Violations: {[row[f'violation_type{j+1}'] for j in range(num_types)]}, Average Goodput: {row['average_goodput']}, Peak Goodput: {row['peak_goodput']}, Dir: {row['dir']}"
        )

# Keep only the latest (controller, rps) entry in data
df = df.sort_values("creation_time").drop_duplicates(
    subset=["controller", "rps"], keep="last"
)

new_num_entries = len(df)
print(f"Dropped {num_entries - new_num_entries} duplicate entries.")

# Print the number of unique rps values.
num_rps = len(df["rps"].unique())
print("Number of unique rps values:", num_rps)

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
    "none": "TopFull",
    "galileo": "Galileo w/o Shield",
    "galileo-shield": "Galileo",
}
legend_handles = [
    Line2D(
        [0],
        [0],
        marker=markers[i],
        color="w",
        label=legend_labels.get(controllers[i], controllers[i]),
        markerfacecolor=edge_colors[i],
        markeredgecolor="black",
        markersize=12,
        linewidth=0,
    )
    for i in range(num_controllers)
]

xpos = numpy.arange(num_types) / 2 * num_controllers
width = 0.25

# Add improvement in violations compared to the first controller.
violation_columns = [col for col in df.columns if col.startswith("violation_type")]
base_violations = df[df["controller"] == "none"][violation_columns + ["rps"]]
# print("Base Violations:", base_violations)

improved_violations = []
for i in range(num_controllers):
    # Get the violations for this controller.
    controller_violations = df[df["controller"] == controllers[i]][
        violation_columns + ["rps"]
    ]
    for rps_val in controller_violations["rps"].unique():
        print(f"Goodputs for {controllers[i]} at rps {rps_val}:")
        peak_goodputs = df[
            (df["controller"] == controllers[i]) & (df["rps"] == rps_val)
        ]["peak_goodput"].values
        avg_goodputs = df[
            (df["controller"] == controllers[i]) & (df["rps"] == rps_val)
        ]["average_goodput"].values
        print(f"  Peak: {peak_goodputs}")
        print(f"  Average: {avg_goodputs}")

        print(f"Violations for {controllers[i]} at rps {rps_val}:")
        for j in range(num_types):
            vals = controller_violations[controller_violations["rps"] == rps_val][
                f"violation_type{j+1}"
            ].values
            print(f"  Type {j+1}: {vals}")

    if controllers[i] != "none":
        for j in range(num_types):
            # Compute improvement per rps
            improvements = []
            for rps_val in controller_violations["rps"].unique():
                base_vals = base_violations[base_violations["rps"] == rps_val][
                    f"violation_type{j+1}"
                ].values
                improved_vals = controller_violations[
                    controller_violations["rps"] == rps_val
                ][f"violation_type{j+1}"].values
                if len(base_vals) == 0 or len(improved_vals) == 0:
                    continue
                base_mean = numpy.mean(base_vals)
                improved_mean = numpy.mean(improved_vals)
                print(f"Req Type {j+1} RPS {rps_val} Improvement: {base_mean - improved_mean}")
                improvements.append(
                    base_mean - improved_mean
                )
            req_type_improvement = numpy.mean(improvements) if improvements else 0
            improved_violations.append(req_type_improvement)

    # Get the average violations for this controller.
    controller_violations = df[df["controller"] == controllers[i]][violation_columns]
    print(f"Average Violations for {controllers[i]}: {controller_violations.mean().values}")

    pos = [x + i * (width + 0.1) for x in xpos]
    # Convert boxplot to scatter plot for SLO violations using controller_violations
    for j in range(num_types):
        y_values = controller_violations[f"violation_type{j+1}"].values
        x_value = pos[j]
        # Plot each value as a scatter point
        axes[0].scatter(
            [x_value] * len(y_values),
            y_values,
            color=edge_colors[i],
            marker=markers[i],
            s=140,
            label=legend_labels.get(controllers[i], controllers[i]),
            alpha=0.5,
            edgecolors="black",
            linewidths=1.5,
        )
axes[0].set_xticks([(p + width * (num_controllers - 1) / 2) for p in xpos])
axes[0].set_xticklabels([f"RT {j}" for j in range(1, num_types + 1)])
# axes[0].set_xlabel("Request Types", labelpad=2)
# axes[0].set_yscale("log")
# axes[0].set_yticks([1, 10, 50])
# axes[0].set_yticklabels([1, 10, 50])
axes[0].set_ylabel("SLO Violations\n(%)")

# Print the SLO violation improvements.
print("SLO Violation Improvements:", improved_violations, numpy.mean(improved_violations))

# Prepare goodput data from the dataframe
avg_goodputs = {
    controller: df[df["controller"] == controller]["average_goodput"].values
    for controller in controllers
}
peak_goodputs = {
    controller: df[df["controller"] == controller]["peak_goodput"].values
    for controller in controllers
}

base_avg_goodput = numpy.mean(avg_goodputs[controllers[0]])
base_peak_goodput = numpy.mean(peak_goodputs[controllers[0]])
improved_avg_goodputs = []
improved_peak_goodputs = []

pos = numpy.arange(0, num_controllers / 2, 0.5)
for i in range(num_controllers):
    if i != 0:
        improved_avg_goodputs.append(
            100
            * (numpy.mean(avg_goodputs[controllers[i]]) - base_avg_goodput)
            / base_avg_goodput
        )
        improved_peak_goodputs.append(
            100
            * (numpy.mean(peak_goodputs[controllers[i]]) - base_peak_goodput)
            / base_peak_goodput
        )

    # Convert boxplot to scatter plot for average goodput
    y_values = avg_goodputs[controllers[i]]
    x_value = pos[i]
    axes[1].scatter(
        [x_value] * len(y_values),
        y_values,
        color=edge_colors[i],
        marker=markers[i],
        s=140,
        label=legend_labels.get(controllers[i], controllers[i]),
        alpha=0.5,
        edgecolors="black",
        linewidths=1.5,
    )

    # Convert boxplot to scatter plot for peak goodput
    y_values = peak_goodputs[controllers[i]]
    x_value = pos[i]
    axes[2].scatter(
        [x_value] * len(y_values),
        y_values,
        color=edge_colors[i],
        marker=markers[i],
        s=140,
        label=legend_labels.get(controllers[i], controllers[i]),
        alpha=0.5,
        edgecolors="black",
        linewidths=1.5,
    )

# Print the goodput improvements.
print("Avg Goodput Improvements:", improved_avg_goodputs)
print("Peak Goodput Improvements:", improved_peak_goodputs)

axes[1].set_xticks([])
axes[1].set_xticklabels([])
axes[1].set_xlim(-0.5, pos[-1] + 0.5)
axes[1].set_xlabel("Average")
axes[1].set_ylabel("Goodput\n(req/s)")
# axes[1].set_yscale("log")
axes[1].set_yticks([0, 150, 300, 450])
axes[1].set_yticklabels([0, 150, 300, 450])
# axes[1].set_yticks([1, 10])
# axes[1].set_yticklabels([1, 10])
axes[1].tick_params(axis="y", which="minor", labelleft=False)

axes[2].set_xticks([])
axes[2].set_xticklabels([])
axes[2].set_xlim(-0.5, pos[-1] + 0.5)
axes[2].set_xlabel("Peak")
if app == "reservation":
    axes[2].set_yticks([300, 600, 900, 1200])
    axes[2].set_yticklabels([300, 600, 900, 1200])
elif app == "social":
    axes[2].set_yticks([150, 300, 450, 600])
    axes[2].set_yticklabels([150, 300, 450, 600])
    axes[2].set_ylim(0, 600)
# axes[2].set_yticks([1, 10])
# axes[2].set_yticklabels([1, 10])
axes[2].tick_params(axis="y", which="minor", labelleft=False)

# Separate legend handles based on label length
one_word_handles = []
multi_word_handles = []
for handle in legend_handles:
    label = handle.get_label()
    if len(label.split()) == 1:
        one_word_handles.append(handle)
    else:
        multi_word_handles.append(handle)

if one_word_handles:
    fig.legend(
        handles=one_word_handles,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 1.05),
        columnspacing=0.5,
        handletextpad=0.05,
    )
if multi_word_handles:
    fig.legend(
        handles=multi_word_handles,
        loc="upper center",
        ncol=1,
        frameon=False,
        bbox_to_anchor=(0.5, 0.97),
        columnspacing=0.5,
        handletextpad=0.05,
    )

plt.tight_layout()
plt.subplots_adjust(
    top=0.85, bottom=0.08, left=0.26, right=0.98, wspace=0.65, hspace=0.35
)
plt.savefig("figures/" + save_name + ".png")
plt.savefig("figures/" + save_name + ".pdf")
