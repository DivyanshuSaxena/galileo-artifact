#!/usr/bin/env bash
# Start the Social Network benchmark

: "${TESTBED:=$HOME}"
pushd $TESTBED

if [ ! -d "$TESTBED/train-ticket" ]; then
  git clone https://github.com/DivyanshuSaxena/train-ticket.git

  kubectl apply -f https://openebs.github.io/charts/openebs-operator.yaml
  kubectl patch storageclass openebs-hostpath -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
fi

pushd train-ticket
helm install train-ticket .
popd

# Wait for the pods to get running
sleep 15m

popd
