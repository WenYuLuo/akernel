#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

action="${1:?ADX service action is required}"
config="${AKERNEL_ADX_CONFIG:-/etc/akernel/adx-standalone.yaml}"

case "${action}" in
  run|stop)
    exec /opt/adx/current/bin/adxctl --config "${config}" "${action}"
    ;;
  *)
    echo "unsupported ADX service action: ${action}" >&2
    exit 2
    ;;
esac
