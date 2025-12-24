# Utility functions for the plotting scripts.

def read_csv_files(log_dir, request_types):
    # Read the logs from the logs directory.
    total_failed = []
    total_goodput = []

    violations = []
    latencies = []
    
    # Total stats are in `total.csv`.
    with open(f"{log_dir}/total.csv", "r") as f:
        for line in f:
            if "RPS" in line:
                continue
            total_failed.append(float(line.split(",")[1]))
            total_goodput.append(float(line.split(",")[2]))

    # Read the logs for each request type.
    for request_type in request_types:
        violation = 0
        type_violations = []
        with open(f"{log_dir}/{request_type}.csv", "r") as f:
            latencies.append([])
            for line in f:
                if "RPS" in line:
                    continue
                latencies[-1].append(float(line.split(",")[4]))
                violation = float(line.split(",")[5])
                type_violations.append(violation)
        violations.append(type_violations)

    return total_failed, total_goodput, violations, latencies