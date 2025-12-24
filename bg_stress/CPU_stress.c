#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <math.h>
#include <unistd.h>
#include <time.h>

// Global variables for controlling threads and workload intensity
volatile int keep_running = 1;
volatile int utilization = 95; // Initial CPU utilization

void* adjust_intensity(void* arg) {
    const int base_utilization = 70;  // Average utilization
    const int amplitude = 20;         // Maximum deviation from base_utilization
    const double smooth_factor = 0.6; // Smoothing factor (0.0 - 1.0, higher = smoother)
    const int spike_chance = 5;      // 10% chance to generate a spike
    int random_offset;

    // const int base_utilization = 20;  // Average utilization
    // const int amplitude = 1;         // Maximum deviation from base_utilization
    // const double smooth_factor = 0.6; // Smoothing factor (0.0 - 1.0, higher = smoother)
    // const int spike_chance = 1;      // 10% chance to generate a spike
    srand(0); // Seed the random number generator

    while (keep_running) {
        sleep(10); // Adjust every second

        // Occasionally introduce a spike with a certain probability
        if (rand() % 100 < spike_chance) {
            // Generate a random spike above the typical range
            int high_utilization = base_utilization + amplitude + (rand() % 10); 

            int smoothed_high_utilization = (int)((1.0 - smooth_factor) * (high_utilization) + smooth_factor * utilization);
            utilization = smoothed_high_utilization;
            sleep(4);

            utilization = high_utilization; // Up to base + amplitude + 10

        } else {
            // Generate a random offset within the normal amplitude range
            random_offset = (rand() % (2 * amplitude + 1)) - amplitude;

            // Smoothly adjust the utilization
            utilization = (int)((1.0 - smooth_factor) * (base_utilization + random_offset) +
                                smooth_factor * utilization);
        }

        // Ensure utilization stays within bounds (allowing spikes to exceed normal range)
        if (utilization > 100) {
            utilization = 100; // Cap at 100%
        } else if (utilization < base_utilization - amplitude) {
            utilization = base_utilization - amplitude;
        }

        printf("Adjusted workload intensity to: %d\n", utilization);
    }

    return NULL;
}

// Function to perform CPU-intensive work
void* stress_cpu(void* arg) {
    const int period_us = 100000; // Total period in microseconds (100 ms)
    int busy_time = period_us * utilization / 100;
    int idle_time = period_us - busy_time;

    struct timespec start_time, current_time;
    long elapsed_time;

    while (1) {
        // Record the start time
        clock_gettime(CLOCK_MONOTONIC, &start_time);

        // Busy loop for 'busy_time' microseconds
        do {
            clock_gettime(CLOCK_MONOTONIC, &current_time);
            elapsed_time = (current_time.tv_sec - start_time.tv_sec) * 1000000L +
                           (current_time.tv_nsec - start_time.tv_nsec) / 1000L;
        } while (elapsed_time < busy_time);

        // Sleep for 'idle_time' microseconds
        usleep(idle_time);
        busy_time = period_us * utilization / 100;
        idle_time = period_us - busy_time;
    }
    return NULL;
}

int main(int argc, char* argv[]) {
    int num_threads;
    // int duration;

    // Parse command-line arguments
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <number_of_threads>\n", argv[0]);
        return EXIT_FAILURE;
    }

    num_threads = atoi(argv[1]);
    // duration = atoi(argv[2]);

    // Seed the random number generator
    srand(time(NULL));

    // Create threads
    pthread_t* threads = malloc(num_threads * sizeof(pthread_t));
    pthread_t intensity_thread;
    if (!threads) {
        perror("Failed to allocate memory for threads");
        return EXIT_FAILURE;
    }

    printf("Starting CPU stress test with %d threads...\n", num_threads);

    // Start the threads for stress testing
    for (int i = 0; i < num_threads; i++) {
        if (pthread_create(&threads[i], NULL, stress_cpu, NULL) != 0) {
            perror("Failed to create stress thread");
            free(threads);
            return EXIT_FAILURE;
        }
    }

    // Start the thread to adjust workload intensity
    if (pthread_create(&intensity_thread, NULL, adjust_intensity, NULL) != 0) {
        perror("Failed to create intensity adjustment thread");
        free(threads);
        return EXIT_FAILURE;
    }

    // Sleep for the specified duration
    while(1) {
        sleep(10);
    }

    // Stop the threads
    keep_running = 0;

    // Join all threads
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }

    pthread_join(intensity_thread, NULL);

    free(threads);
    printf("CPU stress test completed.\n");

    return EXIT_SUCCESS;
}
