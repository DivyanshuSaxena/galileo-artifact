# Read the production workload traces and get the arrival rate traces.
# Arguments:
# 1: Path to the pkl file containing the top-X services.
# 2: Path to the directory containing the traces.
import os
import sys
import pickle

appls = sys.argv[1]
traces_dir = sys.argv[2]

# Read the pickle file and get the services of interest.
with open(appls, "rb") as f:
    data = pickle.load(f)
appls = data.keys()

appl_traces = {}

# Read all the files in the traces directory.
for file in os.listdir(traces_dir):
    if not file.endswith(".csv"):
        continue

    # Read the file line by line.
    print("Reading file", file)
    with open(os.path.join(traces_dir, file), "r") as f:
        num_lines = 0

        while True:
            line = f.readline()
            num_lines += 1
            if not line:
                break

            if num_lines % 5000000 == 0:
                print(f"Processed {num_lines} lines.")

            # Parse the line.
            callgraph = line.split(",")
            timestamp = callgraph[0]
            appl = callgraph[2]
            rpc_id = callgraph[3]

            if appl not in appls or rpc_id != "0":
                continue

            if appl not in appl_traces:
                appl_traces[appl] = []
            appl_traces[appl].append(timestamp)

    # Save a checkpoint of the appl_traces.
    with open("appl_traces.pkl", "wb") as f:
        pickle.dump(appl_traces, f)
    