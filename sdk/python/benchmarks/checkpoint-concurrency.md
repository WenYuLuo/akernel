# checkpoint 并发压力验证

2026-10-09，在 cn-north-4 的 `akernel` 命名空间，通过集群内客户端与独立
ADX API Server 测试入口，验证 `mixed_profile.py` 的独立 checkpoint 沙箱池。
每种 profile 运行 120 秒，七类合计计划到达率 10 事务/秒，runsc 后端。

## 变更与契约

`--checkpoint-concurrency N` 同时控制 checkpoint 类在途上限和独立沙箱数量，
默认值 1 保留历史测量方式。每笔事务独占一个沙箱，完成 checkpoint、reload
和文件回滚验证后归还；失败也归还。多个沙箱可以并发，同一个沙箱不会并发恢复。
fixture 通过 ExitStack 在结束或部分初始化失败时清理已创建沙箱。

其余六类在途上限保持原值：command 4、HTTP 4、file 2、lifecycle 2、PTY 2、
tunnel 1。`target_load_met` 独立报告计划到达槽位是否全部成功执行；`status`
仍报告已提交操作和清理是否成功。目标负载未达成不能只根据 `status=passed`
判定为容量验收通过。计入尾部 drain 后的吞吐按实际结果时长计算。

35 项 benchmark 驱动测试通过，新增测试覆盖并发沙箱独占、失败归还、无效并发
参数以及目标到达槽位的完整与受限结果。新增接口不存在时的红灯与完整绿灯日志
保存在本地 `out/ci/checkpoint-concurrency/`。

## 制品与资源边界

API Server 镜像 digest：
`sha256:764138bb124494c28c00afc4802fbd8fd70edffedc637f3fa8fab3565fcffc83`。
节点 Execd 镜像 digest：
`sha256:4f98767a85fc9607373397d7c588d30749dc6453824887fe943f585fb0a22073`。
本次复用此前验证的派生镜像，没有改动 sandboxd、Coordinator 或生产 API Server。
ADX API/PTY 修复已发布至 `community/refactor` 的 `aac7bfd`。

四个节点均就绪。API Server 限额 8 CPU / 1 GiB；客户端限额 4 CPU / 2 GiB。
每种 profile 准备三个常驻服务沙箱和 N 个 checkpoint 沙箱，每个请求
1 CPU / 2 GiB，checkpoint 实例另请求 256 MiB 存储。测试镜像沿用固定 SWR
OCI digest；入口使用正常 TLS 证书校验。实际集群运行的驱动 SHA256 与
`cd5a94d` 的 `mixed_profile.py` 文件一致。接入 PR 时仅修正超长行格式，
没有改变运行逻辑；修正后的 Ruff 与 35 项驱动测试均通过。

## 结果

| profile | checkpoint 并发 | checkpoint 成功 / 失败 / 客户端拒绝 | 原单路客户端拒绝 | checkpoint 均值 ms | 全组 target_load_met |
|---|---:|---:|---:|---:|---|
| interactive | 4 | 60 / 0 / 0 | 36 | 3,222.17 | true |
| io-heavy | 12 | 181 / 0 / 0 | 157 | 3,388.77 | true |
| churn-heavy | 8 | 120 / 0 / 0 | 95 | 3,391.11 | false |

361 次计划 checkpoint 均执行成功，原单路的 288 次未提交归零。本次提高的是
独立沙箱并发，而非同一个沙箱 checkpoint 的并发上限，也没有证明后端容量极限。
上述均值是完整 checkpoint、reload 和恢复验证，不是单独 checkpoint RPC 耗时。

| profile | 七类总成功 / 执行失败 | 客户端拒绝 | 实际结果时长 s | 含 drain 有效事务/秒 |
|---|---:|---:|---:|---:|
| interactive | 1,202 / 0 | 0 | 123.39 | 9.74 |
| io-heavy | 1,203 / 0 | 0 | 122.69 | 9.80 |
| churn-heavy | 1,198 / 0 | 4 | 120.64 | 9.93 |

churn-heavy 的 4 次拒绝全部来自 lifecycle 原在途上限 2；计划 421 次，提交
417 次并全部成功。该类 P99 桶上界为 2 秒，其他两组分别为 250 ms、1 秒。
本轮没有按每笔事务采集完整阶段 Trace，不能据此确定尾延迟原因。

所有类别执行失败、清理错误和 missed_deadline 均为零。checkpoint 的三组
P99 桶上界均为 10 秒；桶上界不能当成精确百分位。

## 审计与证据

每阶段前后及最终 Redis 的实例目录、held、failed-held 均为空。
四个节点最终实际后端数均为零，均 Ready，重启次数为零。
独立测试 Deployment、Service、ConfigMap 和客户端 Pod 已清理。

集群日志和 3 份结果 JSON 保存在 ADX 工作树的
`out/ci/cn4-checkpoint-parallel-20261009/`，包括 `regression.log`、
`results/campaign.json`、逐类 `mixed-*.json`、`driver-identity.json`、
`redis-final.json`、`backend-final.json`、`cleanup-final.json`。
这些是 runsc 短时 SDK 压力证据，不包含 Firecracker、Kata 或长期稳定性验证。
