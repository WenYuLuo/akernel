# ADX workload checkpoint validation

Verified on 2026-09-22 on the dedicated Linux x86_64 standalone host with gVisor.
The workload interface remains `POST /checkpoint` on `/run/akernel/rrt.sock`.
RRT publishes a pending request to its owning Node Manager, which calls sandboxd
with `leave_running=true` and registers a local recovery point before replying.
The source stays running; SDK `reload()` restores the same logical sandbox.

The ADX implementation is commit `36a8258` (`fix/rrt-checkpoint-socket`). The
validation image `akernel-adx-validation:rrt-checkpoint` has ID
`sha256:6a9dee3bf0e3c7e74f655811ea8ebda0f2eadfab216ea1ae9c064264ad171434`.
It overlays the updated Node Manager, RRT and socket configuration on the #71
validation image. AKernel's existing rootfs was repacked with RRT; sandboxd was
unchanged. The repository release lock still selects #71, which does not include
this bridge: publish the ADX fix and update the artifact lock before relying on
workload checkpoints in a normal packaged deployment.

Results:

- `make sdk-check`: 253 tests passed, Ruff and mypy passed.
- `make deploy-script-check`: passed.
- `test_sandbox.py` standalone integration: 6 passed, 1 skipped (custom OCI image
  not configured), zero failures/errors.
- `test_internal_checkpoint_reload_and_reverse_tunnel` proved Unix socket
  completion, source continuation, reload to checkpoint-era file contents and
  reverse-tunnel recovery. The SDK retains its existing command/file/PTY facades.
- A route propagation race was reproduced after reload. The adapter now uses a
  read-only process listing before returning success; it does not repeat reload.
  Temporary 409 conflicts are bounded, and terminal errors are not retried.
- The task container was removed; persisted test logs and checkpoint data remain
  in the isolated validation worktree for diagnosis.

Remote log: `/var/log/akernel-rrt-checkpoint-e2e-final-20260922.log`.
Custom OCI and Kubernetes were not validated by this run.

## Firecracker follow-up (2026-09-22)

The same integration suite was rerun with `AKERNEL_TEST_RUNTIME=firecracker`
on the x86_64 host (Linux `6.8.0-137-generic`, accessible `/dev/kvm`, KVM API 12).
It passed: **6 cases passed, 1 OCI/Nydus case skipped**, zero failures/errors,
73.973 seconds. The checkpoint/reload/file rollback/reverse-tunnel case passed.
Command/process listing, filesystem and all three PTY cases also passed.
The test container was stopped and removed; logs and task data were retained.

The gVisor validation image did not contain the optional Firecracker payload.
The FC image adds the pinned `v1.16.1-akernel.3` VMM, guest kernel `6.1.177`,
and virtiofsd `1.14.0` from the existing AKernel image after manifest/hash
verification. The guest initrd was built from the same sandboxd source
`7d2af7f52eeaae5203fc9f4fe3dadffc357eac3c`; the sandboxd daemon was unchanged.

- Image: `akernel-adx-validation:rrt-checkpoint-fc`.
- Image ID: `sha256:e5e653a06555cac24d490550b8aad770df3b1d7ba1984a26b7da818f5b9243d9`.
- VMM SHA256: `41133331123c05d635a1a4a61a1eb41f078e9a216b5a197c1398e4e64e957cbf`.
- Kernel SHA256: `78c482cb6904f12c7de16e434de3e8163e9bb7d8abac982a508250ca59abe9af`.
- Initrd SHA256: `1753c338a6a100105ea0e93ce1b94031ff6b9820f7f62292a1c662c82ed6b912`.
- Remote log: `/var/log/akernel-adx-fc-e2e-20260922.log`.
- Local log: `out/remote-validation/logs/firecracker-e2e.log`.

This remains an overlay validation image. The formal ADX release and AKernel
artifact lock update are still pending; this result does not cover custom OCI,
cross-node cloning or Kubernetes deployment.

## Review compatibility regression (2026-09-22)

The revised SDK and simplified standalone profile were validated using only
`AKERNEL_SERVER_ADDRESS=127.0.0.1` and `AKERNEL_TOKEN`. No backend selector,
URL scheme, or gateway override was supplied. The existing `data/token` path
remains the credential entry point, and generated certificates are reused.

- SDK: 227 unit tests, Ruff, and mypy passed. Tests of the removed adapter were
  retired; address parsing, legacy selector aliases, explicit cleanup, and the
  GC-under-HTTPX-lock regression remain covered.
- Deployment: 22 runtime/certificate/Secret/Helm/Terraform contract tests passed;
  shell syntax and Terraform input-reference checks passed.
- gVisor: 6 passed, 1 custom OCI case skipped (52.085 seconds).
- Firecracker: 6 passed, 1 custom OCI case skipped (71.901 seconds).
- Remote run log: `/var/log/akernel-review-78-final-e2e.log`.
- Local run log: `out/pr/standalone-final-e2e.log`.

The runtime image is still derived from the checkpoint validation overlay above,
with the revised configuration and entrypoint scripts. This run verifies the
SDK and deployment behavior; it does not verify a clean all-in-one build from
the currently pinned release. Public artifact publication, the formal package
update, custom OCI validation, and live Kubernetes validation remain pending.
