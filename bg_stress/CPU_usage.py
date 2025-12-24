import psutil
import time
import csv
import matplotlib.pyplot as plt
from threading import Thread, Event
from queue import Queue
import argparse  # Added for argument parsing

def monitor_total_cpu_usage(queue, interval, stop_event):
    """Monitors total CPU usage and sends data to the queue."""
    start_time = time.time()
    while not stop_event.is_set():
        elapsed_time = time.time() - start_time
        cpu_usage = psutil.cpu_percent(interval=interval)
        queue.put((elapsed_time, cpu_usage))

def plot_total_cpu_usage(queue, stop_event, csv_file):
    """Plots CPU usage data dynamically from the queue and logs to CSV."""
    plt.ion()  # Turn on interactive mode
    fig, ax = plt.subplots()
    ax.set_title("Total CPU Usage Over Time")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Total CPU Usage (%)")
    ax.set_xlim(0, 10)  # Start with a 10-second window
    ax.set_ylim(0, 100)

    times = []
    usages = []
    line, = ax.plot([], [], label="Total CPU Usage")
    ax.legend()

    # Open CSV file for writing
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Time (s)", "CPU Usage (%)"])  # Write header

        while not stop_event.is_set() or not queue.empty():
            while not queue.empty():
                elapsed_time, cpu_usage = queue.get()
                times.append(elapsed_time)
                usages.append(cpu_usage)

                # Log data to CSV
                writer.writerow([elapsed_time, cpu_usage])

            if times:
                # Update the plot
                line.set_xdata(times)
                line.set_ydata(usages)
                ax.set_xlim(0, times[-1] + 1)
                ax.figure.canvas.draw()
                ax.figure.canvas.flush_events()
            time.sleep(0.5)

def dump_csv(queue, stop_event, csv_file):
    """Dumps CPU usage data from the queue to CSV without plotting."""
    # Open CSV file for writing
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Time (s)", "CPU Usage (%)"])  # Write header

        while not stop_event.is_set() or not queue.empty():
            while not queue.empty():
                elapsed_time, cpu_usage = queue.get()

                # Log data to CSV
                writer.writerow([elapsed_time, cpu_usage])
            file.flush()  # Flush to write to disk immediately
            time.sleep(0.5)

if __name__ == "__main__":
    # Argument parser to handle command-line arguments
    parser = argparse.ArgumentParser(description='Monitor and plot CPU usage.')
    parser.add_argument('--no-plot', action='store_true', help='Disable plotting and only dump to CSV.')
    args = parser.parse_args()

    monitoring_interval = 1  # Seconds
    stop_event = Event()
    data_queue = Queue()
    csv_filename = "cpu_usage_data.csv"

    print("Starting total CPU usage monitoring. Press Ctrl+C to stop.")
    try:
        # Start monitoring in a background thread
        monitor_thread = Thread(target=monitor_total_cpu_usage, args=(data_queue, monitoring_interval, stop_event))
        monitor_thread.start()

        if args.no_plot:
            # Only dump to CSV
            dump_csv(data_queue, stop_event, csv_filename)
        else:
            # Plot and log data in the main thread
            plot_total_cpu_usage(data_queue, stop_event, csv_filename)
    except KeyboardInterrupt:
        print("Stopping CPU monitoring...")
        stop_event.set()
        monitor_thread.join()
    print(f"CPU usage data saved to {csv_filename}")
