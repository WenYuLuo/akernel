# ADX 看板说明

看板范围由 `cluster` 和 `adx_env` 共同限定。`adx_env` 是部署环境标签；单个沙箱由 Environment ID 标识。各面板的信息图标提供查询口径。以下覆盖六个 ADX 看板；旧 `Sandbox Metrics` 是 Environment 明细的兼容入口。

## 先看统计边界

- **当前值**表示此刻的库存、队列或连接数；**速率**表示窗口内每秒增量；**累计计数器**记录进程或持久业务历史的累计事件。它们不能直接互相比大小。
- 所有 Environment 删除后，当前明细、CPU、内存无行是预期行为。CPU 速率至少需要两次采集；短于采集间隔的用例可能没有资源曲线。
- 空闲窗口没有请求时，成功率与 P95 可以是空值/NaN。它们没有定义，不能解释成 100% 成功或 0 延迟。
- 采集失败、样本过期与真实零负载不同。缺数据不能自动补成“健康的 0”。
- 心跳可达、调度准入、资源观测新鲜度是三个独立维度。资源采样缺失本身不等于节点不可用。

## 创建耗时与告警口径

`POST /api/environment/v1/environments` 的 HTTP span 在响应头返回时结束。SSE 先返回 200/accepted，然后才完成后台创建，因此这个 HTTP 耗时经常只有毫秒级。`environment.create` 业务 span 才覆盖到调度、运行时启动与最终创建结果；它从进入业务创建流程开始，不包含更早的认证/规格准备。成功复用也可以产生成功业务 span；衡量新建性能应使用 Successful New-Create Call P95。Trace 是采样数据，不是完整请求流水。

Control Warnings / Errors 统计最近五分钟 **WARN/ERROR 日志条数**，不是独立故障数或告警规则触发次数。一个未收敛的 Environment 可以每轮对账打印一条日志，同轮还会打印节点汇总。Repeated 表用于按节点、Environment、错误原因展开。后端 Start 结果未知时，一次 List 没找到物理实例不能证明迟到 Start 不会继续创建，因而不能据此直接抹掉控制状态。

节点表展示 Coordinator 的已注册目录，包含历史不可达注册。删除 Kubernetes Node 不一定删除这条注册；Reachable Nodes 只累加当前可达标志。清理历史注册属于节点生命周期操作，不能通过隐藏表格行代替。

## ADX Schedule：调度与采集健康

| 面板 | 含义及读法 |
| --- | --- |
| Running Environments | 当前控制面已提交 Running 状态的逻辑 Environment 数。 |
| Paused Environments | 当前已提交 Paused 状态的数量。暂停前资源样本不能代表当前用量。 |
| Reachable Nodes | Coordinator 心跳判定可达的注册节点数；历史不可达节点贡献 0。 |
| Schedulable Nodes | 当前允许调度的节点数。可达节点也可能因管理准入或运行时能力而不能接收新任务。 |
| Queued Requests | 仍在中央调度队列等候分配的请求数，已分配到节点的创建不属于这个队列。 |
| Created QPS (1m window) | 新 Environment 首次持久提交 Running 的每秒速率；复用、重放、恢复/重启不作为新建。 |
| Created Peak QPS (1m window) | 所选时间范围内，新建一分钟平均速率的最高值。 |
| Created Throughput (1m window) | 真实新建 Environment 的每秒速率曲线，按一分钟平均。 |
| Create Call Outcomes | 创建调用按 success/failure/cancelled/unknown 分组。unknown 是结果不确定，不能直接当作确定失败。 |
| Create Calls in Flight | 等待最终结果的创建调用，包含 SSE 响应头返回后的后台创建。 |
| Create Call Duration P95/P99 | 创建调用到最终结果的耗时分位数，包含重放/复用及各类结果。 |
| CPU / Memory / Disk Allocation Ratio（三个面板） | 允许调度节点上的资源预留量与容量之比。表示资源账本分配，不是实际 CPU、内存或磁盘使用率。 |
| CPU / Memory / Disk Scheduling Capacity and Allocated（三个面板） | 对比调度容量与已分配量。关闭准入使可调度容量为 0，但不释放原有分配；可达节点上的既有分配仍显示。磁盘容量是调度额度，不等同于文件系统总大小。 |
| Running and Paused Environments over Time | 每个历史采样时刻的运行/暂停并发数量，不是所选时间内累计创建数。 |
| Running and Paused Environments by Node | **表格**：每节点一行，Running、Paused 两列，单元格是当前逻辑 Environment 数。包含历史注册节点，0 表示该状态当前没有实例。 |
| Average Running Environments per Node | 可达节点上的 Running 总数除以可达节点数，包含运行数为 0 或已关闭准入的可达节点。没有可达节点时平均值没有意义。 |
| Maximum Running Environments on a Node | 当前可达节点中最大的 Running 数，反映放置集中程度。 |
| Node Status, Scheduling Capacity and Allocation | 每注册节点一行：Reachability 是心跳可达性；Admission 是调度准入；Resource Sample 是资源观测新鲜度。超过 45 秒的样本为 Unknown。容量列展示可调度额度；分配条展示可达节点的预留量/底层容量，关闭准入也保留既有占用。容量为 0 或缺失时比例为 Unknown。条形图固定 0–100%，超过 100% 仍显示数值；70% 以下绿、70–90% 黄、90% 及以上红。历史节点可显示 Unreachable / Blocked / Unknown。 |
| Exported and Failed Spans | Coordinator/adxlet 原生 span 导出的累计计数；span 数不同于 Trace 数和请求数。Ingress 请求可直接在 Tempo 查询。 |
| Environment CPU Usage | 有效 Running 资源样本的 CPU 速率，单位核；至少需两次计数器采样，并应结合新鲜度看。 |
| Environment Memory Usage | 有效 Running 资源样本的内存用量；过期、暂停或删除实例的旧值不作为当前内存。 |
| Fresh and Stale Resource Samples | 运行时资源样本的新鲜/过期数量，帮助区分零负载与观测失效。 |
| Runtime Logs (selected range) | 所选时间范围内运行时日志条数。空闲时可能没有日志；无数据需结合 Collector 状态判断，不能直接解释为采集正常。 |
| Control Warnings / Errors (last 5m) | 最近五分钟控制组件 WARN/ERROR 日志总条数，可能包含同一问题的周期重试。 |
| Repeated Control Warnings / Errors (last 5m) | **表格**：按节点、Environment、错误原因归组的五分钟日志数。Environment ID 为空的行是节点汇总，可能与 Environment 行源于同一故障。 |
| Collector Queue Utilization | Collector 导出队列占用/容量；0 表示队列当前空，缺少 exporter 序列不能直接补 0。 |
| Collector Refused / Enqueue Failed | 日志、指标、Trace 三类信号分别统计接收拒绝及导出入队失败的每秒速率。属于观测链路问题；部分计数器首次使用前不导出。 |

## ADX Sandbox Lifecycle：创建与生命周期

| 面板 | 含义及读法 |
| --- | --- |
| Creation Call Success Ratio | success/(success+failure)。重试/重放按调用计算，unknown/cancelled 单独显示。分母为 0 时无有效成功率。 |
| Successful New-Create Call P95 | 仅成功的新建调用耗时；复用/重放与不确定结果不贡献该样本。 |
| Creation Call Results | 各滚动统计窗口内创建调用结果数量，按 outcome 区分。不同于新建 Environment 事实数量。 |
| Creation Errors by Stage / Reason | **表格**：所选看板时间范围内，按 outcome、stage、reason 汇总创建错误。0 组合不展示；increase 在窗口边界外推，数量可能有小数。无行还需结合采集健康判断。 |
| Current Queued / Starting | 当前等待分配与已分配但尚在创建的数量；终态或已删除记录不计为 Starting。 |
| Oldest Wait | 当前已知等待起点的请求中，最长等待/启动时间，单位秒；没有这类请求时为 0。 |
| Unknown Wait Age | 等待起点不明的排队/启动记录**数量**，不是等待秒数。 |
| Interruptions by Reason | 按原因统计中断事实；重复 WARN 日志不会自动增加一次中断。 |
| Recovery Results | 恢复事实按 recovered、unrecoverable、closed_by_user 分类。普通 Snapshot 克隆不是节点故障恢复。 |
| Current Unrecovered Environments | 当前保留的最新未恢复摘要，不是任意历史窗口的去重影响数量。 |
| Worker Incidents | Worker session 故障事件数，不是不同物理节点的数量。 |
| Operations with Unknown Outcome after Node Loss | 节点丢失时仍有操作在途、结果因此不明的当前失效 Environment 数；不覆盖所有超时或后端 Start 不确定状态。 |
| Collector Target Up | 每个 job/instance 采集目标的 0/1 状态；1 只表示采集成功，不表示业务调用全部成功。一个节点可以有多个目标。 |
| Business Snapshot Age | Coordinator 业务观测缓存最近刷新距今时间。与心跳年龄、运行时资源样本年龄不同。 |
| Normal Operation Results | pause/delete 等生命周期操作，按 operation、intent、outcome 汇总。intent 区分显式调用与空闲策略等来源。 |
| Creation Rejections | 进入已接纳创建尝试之前的拒绝，例如认证失败或无效输入。 |
| History Coverage Known | 1 表示持久业务统计历史有可信起点；0 表示覆盖起点未知，常见于升级旧控制状态。0 不代表当前采集无效。 |
| Statistics Started At | 可信业务统计历史起点。仅 History Coverage Known=1 时导出；未知时显示 Unknown coverage start，不能凭部署时间补造。 |
| Current Impact Query Boundary | 文本说明：私有 Coordinator `/observability/environments` 查询当前保留 Environment 的最新中断摘要；include_resolved 可包含已恢复，operation_unknown 可筛选节点丢失时的在途操作。删除或后一次中断会改变覆盖，不能据此声称完整任意历史窗口去重统计。 |

## ADX Environment Logs：日志与 Trace

| 面板 | 含义及读法 |
| --- | --- |
| Environment Logs | 沙箱主进程 stdout/stderr。Runtime ID 包含 Environment ID 与 generation；正则 `.*` 匹配全部，`.*environment-id.*` 匹配对应各代。文本过滤区分大小写，每次最多 500 行。SDK 命令响应是另一条通道。 |
| Environment Create Completion Traces | 采样到的 environment.create 业务 span，展示最终 outcome 与创建完成耗时。成功也可能是复用；unknown 不是确定失败。 |

## ADX Environments：实例明细

| 面板 | 含义及读法 |
| --- | --- |
| Environment Inventory | 当前 Running/Paused 逻辑库存关联新鲜运行时样本，不是历史创建列表。删除全部实例后无行正常。 |
| Environment CPU Usage | 每 Environment 的实际 CPU 核数，要求有效 Running 样本与至少两次采样。 |
| Environment Memory Usage | 每 Environment 的实际内存；暂停、删除、过期样本不冒充当前用量。 |

## ADX Data Plane：HTTP 与连接

| 面板 | 含义及读法 |
| --- | --- |
| Ingress Requests (selected range) | 共享 Ingress 按路由统计的 HTTP 请求，包含控制与用户数据转发，不局限于创建。 |
| Ingress Responses by Class (selected range) | **表格**：所选范围内按集群、部署环境、HTTP 类别分组的响应数量。1xx 包含成功的 WebSocket 101；旧版本把 101 归入 other。SSE 200 可以在最终业务失败之前返回。 |
| Ingress 4xx / 5xx Ratio (selected range) | 所选范围内 HTTP 客户端/服务端错误比例，不包含仍返回 HTTP 200 的 SSE 最终业务错误。 |
| Ingress Response Header Latency P50 / P95 / P99 | 获取响应头的耗时分位数；与创建完成、整条流存活时间不同，空闲窗口无有效分位数。 |
| Ingress Requests In Flight | HTTP 请求生命周期内在途数；长连接同时参考 session/relay。 |
| Ingress Backend Pool Idle Connections | 当前可复用的空闲上游连接数；0 本身不代表后端故障。 |
| Ingress Backend Pool Events (selected range) | 连接新建、复用、移除等连接池行为，不是请求成功/失败统计。 |
| Relay Active Streams by Node | 按目标节点统计当前 Relay 流数；流、连接与逻辑 Environment 数不同。 |
| Relay Connections / Errors (selected range) | Relay 传输连接活动与失败，不是创建结果。 |
| Relay Rejections / Route Errors (selected range) | Relay 拒绝与路由查找错误；需看 reason，不能全部归为运行时失败。 |
| Ingress Sessions / Physical Connections | 逻辑 session 与物理 HTTP/2 连接对比；多路复用使多个 session 共享一条连接。 |
| Ingress Requests over 100 ms (selected range) | 响应头耗时超过 100ms 的占比，不是创建超过 100ms 的占比。 |
| Ingress Traffic (selected range) | 公网入口连接 TLS 解密后的接收/发送字节数，覆盖 HTTP、CONNECT 与 WebSocket，包含 HTTP 头及帧。自动按 B/KiB/MiB/GiB 展示。 |
| Relay Traffic (selected range) | Relay 到运行时 / 从运行时返回的负载字节数，包含仍在传输的流与协议帧。与 Ingress 是不同跳的观测，不可相加作为业务总流量。 |

计数与流量使用 `increase(counter[$__range])`，先按原始生产者处理重启清零，再汇总。Prometheus 按采样窗口外推，数量可能有小数；短于两次抓取的窗口无法可靠计算。流量不包含 TLS 记录、IP 与链路层开销。生产者尚未升级或未成功抓取时，面板应显示缺数据，不能补成零流量。

流量计数不复制正文、不额外发送 RPC、不打印逐包日志。Ingress 在现有读写返回时更新每连接 relaxed 原子计数；Relay 复用已有每流计数。登记与回收仅在连接建立/关闭时加锁，抓取时汇总活动连接；转发每个数据块不获取共享锁。

## Process Resources：组件进程资源

| 面板 | 含义及读法 |
| --- | --- |
| CPU — cluster total (cores) | 采集进程 user+system CPU 秒/秒之和；1 表示一个逻辑核，不是节点 CPU 百分比。 |
| Memory — cluster total (bytes) | 新鲜进程样本的 RSS 总和；虚拟地址空间另列。 |
| Open file descriptors — cluster total | 打开 FD 数总和，可对比压测/反复创建前后；没有采集进程 FD 上限，因此不推导使用率。 |
| Threads — cluster total | 新鲜进程线程数总和。按 15 秒采样、45 秒新鲜度门槛，退出 PID 的旧样本会退出汇总。 |
| Processes by Pod | 展开 Pod 查看进程；Node/Namespace 表示位置，Component/PID 表示身份，列出 CPU、RSS、FD、线程、存活时间、虚拟内存等。仅保留新鲜样本。 |
