import os
import sys
import subprocess
from argparse import ArgumentParser

# Include the controller-helpers directory in the path.
from pathlib import Path
helpers_path = Path(__file__).parent / ".." / "controller-helpers"
sys.path.append(str(helpers_path.resolve()))

import appl_graphs
import common_utils


parser = ArgumentParser()
parser.add_argument("--app", type=str, required=True)
args = parser.parse_args()
app = args.app

match app:
    case "reservation":
        appl_graph = appl_graphs.hotel_reservation
    case "social":
        appl_graph = appl_graphs.social_network
    case _:
        raise ValueError("Unrecognized application")

services = appl_graph["services"]

# Set the CPU levels to the maximum.
for service in services:
    common_utils.change_resource_allocation(service, 800000)
