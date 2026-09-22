# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

ARG AKERNEL_RUNTIME_BASE_IMAGE=ubuntu:24.04

FROM scratch AS rrt-download

COPY --from=adx_release /runtime/rrt-runtime /rrt-runtime

FROM ${AKERNEL_RUNTIME_BASE_IMAGE} AS rrt-runtime-rootfs

ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libgcc-s1 \
        tini && \
    rm -rf /var/lib/apt/lists/* && \
    test -x /usr/bin/tini-static && \
    /usr/bin/tini-static --version

RUN mkdir -p /var/task/code /__yuanrong /__adx && \
    ln -sfn /home /__yuanrong/home && \
    ln -sfn /usr /__yuanrong/usr && \
    ln -sfn /opt /__yuanrong/opt && \
    ln -sfn /root /__yuanrong/root && \
    ln -sfn /home /__adx/home && \
    ln -sfn /usr /__adx/usr && \
    ln -sfn /opt /__adx/opt && \
    ln -sfn /root /__adx/root

COPY --from=rrt-download /rrt-runtime /usr/local/bin/rrt-runtime

FROM ${AKERNEL_RUNTIME_BASE_IMAGE} AS erofs-builder-base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends erofs-utils && \
    rm -rf /var/lib/apt/lists/*

FROM erofs-builder-base AS rrt-erofs-builder

COPY --from=rrt-runtime-rootfs / /rootfs
RUN mkfs.erofs -E noinline_data /yr-runtime-rootfs.img /rootfs && \
    fsck.erofs /yr-runtime-rootfs.img

FROM scratch AS runtime-rrt
COPY --from=rrt-erofs-builder /yr-runtime-rootfs.img /yr-runtime-rootfs.img
LABEL org.akernel.runtime.profile="rrt"
