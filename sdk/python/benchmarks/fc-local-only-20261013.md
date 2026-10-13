# Firecracker 同节点 local-only 发布包回归

2026-10-13，在远端开发机 `47.83.171.126` 升级独立 standalone 夹具并测试。

## 制品与环境

- ADX 平台：`v0.1.0rc1`，Buildkite #152，commit
  `9a7924658fbcf04a34d76bfcecb0935ed850923a`。
- ADX Sandbox SDK：从 PyPI 安装 `adx-sandbox==0.1.0rc2`。
- 平台与 Execd 分别取自不可变 OBS 路径
  `adx/daily/20261012104710-9a7924658fbc/linux/amd64/`；SHA256 与
  [`deploy/README.md`](../../../deploy/README.md) 中的版本一致。
- 新 standalone 镜像：`akernel-standalone:adx152-20261013`。复用已验证的
  AKernel 后端镜像，安装完整新平台包，使用新 Execd 重建 AKernel 自有 EROFS
  rootfs。已比对安装目录内全部平台二进制及 rootfs 内 Execd 的 manifest 哈希。
- sandboxd gitlink 保持 `31d0749a85e269396cfc1c469c948345f9610906`；本轮没有改
  sandboxd、Firecracker 或部署参数来缩短耗时。
- x86_64、32 CPU、123 GiB RAM、KVM，Linux `6.8.0-137-generic`，宿主 NVMe ext4。
- 独立容器 `akernel-adx152-standalone-20261013`，控制入口 `127.0.0.1:28443`
  与数据入口 `http://127.0.0.1:28080`。此轮没有升级 cn-north-4 集群。
- 复用 SWR 测试镜像
  `swr.cn-north-4.myhuaweicloud.com/openyuanrong/e2e-oci:python312-curl-http-20260927`，
  验证 digest `sha256:80ecce8615ec8e2294aec0d8f61c74f28bed73e4b4d27de512e640a79cb083b3`；没有重复上传。

## 测量口径

通过 ADX Sandbox SDK 调用真实 FC：五档常驻随机内存，每档连续三次
`pause(timeout_seconds=600, ttl_seconds=3600)` / `resume()`，随后一次最新恢复点
`reload()`。每档只运行一个实例，CPU 请求 1000m，可写层 256 MiB。
初始化、镜像准备与随机内存分配均不计入暂停或恢复时延。

- 恢复点必须为 `storage=local`，resume 返回的 node_id 必须等于源节点；没有 OBS 上传或下载。
- 暂停：SDK 调用开始至成功返回。local-only 成功保证制品完整、可读和登记完成，
  ADX 不再额外逐文件执行同步 fsync；不保证宿主突然断电后的制品完整性。
- 恢复：SDK resume 开始至返回 Running；首命令：同一起点至进程验证命令成功。
- 恢复后比较同一进程 PID、随机标记与每 MiB 首尾 64 字节抽样摘要。
  抽样并非扫描完整 VM 内存，首命令完成也不等于所有恢复页已预热。
- reload 从 Running 状态切换到恢复点，包含停止旧执行，独立于 Paused 状态的 resume。
- 每档三轮只用于范围与中位值比较，不能估计 P99 或定义容量 SLA。

## 结果

15 次 pause/resume、5 次 reload 均通过；随后 AKernel L0 为 8/8 项通过、零跳过。
40 行采样含 5 行夹具记录，其余 35 行为操作计时。最终 backend 实例、Redis Environment 字段、checkpoint 制品文件均为 0；新 standalone 保留运行。

时间单位为秒；恢复和首命令列为三轮中位值，重复暂停为后两轮范围。

| 常驻数据 MiB | VM 内存 MiB | 快照 GiB | 首次暂停 | 恢复后再暂停 | resume 返回 Running | 首命令完成 |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1024 | 1.25 | 5.032 | 7.803–12.337 | 1.610 | 1.979 |
| 64 | 1088 | 1.31 | 4.706 | 8.959–12.740 | 1.809 | 2.134 |
| 256 | 1280 | 1.50 | 3.205 | 12.653–14.082 | 4.433 | 4.850 |
| 1024 | 2048 | 2.25 | 2.861 | 18.530–20.960 | 6.741 | 7.272 |
| 2048 | 3072 | 3.25 | 1.768 | 29.165–32.019 | 8.047 | 8.697 |

| 常驻数据 MiB | 三轮 resume 范围 | 三轮首命令范围 | 一次 reload 首命令 |
|---:|---:|---:|---:|
| 0 | 1.577–4.782 | 1.910–5.137 | 5.204 |
| 64 | 1.688–5.462 | 2.057–5.791 | 5.007 |
| 256 | 2.818–4.537 | 3.208–4.895 | 6.920 |
| 1024 | 6.243–8.323 | 6.744–8.861 | 6.332 |
| 2048 | 3.751–8.094 | 4.412–8.723 | 15.749 |

### 与 2026-10-11 同机历史记录比较

旧记录首次暂停为 7.001 / 7.259 / 8.385 / 12.893 / 18.979 秒，
恢复返回 Running 中位值为 1.407 / 1.413 / 1.382 / 1.985 / 2.500 秒。
本轮首次暂停全部更快，重复暂停也低于旧范围；恢复中位值则全部变慢，较大 VM 尤其明显。
旧记录与本轮的主机、sandboxd pin、测试规模和请求方式相同，但平台、Execd 和 SDK 已更新，
且磁盘写回、镜像缓存与宿主负载未做同时配对控制。只能作为历史对照，不能归因为某一个改动的净收益。

### 阶段证据与仍有的瓶颈

3 GiB VM（2 GiB 常驻随机数据）的日志与 SDK 计时：

| 轮次 | SDK pause | guest flush | FC snapshot | 后端 checkpoint 阶段合计 | 后台 memory writeback 日志耗时 |
|---|---:|---:|---:|---:|---:|
| 1 | 1.768 | 0.011 | 1.218 | 1.335 | 36.350 |
| 2 | 32.019 | 2.000 | 27.270 | 29.349 | 33.226 |
| 3 | 29.165 | 2.000 | 23.523 | 25.610 | 25.084 |

后台写回与 API 调用有重叠，不能把最后一列与前面阶段直接相加。第一次 checkpoint
阶段在 01:07:33.133 结束，SDK 约 1.768 秒返回；后台 writeback 日志直到
01:08:09.483 才出现。期间已经完成恢复并开始下一次暂停，证明 local-only 成功返回
没有等待整份 memory 的后台写回完成。

恢复后的十次 checkpoint 均保留 2 秒 guest flush 超时；3 GiB VM 重复保存的
snapshot 阶段仍为 23.523–27.270 秒。这些后端瓶颈未由 ADX 去除 fsync 的改动解决。

一个较慢的 3 GiB VM 恢复样本中：sandboxd Start 于 01:08:14.499 收到；
OCI MountImage 总计 4.392 秒，其中 extract_layers 3.777 秒；FC restore
阶段总计 2.030 秒（load 1.255 秒，agent 0.577 秒）。因此不能将 SDK 恢复的
全部时延当作 FC snapshot load，也不能只凭后台写回重叠就认定恢复变慢的唯一根因。
日志确认 OCI 准备及 FC 恢复均有成本；I/O 竞争程度仍需独立配对实验。

### 清理与部署留存

- 5 个性能测试 Environment 和 L0 创建的 Environment 均已删除。
- `sbox list` 仅表头；Redis `environment:*` 字段为空；checkpoint 目录无制品文件。
- `cleanup.json.exit_code=0`，容器保持运行，便于继续手动验证。
- 镜像 ID：`sha256:0fefaf396c4c7cbbb2223c6a1ccbcce60418d1a8e80d75cd93e56ce275c3da31`。
- 正式测试没有复用前置失败尝试的 Redis 数据。

## 证据与复跑

远端证据目录：
`/root/akernel-worktrees/adx-release152-20261013/out/ci/fc-release-152-20261013/`。
主日志：`/var/log/akernel-adx152-fc-regression-ready-20261013.log`。

证据包括 `samples.jsonl`、`performance-summary.json`、`summary.json`、
`installed-identity.json`、`sandboxd.log`、`bench.py`、`run.sh`、
`akernel-l0/summary.json` 和最终清理检查。驱动及日志保留在该次运行目录，
不含 registry 凭证或 API Key 的公开副本。

运行入口为该目录的 `run.sh`；它拒绝覆盖现存同名容器，使用独立数据目录，
在失败时移除自己的容器，在全部通过时保留部署。复跑前应先保存已有证据，
停止自己的夹具并使用新的测试目录；不要复用旧样本文件或删除其他用户环境。

前置失败（镜像组装路径、身份探测工具、SWR 凭证过期）已与正式样本分开保存；
修正验证夹具并核验身份后才开始计时。旧 Redis/配置目录未沿用到正式测试。
