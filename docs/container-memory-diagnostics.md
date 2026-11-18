# 容器内存诊断手册

线上「越用越慢」「容器把内存吃满」时，如何定位是哪块内存、什么时候涨的、以及怎么回收。

本文以一次真实排查为例（app 容器涨到 6.3 GB），给出可复用的测量步骤与判读标准。部署方式见 [deploy-mac-mini.md](./deploy-mac-mini.md)，网络层变慢见 [latency-diagnostics.md](./latency-diagnostics.md)。

> 文中数字来自 2026-11-18 对该项目 Mac mini 部署（Docker Desktop，VM 内存 8 GB）的实测，仅作基线参考。

## 一、先分清「谁占的」

容器内存有两类完全不同的来源，处理方式也不同：

| 来源 | 表现 | 常见原因 |
| --- | --- | --- |
| 镜像/权重文件映射 | `RssFile` 高，`grep onnx /proc/<pid>/maps` 有结果 | 模型文件被 `mmap`，属可回收的页缓存 |
| 进程堆分配 | `RssAnon` 高，`maps` 里没有模型文件 | 推理中间张量、内存池、缓存，**不会自动归还** |

一条命令就能区分（`docker compose exec <svc> sh -c`）：

```bash
cat /proc/1/status | grep -E "VmRSS|RssAnon|RssFile|VmSwap"
grep -oE "/root/\.rembg[^ ]*\.onnx" /proc/1/maps | sort -u
ls -l /proc/1/fd | grep -c onnx
cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.peak
```

判读规则：

- `RssAnon` 占大头、`maps` 里没有模型 → **堆内存问题**，看下面第二、三节；
- `RssFile` 占大头 → 权重映射，属正常缓存，压缩容器内存收益很小；
- `VmSwap` 明显大于 0 → 内存已经不够，**整机变慢通常从这里开始**。

本次实测：`VmRSS 6328968 kB`、`RssAnon 6327872 kB`、`RssFile 1652 kB`，而 `maps` 里没有任何 onnx 文件。结论：不是权重映射，是堆内存。

## 二、找到是哪条代码路径

container 内存不会自己涨，一定是某条请求路径写的。定位方法：

1. 记下当前 `docker stats` 的数值；
2. **重启容器**，读空载基线；
3. 只触发一个待排查的功能，再读一次；

```bash
docker compose restart app
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" ai-retouch-agent-app-1   # 空载
curl -sS -o /dev/null -w "%{http_code} %{time_total}s\n" \
  -X POST -H "cookie: session=<token>" \
  http://127.0.0.1:7302/api/sessions/<id>/selection/prepare                          # 触发点选预热
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" ai-retouch-agent-app-1   # 再看
```

本次实测：

| 状态 | app 内存 |
| --- | --- |
| 重启后空载 | 175 MiB |
| 触发一次点选预热（`selection/prepare`） | **3.56 GiB** |

一步就能锁定：**画布点选**载入 SAM（`app/edits/segment.py`），会话存在模块级全局变量里，因此常驻 uvicorn 进程。拆分图层的抠图模型跑在 worker（`queued=True`），所以 worker 只占约 1 GB——**两个模型分工不同，别看到「大内存」就以为是同一处**。

## 三、判断内存是「一次到位」还是「持续累积」

这是最容易被忽略的一步。固定占用可以靠加内存解决，持续累积则加多少都会被吃光。

在容器内连续处理多张不同图片，观察每张之后的峰值：

| 处理的图片 | 内存池开启（默认） | 内存池关闭 |
| --- | --- | --- |
| 第 1 张 | 3607 MB | 3479 MB |
| 第 2 张 | **6641 MB** | 3482 MB |
| 第 3 张 | 6641 MB | 3482 MB |

规律：只要**换了图片**，峰值就往上跳一档，然后停住；处理 3 张就顶到 6.6 GB。

原因是 onnxruntime 默认开启 CPU 内存池（`enable_cpu_mem_arena`）。池按会话内遇到的**最大张量尺寸**扩容，扩了就不还，所以「图片数」和「画布尺寸」共同决定占用上限，而不是当前只处理一张。

## 四、两种修法（都要做）

### 1. 关掉内存池，把上限压平

```python
import onnxruntime as ort

options = ort.SessionOptions()
options.enable_cpu_mem_arena = False
session = new_session("sam", sam_quant=True, sess_opts=options)
```

实测 6.6 GB → 3.5 GB，且**不再随图片数增长**；推理耗时反而略降（1.8~1.9 s，开启时 2.0~2.5 s）。

### 2. 闲置后释放会话

关掉内存池后仍有约 3.5 GB 常驻。让会话在闲置一段时间后释放，用「下次进入点选多等一次加载」换「平时不占内存」。两个实现要点：

- **只在没有推理进行时释放**：并发请求共用同一个会话，直接置空会把别的线程正在用的模型关掉；
- **`gc.collect()` 放在锁外**：大对象回收耗时，别阻塞排队的请求。

释放后首次点选的代价：重新加载模型约 0.5 s + 重算 embedding 约 2.8 s（日志里能观察到 `selection/prepare` 变慢，属预期）。

### 3. 不推荐：只是把 Docker VM 内存调大

Mac mini 物理内存 16 GB，把 VM 从 8 GB 调到 12 GB 能缓解，但**不改变「随图片数累积」的规律**，只是把撞墙时间推后。优先做前两条。

## 五、不要踩的坑

- **别用宿主机的 `docker stats` 之外的手段猜**：容器内 `ps` 可能不存在，用 `/proc/<pid>/status`；
- **`memory.peak` 是历史峰值**，不会因为负载下降而回落，判断当前占用要看 `memory.current`；
- **容器内跑分析脚本要传文件**，别用 `ssh 'docker exec -i ... <<PY'` 套 heredoc：引号会在多层 shell 里被吃掉，出现 `[arena=on is not defined]` 这类诡异报错；
- **测速要留意自己的代理**：从本地 `curl` 线上，若流量走 VPN，`cf-ray` 会指向海外节点，测出的延迟和带宽都不代表国内真实链路（本次 cf-ray 落在 AMS，测速结论作废，改在服务器本机测）；
- **signed URL 每次都不一样**，别用它判断对象存储的缓存命中率。

## 六、改动后的验证清单

```bash
# 单测：不加载模型，覆盖释放与并发保护
cd backend && uv run pytest tests/test_edits.py -q -k release_idle

# 线上：重启后空载 vs 触发一次点选
docker compose restart app
docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" ai-retouch-agent-app-1
```

验收标准：空载回到百兆级；连续点选多张画布后，内存**稳定在一个平台值**而不是逐张上涨。

## 关键文件

| 文件 | 关注点 |
| --- | --- |
| `backend/app/edits/segment.py` | SAM 会话创建、embedding 缓存、闲置释放 |
| `backend/app/main.py` | 闲置回收任务的启动与取消 |
| `backend/app/edits/pixels.py` | 抠图模型选择与 auto 降级（跑在 worker） |
| `docker-compose.yml` | 容器内存共用同一个 Docker VM，需按总和规划 |
