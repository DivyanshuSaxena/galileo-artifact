"""
Compare logs of different controllers
Args:
    log_files (List[str]): List of paths to the log dirs.
"""

import sys
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from utils import *

# Check if the log files are provided.
if len(sys.argv) < 4:
    print(
        "Usage: python3 plot_controller_comparison.py <save_name> <log_dir1> <log_dir2>"
    )
    sys.exit(1)

save_name = sys.argv[1]
log_dirs = sys.argv[2:]
num_controllers = len(log_dirs)

if "reservation" in log_dirs[0]:
    type_names = ["user", "recommend", "search", "reserve"]
elif "social" in log_dirs[0]:
    type_names = ["compose_post", "read_home_timeline", "read_user_timeline"]
else:
    raise ValueError("Unrecognized application")

num_types = len(type_names)

# To plot: workload, goodput of all controllers
workload = []
all_goodputs = []
all_latencies = []
all_violations = []
final_violations = []

for _ in range(num_controllers):
    failed, goodput, violations, latencies = read_csv_files(
        log_dirs[_], type_names
    )

    # Controller workload is the sum of failed and goodput rates.
    controller_workload = np.add(failed, goodput)

    if len(workload) == 0:
        workload = controller_workload
    else:
        # Check if the workload is the same.
        min_len = min(len(workload), len(controller_workload))
        diff = np.subtract(workload[:min_len], controller_workload[:min_len])

        # Get entries that are more than 20.
        diff_larger = np.abs(diff) > 20
        if np.any(diff_larger):
            print("Workload is different for the controllers.")

            # Print the entries that are more than 20.
            print(diff[np.where(diff_larger)])

    all_goodputs.append(goodput)
    all_latencies.append(latencies)
    all_violations.append(violations)
    final_violations.append([100 * violations[i][-1] for i in range(num_types)])

    # Get average latency.
    print("Violations", final_violations[_])
    print(f"Average latency for {log_dirs[_]}: {np.average(latencies)}")

# Plot the workload and goodputs.
plt.rcParams["font.size"] = 18

colors = ["#D5E8D4", "#FFE6CC", "#F8CECC", "#CDD9E9", "#F1E6C6", "#DBCFE1"]
edge_colors = ["#82B366", "#D79B00", "#B85450", "#6C8EBF", "#D6B656", "#9673A6"]
styles = ["-", "--", "-.", "dotted", "-"]
markers = ["o", "P", "^", "s", "v", "^"]
hatches = ["/", "x", "|", "\\", "+", "-"]

controller_names = []
for i in range(num_controllers):
    # Extract controller name from the log_dir.
    run_name = log_dirs[i].split("/")[-1]
    if "galileo" in run_name:
        controller_name = "Galileo"
    elif "training" in run_name:
        controller_name = "TopFull"
        # MODIFY: Labels only for motivation plots.
        # if i == 0:
        #     controller_name = "No Stress"
        # else:
        #     controller_name = "Stress"
    else:
        controller_name = "TopFull Base"
    controller_names.append(controller_name)


#####################################
# Time series Goodput and Latencies #
#####################################
fig, axes = plt.subplots(2, 1, figsize=(5.2, 6))

# Plot the total workload.
axes[0].plot(workload, label="Applied Workload", color="black", linestyle=styles[0], linewidth=2)

# Plot the goodputs of all controllers.
for i in range(num_controllers):
    # Print average goodput.
    print(f"Average goodput for {controller_names[i]}: {np.average(all_goodputs[i])}")
    axes[0].plot(
        all_goodputs[i],
        label=controller_names[i],
        linewidth=3,
        color=edge_colors[i],
        linestyle=styles[i + 1],
    )

axes[0].axvline(x=11, color="red", linestyle="--", linewidth=2)
axes[0].set_ylabel("Request Rate (rps)")
axes[0].set_xlabel("Time (min)")
axes[0].legend(loc="upper center", bbox_to_anchor=(0.5, 1.65), ncol=1, frameon=False)

# Plot the latencies - average of all types.
# latency_avg = np.mean(all_latencies, axis=1)
# print(latency_avg.shape)

# Get the time-wise cumulative violations
violations_avg = np.mean(all_violations, axis=1)
cumulative_violations = np.cumsum(violations_avg, axis=1)
print(violations_avg.shape)
print(cumulative_violations.shape)

for i in range(num_controllers):
    axes[1].plot(
        cumulative_violations[i],
        label=controller_names[i],
        linewidth=3,
        color=edge_colors[i],
        linestyle=styles[i+1],
    )

axes[1].set_ylabel("Cumulative\nViolations (%)")
axes[1].set_xlabel("Time (min)")
axes[1].axvline(x=11, color="red", linestyle="--", linewidth=2)

plt.subplots_adjust(top=0.82, bottom=0.12, left=0.18, right=0.95)
plt.savefig(f"figures/{save_name}_comparison.png")
plt.savefig(f"figures/{save_name}_comparison.pdf")
plt.close()


#####################################
# Combined - Goodput and Violations #
#####################################
fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), gridspec_kw={"width_ratios": [3, 1]})

legend_patches = []
for i in range(num_controllers):
    legend_patches.append(
        mpatches.Patch(
            facecolor=colors[i],
            label=controller_names[i],
            hatch=hatches[i],
            edgecolor=edge_colors[i],
        )
    )

# Plot the violations.
xpos = np.arange(num_types) * num_controllers
for i in range(num_controllers):
    width=0.5
    pos = [x + i * width for x in xpos]
    axes[0].bar(
        pos,
        final_violations[i],
        width=width,
        color=colors[i],
        edgecolor=edge_colors[i],
        linewidth=2,
        label=controller_names[i],
        hatch=hatches[i]
    )
axes[0].set_xticks([(p + width * (num_controllers - 1) / 2) for p in xpos])
axes[0].set_xticklabels(type_names, rotation=15, ha="center")
axes[0].set_ylabel("SLO Violations (%age)")

# Plot the goodput as a boxplot.
pos = np.arange(num_controllers)
for i in range(num_controllers):
    bp = axes[1].boxplot(
        all_goodputs[i],
        positions=[pos[i]],
        widths=0.5,
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
axes[1].set_ylabel("Goodput (rps)")

# Add the legend.
fig.legend(handles=legend_patches, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 1.05))

# plt.tight_layout()
plt.subplots_adjust(top=0.85, bottom=0.22, left=0.12, right=0.98, wspace=0.45)
plt.savefig(f"figures/{save_name}.png")
plt.savefig(f"figures/{save_name}.pdf")

#####################################
# Bar plot - Goodput and Violations #
#####################################
fig = plt.figure(figsize=(8.4, 4.8))

# Plot the total workload.
plt.plot(workload, label="Applied Workload", color="black", linestyle=styles[0])

# Plot the goodputs of all controllers.
for i in range(num_controllers):
    # Print average goodput.
    print(f"Average goodput for {controller_names[i]}: {np.average(all_goodputs[i])}")
    plt.plot(
        all_goodputs[i],
        label=controller_names[i],
        linewidth=2,
        color=edge_colors[i],
        linestyle=styles[i + 1],
    )

plt.ylabel("Request Rate (rps)")
plt.xlabel("Time (min)")
plt.legend(loc="upper center", bbox_to_anchor=(0.5, 1.3), ncol=2, frameon=False)
plt.subplots_adjust(top=0.8, bottom=0.15, left=0.15, right=0.95)

plt.savefig(f"figures/goodput_{save_name}.png")
plt.close()

# Make another bar plot for the violations.
fig = plt.figure(figsize=(8.4, 4.8))

# Make a bar plot, with a set of bars for each request type.
xpos = np.arange(num_types) * num_controllers
for i in range(num_controllers):
    pos = [x + i * 0.8 for x in xpos]
    plt.bar(
        pos,
        final_violations[i],
        width=0.8,
        color=colors[i],
        edgecolor=edge_colors[i],
        linewidth=2,
        label=controller_names[i],
    )

plt.xticks([(p + 0.8 * (num_controllers - 1) / 2) for p in xpos], type_names)
plt.ylabel("SLO Violations (%age)")
plt.legend(loc="upper center", bbox_to_anchor=(0.45, 1.2), ncol=3, frameon=False)
plt.subplots_adjust(top=0.85, bottom=0.12, left=0.12, right=0.95)

plt.savefig(f"figures/violations_{save_name}.png")
plt.savefig(f"figures/violations_{save_name}.pdf")
plt.close()
