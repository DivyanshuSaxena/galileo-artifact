# Read the appl_traces.pkl file and construct the traces for arrival rates.
import os
import numpy
import pickle
import matplotlib.pyplot as plt

# Read the appl_traces.pkl file.
with open("appl_traces.pkl", "rb") as f:
    appl_traces = pickle.load(f)

MULTIPLIER = 5

num_appls = 0
num_interesting = 0
for appl, traces in appl_traces.items():
    sorted_traces = sorted([int(x) for x in traces])

    if len(sorted_traces) < 7200:
        continue

    num_appls += 1
    # print(f"Service: {appl}, Num traces: {len(traces)}")

    # Construct an array of invocations for 1-minute intervals.
    invocations = []
    start_time = int(sorted_traces[0] / (60 * 1000))
    end_time = int(sorted_traces[-1] / (60 * 1000))
    # print(f"Start time: {start_time}, End time: {end_time}")
    num_intervals = int(end_time - start_time) + 1
    for i in range(num_intervals):
        invocations.append(0)

    # Count the number of invocations in each interval.
    for trace in sorted_traces:
        bucket = int(trace / (60 * 1000)) - start_time
        invocations[bucket] += 1

    # Check if the invocation pattern for this application is interesting.
    # There are at least N time steps where the invocations change by more than 50%.
    interesting = False
    count = 0
    for i in range(5, len(invocations)):
        if abs(invocations[i] - invocations[i - 1]) > 0.5 * invocations[i - 1]:
            count += 1
            if count >= 20:
                interesting = True
                break
        
        # max_in_window = max(invocations[i - 5:i])
        # if abs(invocations[i] - max_in_window) < 0.1 * invocations[i]:
        #     count += 1
        #     if count >= 100:
        #         interesting = True

    if interesting:
        # Plot the arrival rate.
        num_interesting += 1

        # Get only the traces between 10-70 minutes.
        invocations = invocations[10:70]
        plt.plot(invocations, label=f"{num_interesting}")

        # Write to a rps.txt file.
        traces_dir = os.path.join(os.getcwd(), "traces")
        if not os.path.exists(traces_dir):
            os.makedirs(traces_dir)

        filename = f"{traces_dir}/rps{num_interesting}.txt"
        if MULTIPLIER > 1:
            filename = f"{traces_dir}/rps{num_interesting}x{MULTIPLIER}.txt"

        with open(filename, "w") as f:
            # Print statistics about invocations.
            mean = numpy.average(invocations)
            maximum = numpy.max(invocations)
            
            # Get the max consecutive increase in invocations.
            max_change = 0
            for i in range(1, len(invocations)):
                before = max(1, invocations[i - 1])
                after = max(1, invocations[i])
                max_change = max(max_change, max(before/after, after/before))

            print(f"{num_interesting}: max: {maximum} mean: {mean} max change: {max_change}")
            for i in invocations:
                for _ in range(60):
                    f.write(f"{MULTIPLIER*i}\n")

plt.xlabel("Time (minutes)", fontsize=20)
plt.ylabel("Arrival rate (rpm)", fontsize=20)
plt.legend()

print(f"Number of services: {num_appls}, interesting: {num_interesting}")
plt.savefig("arrival_rates.png")