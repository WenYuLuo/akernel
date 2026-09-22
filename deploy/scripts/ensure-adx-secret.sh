#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

namespace="${NAMESPACE:-akernel}"
secret_name="${SECRET_NAME:-akernel-adx-tls}"
kubectl_bin="${KUBECTL:-kubectl}"
kubeconfig=""

kubectl_cmd() {
  if [[ -n "${kubeconfig}" ]]; then
    "${kubectl_bin}" --kubeconfig "${kubeconfig}" "$@"
  else
    "${kubectl_bin}" "$@"
  fi
}

usage() {
  cat <<'EOF'
Usage: ensure-adx-secret.sh [options]

Create the shared Agent DX Kubernetes identity Secret when it does not exist.
The node certificate is a pool identity; each Node Manager supplies its
Kubernetes node name in the authenticated RPC request.

Options:
  -n, --namespace NAME     Kubernetes namespace (default: akernel)
      --name NAME          Secret name (default: akernel-adx-tls)
      --kubeconfig PATH    kubeconfig passed to kubectl
  -h, --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n | --namespace)
      namespace="$2"
      shift 2
      ;;
    --name)
      secret_name="$2"
      shift 2
      ;;
    --kubeconfig)
      kubeconfig="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v "${kubectl_bin}" >/dev/null 2>&1 || {
  echo "kubectl not found: ${kubectl_bin}" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required to generate Agent DX identities" >&2
  exit 1
}

if ! kubectl_cmd get namespace "${namespace}" >/dev/null 2>&1; then
  kubectl_cmd create namespace "${namespace}"
fi

if kubectl_cmd -n "${namespace}" get secret "${secret_name}" >/dev/null 2>&1; then
  echo "Agent DX Secret already exists: ${namespace}/${secret_name}"
  exit 0
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf -- "${tmp_dir}"' EXIT

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${tmp_dir}/ca.key" \
  -out "${tmp_dir}/ca.pem" \
  -subj "/CN=akernel-adx-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -days 3650 >/dev/null 2>&1

cat >"${tmp_dir}/leaf.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:adx.internal,DNS:akernel-adx-control,DNS:akernel-adx-control.${namespace},DNS:akernel-adx-control.${namespace}.svc,DNS:akernel-adx-control.${namespace}.svc.cluster.local,IP:127.0.0.1
EOF

for identity in master node api-server edge public; do
  openssl req -newkey rsa:2048 -nodes \
    -keyout "${tmp_dir}/${identity}.key" \
    -out "${tmp_dir}/${identity}.csr" \
    -subj "/CN=${identity}" >/dev/null 2>&1
  openssl x509 -req \
    -in "${tmp_dir}/${identity}.csr" \
    -CA "${tmp_dir}/ca.pem" \
    -CAkey "${tmp_dir}/ca.key" \
    -CAcreateserial \
    -out "${tmp_dir}/${identity}.pem" \
    -days 3650 \
    -extfile "${tmp_dir}/leaf.ext" >/dev/null 2>&1
  if [[ "${identity}" != public ]]; then
    openssl x509 -in "${tmp_dir}/${identity}.pem" -outform DER \
      -out "${tmp_dir}/${identity}.der"
  fi
done

openssl rand -hex 32 >"${tmp_dir}/admin-key"

kubectl_cmd -n "${namespace}" create secret generic "${secret_name}" \
  --from-file=ca.pem="${tmp_dir}/ca.pem" \
  --from-file=master.pem="${tmp_dir}/master.pem" \
  --from-file=master.key="${tmp_dir}/master.key" \
  --from-file=master.der="${tmp_dir}/master.der" \
  --from-file=node.pem="${tmp_dir}/node.pem" \
  --from-file=node.key="${tmp_dir}/node.key" \
  --from-file=node.der="${tmp_dir}/node.der" \
  --from-file=api-server.pem="${tmp_dir}/api-server.pem" \
  --from-file=api-server.key="${tmp_dir}/api-server.key" \
  --from-file=api-server.der="${tmp_dir}/api-server.der" \
  --from-file=edge.pem="${tmp_dir}/edge.pem" \
  --from-file=edge.key="${tmp_dir}/edge.key" \
  --from-file=edge.der="${tmp_dir}/edge.der" \
  --from-file=public.pem="${tmp_dir}/public.pem" \
  --from-file=public.key="${tmp_dir}/public.key" \
  --from-file=admin-key="${tmp_dir}/admin-key"

echo "Created Agent DX Secret: ${namespace}/${secret_name}"
