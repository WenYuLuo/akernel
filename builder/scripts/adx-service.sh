#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

action="${1:?ADX service action is required}"
config="${AKERNEL_ADX_CONFIG:-/etc/akernel/adx-standalone.yaml}"

if [[ "${AKERNEL_ADX_MANAGED_CREDENTIALS:-local}" != external ]]; then
  state_dir="${AKERNEL_ADX_STATE_DIR:-/home/akernel/adx}"
  install -d -m 0700 "${state_dir}" "${state_dir}/run"
  ln -sfn "${state_dir}" /opt/adx/config
  ln -sfn "${state_dir}" /opt/adx/data
  ln -sfn "${state_dir}/run" /opt/adx/run
fi

case "${action}" in
  run|stop)
    exec /opt/adx/current/bin/adxctl --config "${config}" "${action}"
    ;;
  *)
    echo "unsupported ADX service action: ${action}" >&2
    exit 2
    ;;
esac
