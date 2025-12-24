import os
import matplotlib.pyplot as plt

# Read traces
trace_dir = os.path.dirname(os.path.os.path.abspath(__file__)) + '/traces'
rpss = {}
for trace in os.listdir(trace_dir):
    if '_' not in trace:
        with open(os.path.join(trace_dir, trace), 'r') as trace_file:
            rps = [int(line) for line in trace_file.readlines()]
            rpss[trace] = rps

# Plot traces
for rps in range(1, 11):
    plt.plot(rpss[f'rps{rps}.txt'], label=rps)
plt.title('RPS Visualization')
plt.legend()
plt.savefig('rps')