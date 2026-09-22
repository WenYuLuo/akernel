#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

if [[ "${AKERNEL_ADX_MANAGED_CREDENTIALS:-local}" == "external" ]]; then
  exit 0
fi

state_dir="${AKERNEL_ADX_STATE_DIR:-/home/akernel/adx}"
tls_dir="${state_dir}/tls"
secrets_dir="${state_dir}/secrets"
install -d -m 0700 "${state_dir}" "${tls_dir}" "${secrets_dir}"
if [[ ! -s "${tls_dir}/edge-public.pem" || ! -s "${tls_dir}/edge-public.key" ]]; then
  tmp_dir="$(mktemp -d "${state_dir}/.certs.XXXXXX")"
  trap 'rm -rf -- "${tmp_dir}"' EXIT
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "${tmp_dir}/edge-public.key" -out "${tmp_dir}/edge-public.pem" \
    -subj "/CN=akernel" -days 3650 \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "extendedKeyUsage=serverAuth" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" >/dev/null 2>&1
  install -m 0600 "${tmp_dir}/edge-public.key" "${tls_dir}/edge-public.key"
  install -m 0644 "${tmp_dir}/edge-public.pem" "${tls_dir}/edge-public.pem"
fi
if [[ ! -s "${secrets_dir}/admin-key" ]]; then
  umask 077
  openssl rand -hex 32 > "${secrets_dir}/admin-key"
fi
