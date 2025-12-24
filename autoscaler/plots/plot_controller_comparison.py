"""
Read the given controller logs and plot their comparison plots.
Args:
    log_dirs (list): List of paths to the log dirs
"""

import os
import sys
import numpy
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

import utils

# Include the controller-helpers directory in the path.
from pathlib import Path

helpers_path = Path(__file__).parent / ".." / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs

if len(sys.argv) < 3:
    print(
        "Usage: python3 plot_controller_comparison.py <save_name> <type (latency/violations/timeseries)> <log_dirs>"
    )
    sys.exit(1)

save_name = sys.argv[1]
to_plot = sys.argv[2]
log_dirs = sys.argv[3:]

if to_plot not in ["latency", "violations", "timeseries"]:
    print("Type should be either 'latency', 'violations' or 'timeseries'.")
    sys.exit(1)

# Get the .log files from the log directories.
log_files = []
for log_dir in log_dirs:
    log_files.extend(
        [
            os.path.join(log_dir, log_file)
            for log_file in os.listdir(log_dir)
            if log_file.endswith(".log") and log_file.startswith("autothrottle")
        ]
    )
print(f"Log paths: {log_files}")

if "reservation" in log_dirs[0]:
    type_names = appl_graphs.hotel_reservation["request_types"]["by_type"]
elif "social" in log_dirs[0]:
    type_names = appl_graphs.social_network["request_types"]["by_type"]
else:
    raise ValueError("Unrecognized application")

num_types = len(type_names)
num_controllers = len(log_files)

labels = []
for i in range(num_controllers):
    # Get the label between -rps and the / before -rps.
    label = log_dirs[i].split("-rps")[0].split("/")[-1]
    print(f"Label: {label}")
    labels.append(label)

# Read the controller logs.
timestamps = []
workloads = []
allocations = []
latencies_99p = []
certificates = []
violations = []

for log_file in log_files:
    ts, wl, _, lat_99p, alloc, v, c = utils.read_controller_log(log_file, type_names)

    timestamps.append(ts)
    latencies_99p.append(lat_99p)
    certificates.append(c)

    # Process workload and allocations.
    workloads.append([sum(w) for w in wl])
    allocations.append([16 * sum(a.values()) for a in alloc])

    # Since the violations are incrementally updteed, just get the last value.
    j = 1
    while len(v[-j]) != num_types:
        j += 1
    violations.append([100 * v[-j][i] for i in range(num_types)])

avg_alloc = [numpy.mean(a) for a in allocations]
print(
    list(
        zip(
            labels,
            numpy.average(violations, axis=1),
            numpy.min(violations, axis=1),
            numpy.max(violations, axis=1),
            avg_alloc,
            violations,
        )
    )
)
print(f"Average Allocations Comparison: {(1 - 1/(avg_alloc[1] / avg_alloc[0])) * 100}%")

# Plot the graphs.
plt.rcParams["font.size"] = 20

colors = ["#D5E8D4", "#FFE6CC", "#F8CECC", "#CDD9E9", "#F1E6C6", "#DBCFE1"]
edge_colors = ["#82B366", "#D79B00", "#B85450", "#6C8EBF", "#D6B656", "#9673A6"]
markers = ["o", "P", "^", "s", "v", "^"]
styles = ["--", "-.", "-", ":", "-", "--"]
hatches = ["/", "x", "|", "\\", "+", "-"]

legend_labels = {
    "galileo": "Galileo",
    "galileo-d0.5": "Galileod 0.5",
    "autothrottle": "Autothrottle",
    "galileo-shield": "Galileo",
    "galileo-sigmoid": "Galileo w/o Shield",
}
legend_patches = []
for i in range(num_controllers):
    legend_patches.append(
        mpatches.Patch(
            facecolor=colors[i],
            label=labels[i],
            hatch=hatches[i],
            edgecolor=edge_colors[i],
            linewidth=2,
            linestyle=styles[i],
        )
    )

# Plot the workload.
# for i in range(num_controllers):
#     axes[0].plot(timestamps[i], workloads[i], linewidth=2, label=labels[i], color=edge_colors[i])
# axes[0].set_ylabel("Workload")
# axes[0].set_xlabel("Time (s)")

xpos = numpy.arange(num_types) * num_controllers
plot_allocations = False

# Make a box plot for latencies or a bar plot for violations.
if to_plot == "latency":
    fig, axes = plt.subplots(
        1, 2, figsize=(10, 5), gridspec_kw={"width_ratios": [3, 1]}
    )
    plot_allocations = True

    # Plot the 99th percentile latencies - make a box plot.
    for i in range(num_controllers):
        pos = [x + i * 0.8 for x in xpos]
        axes[0].boxplot(
            latencies_99p[i],
            positions=pos,
            widths=0.6,
            whis=[1, 99],
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor=colors[i], color=edge_colors[i]),
            whiskerprops=dict(color=edge_colors[i]),
            capprops=dict(color=edge_colors[i]),
            medianprops=dict(color=edge_colors[i], linewidth=2),
        )
    axes[0].axhline(y=100, color="b", linestyle="dashed", linewidth=2)
    axes[0].set_xticks([(p + 0.8 * (num_controllers - 1) / 2) for p in xpos])
    axes[0].set_xticklabels(type_names)
    axes[0].set_yscale("log")
    axes[0].set_ylabel("99th Percentile Latency (ms)")
elif to_plot == "timeseries":
    fig, axes = plt.subplots(
        3, 1, figsize=(5.2, 6), gridspec_kw={"height_ratios": [1, 1, 1]}
    )

    # Needed for deep-dive plots -- trim the x-axis between 20-35 mins.
    xlims = (58, 80)  # (0, -1) for full

    # Plot allocations -- should be skewed by 1
    for i in range(num_controllers):
        axes[0].plot(
            numpy.clip(allocations[i], None, 64)[xlims[0] - 2 : xlims[1] - 2],
            color=edge_colors[i],
            linewidth=3,
            linestyle=styles[i],
        )
    axes[0].set_ylabel("CPU Core\nAllocations", labelpad=12)
    axes[0].set_yticks([3, 4, 5, 6])

    # Plot latencies
    for i in range(num_controllers):
        axes[1].plot(
            numpy.mean(latencies_99p[i], axis=0)[xlims[0] : xlims[1]],
            color=edge_colors[i],
            linewidth=3,
            linestyle=styles[i],
        )
        # if certificates[i]:
        #     axes[1].plot(numpy.mean(certificates[i], axis=1), color=edge_colors[i], linestyle=styles[0])

    axes[1].axhline(y=100, color="b", linestyle="dashed", linewidth=2)
    axes[1].set_ylabel("Latencies", labelpad=12)
    axes[1].set_yticks([0, 150, 300])
    # axes[1].set_ylabel("Latencies\n& Certificates", labelpad=2)

    # Plot certs
    for i in range(num_controllers):
        if certificates[i]:
            axes[2].plot(
                numpy.mean(certificates[i], axis=1)[xlims[0] : xlims[1]],
                color=edge_colors[i],
                linewidth=3,
                linestyle=styles[i],
            )
    axes[2].set_ylabel("Certificates", labelpad=12)
    axes[2].set_yticks([0, 150, 300])
    axes[2].axhline(y=100, color="b", linestyle="dashed", linewidth=2)

    vlines = [3.5]  # [(31.95, 1), (38, 0)]
    for ax in axes:
        ax.set_xticks(range(0, xlims[1] - xlims[0], (xlims[1] - xlims[0]) // 6))
        ax.set_xticklabels([f"{int(x//2)}" for x in ax.get_xticks()])
        for vline in vlines:
            ax.axvline(x=vline * 2, color="r", linestyle="dashed", linewidth=2)

    axes[-1].set_xlabel("Time (m)")

    # Update legend
    legend_patches = [
        plt.Line2D(
            [0],
            [0],
            color=edge_colors[i],
            linestyle=styles[i],
            label=legend_labels.get(labels[i], labels[i]),
            linewidth=2,
        )
        for i in range(num_controllers)
    ]
elif to_plot == "violations":
    fig, axes = plt.subplots(
        1, 2, figsize=(10, 5), gridspec_kw={"width_ratios": [3, 1]}
    )
    plot_allocations = True

    # Plot the violations - make a bar plot.
    width = 0.5
    for i in range(num_controllers):
        pos = [x + i * width for x in xpos]
        axes[0].bar(
            pos,
            violations[i],
            width=width,
            color=colors[i],
            edgecolor=edge_colors[i],
            linewidth=2,
            hatch=hatches[i],
        )
    axes[0].set_xticks([(p + width * (num_controllers - 1) / 2) for p in xpos])
    axes[0].set_xticklabels(type_names, rotation=15, ha="center")
    axes[0].set_ylabel("SLO Violations (%age)")

if plot_allocations:
    # Plot the allocations.
    # for i in range(num_controllers):
    #     axes[1].plot(timestamps[i], allocations[i], linewidth=2, label=f"Controller {i}", color=edge_colors[i])
    pos = numpy.arange(num_controllers)

    for i in range(num_controllers):
        capped_allocations = numpy.clip(allocations[i], None, 64)
        bp = axes[1].boxplot(
            capped_allocations,
            positions=[pos[i]],
            widths=0.6,
            showfliers=False,
            patch_artist=True,
            boxprops=dict(facecolor=colors[i], color=edge_colors[i]),
            whiskerprops=dict(color=edge_colors[i]),
            capprops=dict(color=edge_colors[i]),
            medianprops=dict(color=edge_colors[i], linewidth=2),
        )
        for box in bp["boxes"]:
            box.set(hatch=hatches[i])

    # Remove the x-axis ticks and labels.
    axes[1].set_xticks([])
    axes[1].set_yticks([0, 2, 4, 6])  # MODIFY: As per the limits.
    axes[1].set_ylabel("CPU Core\nAllocations")

# Add the legend.
# Separate labels by word count
one_word_labels = []
one_word_handles = []
multi_word_labels = []
multi_word_handles = []

for i, patch in enumerate(legend_patches):
    label = labels[i]
    display_label = legend_labels.get(label, label)
    if len(display_label.split()) == 1:
        one_word_labels.append(display_label)
        one_word_handles.append(patch)
    else:
        multi_word_labels.append(display_label)
        multi_word_handles.append(patch)

if one_word_handles:
    fig.legend(
        handles=one_word_handles,
        labels=one_word_labels,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 1.035),
        columnspacing=0.5,
        handlelength=1.5
    )
if multi_word_handles:
    fig.legend(
        handles=multi_word_handles,
        labels=multi_word_labels,
        loc="upper center",
        ncol=1,
        frameon=False,
        bbox_to_anchor=(0.5, 0.98),
        handlelength=1.5
    )

plt.tight_layout()
plt.subplots_adjust(
    top=0.87, bottom=0.12, left=0.22, right=0.98, wspace=0.55, hspace=0.3
)
plt.savefig("figures/" + save_name + ".png")
plt.savefig("figures/" + save_name + ".pdf")
