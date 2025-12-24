"""
Wait for a connection from the stats client and start the stats script cpumem_stats.
Args:
    host (str): The IP address of the stats server.
"""
import os
import sys
import time
import signal
import socket
import subprocess


def start_server(host):
    # Start a socket server to listen for connections from the stats client
    port = 2222

    # Bind the socket to the host and port
    print("Starting stats server on {0}:{1}".format(host, port))
    server_socket = socket.socket()
    server_socket.bind((host, port))

    # Wait for a connection from the stats client
    server_socket.listen(1)
    conn, addr = server_socket.accept()
    print("Connection from: " + str(addr))

    while True:
        # Receive the mesh type from the client
        try:
            data = conn.recv(1024)
        except socket.error:
            # No data received -- continue
            time.sleep(2)
            continue

        if not data:
            # No data received -- continue
            time.sleep(2)
            continue

        # Decode the data
        data = data.decode('utf-8')

        # If data is not 'exit', start the stats script
        if data != 'EXIT':
            # Start the stats script
            print("Starting stats script with arg: {0}".format(data))

            # Get directory of the stats script
            script_dir = os.path.dirname(os.path.realpath(__file__))
            stats_script = os.path.join(script_dir, 'cpumem_stats.py')

            process = subprocess.Popen(['python', stats_script, data])

            # Send a message to the client that the stats script has started
            conn.send(b'STARTED')
        else:
            # Kill process with SIGINT and exit
            process.send_signal(signal.SIGINT)
            break

    # Close the connection
    conn.close()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python stats_server.py <host>')
        sys.exit(1)

    print("Starting stats server on {0}".format(sys.argv[1])) 

    host = sys.argv[1]
    start_server(host)