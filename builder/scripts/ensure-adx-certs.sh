#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

state_dir="${AKERNEL_ADX_STATE_DIR:-/home/akernel/adx}"
tls_dir="${state_dir}/tls"
secrets_dir="${state_dir}/secrets"
required=(
  ca.pem public-ca.pem
  master.pem master.key master.der
  node-1.pem node-1.key node-1.der
  api-server.pem api-server.key api-server.der
  edge.pem edge.key edge.der
  edge-public.pem edge-public.key
)

complete=1
for file in "${required[@]}"; do
  [[ -s "${tls_dir}/${file}" ]] || complete=0
done
[[ -s "${secrets_dir}/admin-key" ]] || complete=0
if [[ "${complete}" == 1 ]]; then
  exit 0
fi

install -d -m 0700 "${state_dir}" "${tls_dir}" "${secrets_dir}"
tmp_dir="$(mktemp -d "${state_dir}/.certs.XXXXXX")"
cleanup() {
  rm -rf -- "${tmp_dir}"
}
trap cleanup EXIT

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${tmp_dir}/ca.key" \
  -out "${tmp_dir}/ca.pem" \
  -subj "/CN=akernel-adx-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -days 3650 >/dev/null 2>&1

cat > "${tmp_dir}/leaf.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:localhost,DNS:adx.internal,IP:127.0.0.1
EOF

for identity in master node-1 api-server edge edge-public; do
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
  if [[ "${identity}" != edge-public ]]; then
    openssl x509 -in "${tmp_dir}/${identity}.pem" -outform DER \
      -out "${tmp_dir}/${identity}.der"
  fi
done

cp "${tmp_dir}/ca.pem" "${tmp_dir}/public-ca.pem"
openssl rand -hex 32 > "${tmp_dir}/admin-key"
chmod 0644 "${tmp_dir}"/*.pem "${tmp_dir}"/*.der
chmod 0600 "${tmp_dir}"/*.key "${tmp_dir}/admin-key"

for file in "${required[@]}"; do
  mode=0644
  if [[ "${file}" == *.key ]]; then
    mode=0600
  fi
  install -m "${mode}" "${tmp_dir}/${file}" "${tls_dir}/${file}"
done
install -m 0600 "${tmp_dir}/admin-key" "${secrets_dir}/admin-key"
