"""
Initiate a socket client to send mesh type to the stats server.
Args:
    config (str): Path to the config file.
    MESH (str): The mesh type.
"""
import signal
import socket
import sys

# Gracefully end on interrupt
def signal_handler(sig, frame):
    for client_socket in client_sockets:
        # Send a message to the server to exit
        client_socket.send(b'EXIT')

    sys.exit(0)

if len(sys.argv) < 3:
    print('Usage: python stats_client.py <config> <mesh_type>')
    sys.exit(1)

# Read the config file
with open(sys.argv[1], 'r') as f:
    content = f.readlines()

server_addresses = [x.strip() for x in content]
print("Server addresses: ", server_addresses)

MESH = sys.argv[2]
client_sockets = []

for server_address in server_addresses:
    print("Connecting to stats server on {0}:2222".format(server_address))

    # Start a socket client to send the mesh type to the stats server
    client_socket = socket.socket()
    client_socket.connect((server_address, 2222))

    # Send the mesh type to the server
    client_socket.send(MESH.encode('utf-8'))

    # Wait for a response from the server
    data = client_socket.recv(1024)
    print("Received from stats server: ", data.decode('utf-8'))

    # Add the client socket to the list of client sockets
    client_sockets.append(client_socket)

# Register a signal handler
signal.signal(signal.SIGINT, signal_handler)

# Wait for the signal to exit
while True:
    pass