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
Firecracker, custom OCI and Kubernetes were not validated by this run.
