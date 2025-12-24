# Utility functions for the plotting scripts.

def stof(s):
    f = 0
    try:
        f = float(s)
    except:
        print("FAILED TO CONVERT ", s)
    return f

def read_controller_log(log_file, request_types):
    # Read the logs from the file.
    timestamps = []
    workloads = []
    allocations = []
    certificates = []
    violations = []

    has_certificates = False
    if "galileo" in log_file or "atplusplus" in log_file:
        has_certificates = True

    num_types = len(request_types)

    latencies_50p = []
    latencies_99p = []
    for _ in range(num_types):
        latencies_50p.append([])
        latencies_99p.append([])

    base_time = None
    with open(log_file, "r") as f:
        for line in f:
            timestamp = float(line.split(",")[0])           # Timestamp is the number before the first comma.
            workload = line.split("[")[1].split("]")[0]     # Workload is an array between the first [].
            latency = line.split("[")[2].split("]")[0]      # Latencies is an array between the second [].
            violation = line.split("[")[3].split("]")[0]   # Violations is an array between the third [].
            allocation = line.split("{")[1].split("}")[0]   # Allocations is a dict between the first {}.
            
            if has_certificates:
                certificate = line.split("[")[-1].split("]")[0]

            if base_time is None:
                base_time = timestamp
            timestamps.append(round(timestamp - base_time))

            workload = [float(i) for i in workload.split(", ")]
            workloads.append(workload)

            # Latency is a list of tuples.
            latency = [[float(x.replace(')', '').replace('(', '')) for x in tup.split(", ")] for tup in latency.split("), ")]
            for i in range(num_types):
                latencies_50p[i].append(latency[i][0])
                latencies_99p[i].append(latency[i][1])
            
            violation = [stof(i) for i in violation.split(", ")]
            violations.append(violation)

            allocation = {i.split(": ")[0][1:-1]: float(i.split(": ")[1]) for i in allocation.split(", ")}
            allocations.append(allocation)

            if has_certificates:
                certificate = [float(i) for i in certificate.split(", ")]
                certificates.append(certificate)

            # print(f"Timestamp: {timestamp}, Workload: {workload}, Latencies: {latency}, Allocations: {allocation}")

    return timestamps, workloads, latencies_50p, latencies_99p, allocations, violations, certificates