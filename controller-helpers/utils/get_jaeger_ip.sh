#!/bin/bash
# Script to get the IP address of the Jaeger service and print to console.

IP_ADDR=$(kubectl get svc jaeger -o jsonpath='{.spec.clusterIP}')
echo $IP_ADDR