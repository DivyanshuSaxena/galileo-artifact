import os
import sys
import grpc
import time
import pickle
import requests
import datetime
from google.protobuf.timestamp_pb2 import Timestamp

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)) + "/proto_gen_python")
from proto_gen_python import query_pb2, query_pb2_grpc


def json_query_service():
    URL = "http://localhost:16686/api"
    values = requests.get(URL + "/services").json()["data"]
    print(values)


def create_grpc_channel(ip_address):
    channel = grpc.insecure_channel(ip_address + ":16685")
    return channel


def create_grpc_stub(channel):
    stub = query_pb2_grpc.QueryServiceStub(channel)
    return stub


def grpc_query_service(stub):
    response = stub.GetServices(query_pb2.GetServicesRequest())
    return response.services


# Construct trace_dict from a list of spans
# trace: List of different spans
# trace_id: ID of the trace
# Returns a dictionary with the following format:
# {
#   'trace_id': <trace_id>,
#   'spans': {
#       <service_name>: <duration>
#   }
# }
def construct_trace(trace, trace_id):
    trace_dict = {"trace_id": trace_id, "spans": {}}

    # NOTE: Currently not subtracting latencies
    # # Sort trace by durations
    # trace.sort(key=lambda x: x[2])

    # # Subtract child spans from parent spans
    # for i in range(len(trace)):
    #     span_details = trace[i]
    #     parent_span = span_details[3]
    #     search_limit = i

    #     # Find parent service and subtract duration
    #     flag = False
    #     while parent_span != None:
    #         for j in range(search_limit, len(trace)):
    #             if trace[j][0] == parent_span:
    #                 trace[j][2] -= span_details[2]
    #                 parent_span = trace[j][3]
    #                 search_limit = j
    #                 break

    # Construct trace dict
    for span_details in trace:
        service = span_details[1]
        if service not in trace_dict["spans"]:
            trace_dict["spans"][service] = span_details[2]
        else:
            trace_dict["spans"][service] = max(
                trace_dict["spans"][service], span_details[2]
            )

    return trace_dict


# Query traces of a service
# exp_start_time: time when the experiment started
# service_name: name of the service
# log: whether to log the traces
# trace_name: name of the trace
# num_samples: number of samples to query
# period: period for which we need to monitor the traces
#
# If the num_samples is set, collect until the number of samples is reached.
# If the period is set, collect for that period.
# 
# Returns a list of traces containing the service name, in the following format:
# [
#   {
#       'trace_id': <trace_id>,
#       'spans': {
#           <service_name>: <duration>...
#       }
#   }
# ]
def grpc_query_traces(
    stub,
    exp_start_time,
    service_name="compose-post-service",
    log=False,
    trace_name="compose-post",
    num_samples=100,
    period=None,
):
    use_period = False
    monitoring_period = 30
    if period is not None:
        monitoring_period = period
        use_period = True

    collected_samples = 0
    
    # Append all traces in a list
    all_traces = []
    collection_start_time = exp_start_time
    while collected_samples < num_samples:
        # First sleep for monitoring_period seconds to allow enough traces to be collected.
        now = datetime.datetime.now()
        if (now - collection_start_time).total_seconds() < monitoring_period:
            print("Sleeping for {0} seconds".format(monitoring_period), flush=True)
            time.sleep(monitoring_period)

        start_time = Timestamp(seconds=int(collection_start_time.timestamp()))
        print("Start time: ", start_time)

        # Construct the TraceQueryParameters object
        trace_query_parameters = query_pb2.TraceQueryParameters(
            service_name=service_name,
            start_time_min=start_time,
            search_depth=24000,
        )

        # Construct the FindTracesRequest object
        find_traces_request = query_pb2.FindTracesRequest(query=trace_query_parameters)

        print(
            "Querying traces for service {0} for monitoring period {1}".format(
                service_name, monitoring_period
            )
        )
        stream_responses = stub.FindTraces(find_traces_request)

        # Construct traces from the stream responses
        curr_trace_id = None
        trace = []  # List of span details
        svc_count = {}  # Count how many times a service was present in the trace
        for response in stream_responses:
            for span in response.spans:
                # print(span.operation_name,
                #       span.trace_id.hex()[12:],
                #       span.duration.nanos / 1000, span.process.service_name,
                #       span.span_id.hex())

                # Add trace ID or check if the span is of the same trace or not.
                if curr_trace_id is None:
                    curr_trace_id = span.trace_id.hex()
                else:
                    if curr_trace_id != span.trace_id.hex():
                        trace_dict = construct_trace(trace, curr_trace_id)
                        for svc, _ in trace_dict["spans"].items():
                            if svc not in svc_count:
                                svc_count[svc] = 1
                            else:
                                svc_count[svc] += 1
                        all_traces.append(trace_dict)
                        curr_trace_id = None
                        trace = []

                # Add details of the span
                span_id = span.span_id.hex()
                parent_span_id = None
                if len(span.references) > 0:
                    parent_span_id = span.references[0].span_id.hex()
                service = span.process.service_name
                duration = span.duration.nanos / 1000
                trace.append([span_id, service, duration, parent_span_id])

        if curr_trace_id != None:
            trace_dict = construct_trace(trace, curr_trace_id)
            for svc, _ in trace_dict["spans"].items():
                if svc not in svc_count:
                    svc_count[svc] = 1
                else:
                    svc_count[svc] += 1
            all_traces.append(trace_dict)
        
        # If no traces found, return empty list
        if len(all_traces) == 0:
            print("No traces found for {0}".format(service_name))
            return []

        collected_samples = len(all_traces)
        print("Collected samples: ", collected_samples)

        if use_period:
            break

        # Update monitoring period if we have not collected enough samples
        if collected_samples < num_samples:
            time_since_start = (datetime.datetime.now() - exp_start_time).total_seconds()
            expected_period = int((num_samples - collected_samples) * time_since_start / collected_samples) + 1
            monitoring_period = expected_period / 2
            collection_start_time = datetime.datetime.now()

    # print(
    #     "Number of request traces found for {0}: {1}".format(
    #         service_name, len(all_traces)
    #     )
    # )
    # print('Service-wise distribution: ', svc_count)

    if log:
        # Get the $HOME environment variable
        home = os.environ["HOME"]
        out_dir = os.path.join(home, "out")

        # Save the traces to a pickle file
        print(
            "Saving traces to {0}".format(
                os.path.join(out_dir, "traces_{0}_{1}.pkl".format(service_name, trace_name))
            )
        )
        with open(
            os.path.join(out_dir, "traces_{0}_{1}.pkl".format(service_name, trace_name)), "wb"
        ) as f:
            pickle.dump(all_traces, f)

    return all_traces


# Get the latencies of a service for the past `num_samples` samples.
# service_name: name of the service
# num_samples: number of samples to query
# jaeger_ip: IP address of the Jaeger gRPC stub
# Returns a list of latencies (in ms) for the span of the service.
def get_latencies(service_name, num_samples, jaeger_ip):
    channel = create_grpc_channel(jaeger_ip)
    stub = create_grpc_stub(channel)
    exp_start_time = datetime.datetime.now()
    traces = grpc_query_traces(
        stub, exp_start_time=exp_start_time, service_name=service_name, num_samples=num_samples
    )
    latencies = []
    for trace in traces:
        latencies.append(trace["spans"][service_name] / 1000)

    return latencies


# Get the end-to-end latencies of a particular request_type for the past `period` seconds.
# period: period for which we need to monitor the traces
# jaeger_ip: IP address of the Jaeger gRPC stub
# frontend_service: service whose span gives the end-to-end latency
# request_types: list of request types. Each request type is an array of services in the request chain
# Returns a list of latencies (in ms) for each request_type.
def get_latencies_by_type(period, jaeger_ip, frontend_service, request_types):
    channel = create_grpc_channel(jaeger_ip)
    stub = create_grpc_stub(channel)

    # Choose any service in the request_type, and then filter out the traces that do not
    # have all services in the request type.
    exp_start_time = datetime.datetime.now() # Not used if we are using period.
    traces = grpc_query_traces(
        stub, exp_start_time=exp_start_time, service_name=frontend_service, period=period
    )
    type_latencies = []
    for _ in request_types:
        type_latencies.append([])

    for trace in traces:
        for index, request_type in enumerate(request_types):
            all_present = True
            for svc in request_type:
                if svc not in trace["spans"]:
                    all_present = False
                    break

            if not all_present:
                continue
            else:
                type_latencies[index].append(trace["spans"][frontend_service] / 1000)
                break

    return type_latencies


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(
            "Usage: python query_jaeger.py <jaeger_ip> <trace_name> <samples>"
        )
        sys.exit(1)

    # Query for the services
    channel = create_grpc_channel(sys.argv[1])
    stub = create_grpc_stub(channel)
    all_services = grpc_query_service(stub)
    exp_start_time = datetime.datetime.now()

    for service in all_services:
        # Ignore the jaeger service
        if "jaeger" in service:
            continue

        grpc_query_traces(
            stub,
            exp_start_time,
            service_name=service,
            log=True,
            trace_name=sys.argv[2],
            num_samples=int(sys.argv[3]),
        )
