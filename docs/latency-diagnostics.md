# 访问延迟诊断手册

线上访问慢时，如何判断瓶颈在**代码**、在**服务器**、还是在**网络链路**。

本文只讲测量方法和判读标准，不绑定具体优化结论。项目部署方式见 [deploy-mac-mini.md](./deploy-mac-mini.md)，机器常驻配置见 [macmini-as-cloud-server.md](./macmini-as-cloud-server.md)。如果服务端本身就慢，先按 [container-memory-diagnostics.md](./container-memory-diagnostics.md) 排除容器内存被吃满（内存不足会触发换页，表现为整机变慢）。

> 文中所有数字来自 2026-11-17 对该项目 Cloudflare Tunnel 部署的实测，仅作基线参考。

## 核心思路：分层测量，逐层排除

慢只有三种可能，必须分开测才能定位：

```text
① 应用层  ── 服务器上直接打接口，多久？
② 传输层  ── 同一个接口，从外部打，多久？
③ 链路层  ── 网络本身 RTT 多少、走了哪些节点？
```

判定规则很简单：

| ① 服务端 | ② 公网 | 结论 |
| --- | --- | --- |
| 快 | 快 | 没问题 |
| 快 | 慢 | **网络链路问题**，改代码无效 |
| 慢 | 慢 | 应用/数据库问题，与网络无关 |

**最常见的误判**是跳过 ①，直接看公网慢就去优化代码——但如果 ① 只有 3ms，把代码优化到 1ms 对总耗时毫无意义。

## 一、测服务端基线

在服务器上直接访问，绕过所有网络。

```bash
# 基础连通性与首页
curl -s -o /dev/null -w "ttfb=%{time_starttransfer}s total=%{time_total}s size=%{size_download}B\n" \
  --max-time 15 http://127.0.0.1:7302/

# 健康检查
curl -s -o /dev/null -w "total=%{time_total}s\n" http://127.0.0.1:7302/api/health
```

逐接口测：

```bash
for ep in /api/health /api/auth/me /api/sessions /api/assets /api/assets/library; do
  printf "%-24s " "$ep"
  curl -s -o /dev/null -w "%{time_total}s http=%{http_code}\n" \
    --max-time 20 -H "Cookie: session=$TOKEN" "http://127.0.0.1:7302$ep"
done
```

带鉴权的接口需要一个合法会话，见文末[附录](#附录只读鉴权测量)。

**判读**：本项目服务端所有接口在 **2~6ms**。如果测出来是几十上百毫秒，才需要看数据库查询、序列化、N+1 这类应用层问题。

## 二、测公网对比

用同样的接口，从外部（最好是发起的机器）打公网域名。

```bash
for ep in /api/health /api/auth/me /api/sessions /api/assets; do
  printf "%-24s " "$ep"
  curl -s -o /dev/null \
    -w "total=%{time_total}s tcp=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s\n" \
    --max-time 30 -H "Cookie: session=$TOKEN" "https://app.x-pages.cc.cd$ep"
done
```

**关键**：如果①和②差距是几十倍以上，问题 100% 在网络，与应用无关。

本项目实测：服务端 2~6ms，公网 **1.5~3.5s**，差距约 500~1000 倍。逐接口对比见[实测基线](#九本项目实测基线2026-11-17)。

## 三、拆解时间都花在哪

`curl -w` 的输出字段含义：

| 字段 | 含义 | 异常表现 |
| --- | --- | --- |
| `time_namelookup` | DNS 解析 | 偶发上百毫秒说明 DNS 不稳 |
| `time_connect` | TCP 三次握手完成 | 接近一个 RTT 属正常 |
| `time_appconnect` | TLS 握手完成 | 减去 connect 即 TLS 开销，通常 1~2 RTT |
| `time_starttransfer` | 首字节到达（TTFB） | 减去 appconnect 即服务端处理 + 回程 |
| `time_total` | 整个请求完成 | 用于判断传输是否被限速 |

典型拆分方法：

```text
TCP 建连     = time_connect                        → 1 个 RTT
TLS 握手     = time_appconnect - time_connect       → 1~2 个 RTT
服务端+回程  = time_starttransfer - time_appconnect → 应接近 0
传输剩余     = time_total - time_starttransfer      → 大文件才明显
```

**如果 TLS 占了大头**，说明问题在握手往返，优化方向是连接复用与 HTTP/3，而非业务代码。

本项目实测（连续 5 次全新连接）：

```text
tcp=0.23s  tls=0.50s  ttfb=1.52s
tcp=0.25s  tls=0.53s  ttfb=1.52s
tcp=0.19s  tls=0.41s  ttfb=1.65s
```

握手约 0.7s，占单次请求近一半。完整 5 次记录见[实测基线](#九本项目实测基线2026-11-17)。

## 四、测链路质量

### RTT 与丢包

```bash
# 隧道边缘地址
nslookup region1.v2.argotunnel.com
ping -c 5 <上述解析出的 IP>

# 或直接测应用域名（走 anycast，测的是入口边缘）
ping -c 5 app.x-pages.cc.cd
```

**判读**：

- RTT 稳定、0% 丢包 → 延迟高就是物理距离
- 有丢包或 RTT 抖动大 → TCP 会触发重传，实际耗时远超 RTT

### 路由路径

```bash
traceroute -n -w 1 -q 1 -m 20 app.x-pages.cc.cd
```

**重点看延迟在哪一跳突然跳变**，那就是跨洋/跨境的位置。

本项目实测：

```text
 6  202.97.65.157    24ms    ← 国内骨干
 8  202.97.39.189    24ms
10  218.30.54.214   167ms    ← 此处跨洋
```

到边缘 RTT avg **224ms**，0% 丢包。

## 五、确认隧道连到了哪个边缘

Cloudflare Tunnel 的边缘节点由 anycast 决定，**取决于出口 IP 的路由，不是地理位置**。国内网络经常被路由到很远的节点。

```bash
# 隧道连接状态（需要隧道 ID 或名称）
cloudflared tunnel info <隧道ID>
```

输出中的 `EDGE` 一列即边缘代号，例如：

```text
EDGE
2xlax01, 1xlax10, 1xlax12
```

常见代号：

| 代号 | 位置 | 代号 | 位置 |
| --- | --- | --- | --- |
| `lax` | 洛杉矶 | `hkg` | 香港 |
| `sjc` | 圣何塞 | `nrt` | 东京 |
| `sea` | 西雅图 | `sin` | 新加坡 |
| `ams` | 阿姆斯特丹 | `fra` | 法兰克福 |

### 确认浏览器/客户端从哪个边缘进入

```bash
curl -s https://<你的域名>/ -D - -o /dev/null | grep -i cf-ray
# cf-ray: xxxxx-HKG   ← 后缀即入口边缘

# 对照：普通 Cloudflare 域名走哪个边缘
curl -s https://cloudflare.com/cdn-cgi/trace | grep -E '^(ip|loc|colo)='
```

**这两者不一致是重要线索**：说明该域名的 anycast 前缀被路由到了较远节点。本项目实测域名走 **AMS**，而 `cloudflare.com` 走 **LAX**。

### 完整路径重建

把上面三块拼起来：

```text
客户端 ──► 入口边缘(cf-ray 后缀) ──► CF 骨干 ──► 隧道所在边缘(EDGE) ──► 公网 ──► 源站
```

如果入口边缘和隧道边缘**都在海外**，路径就有两次跨洋，延迟必然高。这种情况只能靠更换接入方式解决，代码层面无解。

## 六、静态资源单独测

静态资源有 CDN 缓存，行为与 API 不同，要分开测。

```bash
# 注意：必须带 --compressed，否则测到的是未压缩体积
curl -s --compressed -o /dev/null \
  -w "ttfb=%{time_starttransfer}s total=%{time_total}s size=%{size_download}B speed=%{speed_download}B/s\n" \
  --max-time 90 "https://app.x-pages.cc.cd/assets/index-xxxx.js"

curl -s --compressed -D - -o /dev/null \
  --max-time 90 "https://app.x-pages.cc.cd/assets/index-xxxx.js" \
  | grep -i -E 'content-encoding|cf-cache-status|cache-control|age'
```

**判读要点**：

| 响应头 | 含义 |
| --- | --- |
| `cf-cache-status: HIT` | 边缘已缓存，不回源；但仍受边缘距离影响 |
| `cf-cache-status: DYNAMIC` | 未缓存，每个请求都回源；API 正常应为此值 |
| `content-encoding: gzip/br` | 已压缩；若缺失且体积大，需检查压缩配置 |
| `cache-control: max-age=...` | 带哈希文件应设长缓存 + `immutable` |

本项目实测：

```text
index.js   935,129B → gzip 后 286,983B（约 1/3）
           无压缩 total=10.7s，带压缩 total=2.07s
cf-cache-status: HIT
cache-control: max-age=14400   ← 仅 4 小时，可延长
```

完整的静态资源测量（含 CSS、HTML）见[实测基线](#九本项目实测基线2026-11-17)。

## 七、常见陷阱

这些都是实际踩过的坑，会导致误判。

| 陷阱 | 后果 | 正确做法 |
| --- | --- | --- |
| `curl` 不带 `--compressed` | 测到未压缩体积，结论偏大约 3 倍 | 加 `--compressed` |
| 用 `command -v xxx` 判断工具是否安装 | 非交互 SSH 的 `PATH` 只有 `/usr/bin:/bin:/usr/sbin:/sbin`，找不到 Homebrew | 用绝对路径 `ls -l /opt/homebrew/bin/xxx` |
| `df -h /` 看磁盘占用 | 只显示系统快照卷，严重低估 | 看 `/System/Volumes/Data` 或 `diskutil apfs list` |
| 只测一次就下结论 | 国际链路抖动大，单次不可信 | 连续 3~5 次取中位数 |
| 忽略 TCP 连接复用 | 每次都算上握手，高估延迟 | 明确区分「首次连接」与「复用连接」 |
| 看到 cf-ray 与自己预期不符就断定用了代理 | 可能是 ISP 的 anycast 路由问题 | 用 `cloudflare.com/cdn-cgi/trace` 与默认路由交叉验证 |

## 八、优化手段对照

按「对哪一层有效」归类，避免用错方向。

| 手段 | 作用层 | 预期收益 | 成本 |
| --- | --- | --- | --- |
| 合并/并发前端请求 | 应用层 | 每减少一次串行往返省一个 RTT+处理 | 改代码 |
| 增加数据库索引、消除 N+1 | 应用层 | 仅当服务端本身慢时有效 | 改代码 |
| 静态资源长缓存 + `immutable` | 传输层 | 回访不再下载资源 | 改配置 |
| 开启 Brotli | 传输层 | 比 gzip 再省 15~20% | 面板开关 |
| 开启 HTTP/3 | 传输层 | 握手从 2 RTT 降到 1 RTT | 面板开关 |
| 连接复用 / keep-alive | 传输层 | 省掉重复握手 | 客户端配置 |
| Cloudflare Argo 智能路由 | 链路层 | 跨洋场景约 20~40% | 付费 |
| 香港/新加坡 VPS 中转 | 链路层 | 可降到 100ms 内 | VPS + 维护 |
| 代理改变隧道出口 | 链路层 | 不确定，需实测 | 稳定性风险 |

**优先级原则**：先测出瓶颈在哪一层，再选对应手段。链路层问题用应用层手段优化，收益接近零。

## 九、本项目实测基线（2026-11-17）

以下为该项目 Cloudflare Tunnel 部署的完整测量记录，可作为以后对比的参照。

### 环境

| 项 | 值 |
| --- | --- |
| 源站 | Mac mini M4，macOS 27.2.1，上海（出口 IP `59.173.216.250`） |
| 部署方式 | Docker Compose `deploy` profile，服务监听 `127.0.0.1:7302` |
| 接入 | Cloudflare Tunnel（Token 模式），隧道 `Mac-mini-m4` |
| 测量位置 | 从 Mac mini 本机发起（既测源站，也测公网回环） |

### ① 服务端 vs 公网：同一批接口

先看本地直连，再看同一接口走公网。

| 接口 | ① 服务端本地 | ② 公网 | 倍数 |
| --- | --- | --- | --- |
| `/api/health` | **2.9 ms** | 3530 ms | ~1200× |
| `/api/auth/me` | **2.0 ms** | 2045 ms | ~1000× |
| `/api/sessions` | **2.5 ms** | 2694 ms | ~1080× |
| `/api/assets` | **3.7 ms** | 2568 ms | ~690× |
| `/api/assets/library` | **5.4 ms** | 2159 ms | ~400× |

**结论**：所有接口服务端处理都在 **2~6ms**。差距全部产生在网络链路上，优化业务代码对总耗时没有实际影响。

### ② 公网请求的时间分解

| 接口 | TCP 建连 | TLS 握手 | TTFB | 总计 |
| --- | --- | --- | --- | --- |
| `/api/health` | 2243 ms | 2501 ms | 3530 ms | 3530 ms |
| `/api/auth/me` | 205 ms | 424 ms | 1280 ms | 2045 ms |
| `/api/sessions` | 248 ms | 1509 ms | 2385 ms | 2694 ms |
| `/api/assets` | 1215 ms | 1439 ms | 2568 ms | 2568 ms |
| `/api/assets/library` | 212 ms | 1326 ms | 2159 ms | 2159 ms |

**注意方差极大**：TCP 建连在 205ms 到 2243ms 之间跳动。正常应为 1 个 RTT（约 224ms），出现 1.2~2.2 秒说明**发生了 TCP 重传**（macOS 初始 RTO 为 1 秒）。这比单纯的物理延迟更致命。

### ③ 连接复用后的稳定表现

连续 5 次全新连接测同一接口：

| 次数 | TCP | TLS | TTFB |
| --- | --- | --- | --- |
| 1 | 234 ms | 1405 ms | 2312 ms |
| 2 | 194 ms | 407 ms | 1654 ms |
| 3 | 251 ms | 516 ms | 1510 ms |
| 4 | 255 ms | 527 ms | 1516 ms |
| 5 | 243 ms | 502 ms | 1762 ms |

**结论**：TCP 稳定在 ~230ms（≈RTT），TLS 稳定在 ~500ms（≈2 RTT），TTFB 稳定在 1.5~1.7s。说明**握手约占 0.7 秒**，其中 TLS 的 2 个 RTT 可通过 HTTP/3 压缩到 1 个。

### ④ 静态资源

| 资源 | 原始体积 | 传输体积 | TTFB | 总计 | 速度 |
| --- | --- | --- | --- | --- | --- |
| HTML（SPA 外壳） | 711 B | 711 B | 1330~2298 ms | 1648~2299 ms | — |
| JS（未压缩） | 935,129 B | 935,129 B | 3225 ms | **10,706 ms** | 87 KB/s |
| JS（gzip） | 935,129 B | **286,983 B** | 1024 ms | **2069 ms** | 139 KB/s |
| CSS | 115,613 B | 115,613 B | 2254 ms | 3385 ms | 34 KB/s |

同一 JS 文件在服务端本地取用：**15.8 ms**（935,129 B）。

查看的响应头：

```text
/assets/index.js     cf-cache-status: HIT    cache-control: max-age=14400    content-encoding: gzip
/                    cf-cache-status: DYNAMIC
alt-svc: h3=":443"; ma=86400
```

**要点**：

- 压缩与否相差 **5 倍**（10.7s → 2.07s），必须带 `--compressed` 测
- 带哈希的静态资源只设了 4 小时缓存，未加 `immutable`
- `alt-svc` 已公告 HTTP/3，但需客户端实际协商

### ⑤ 链路质量

```text
ping 198.41.192.37（argotunnel 边缘）
5 packets, 0.0% packet loss
min/avg/max/stddev = 206.553/224.075/249.196/14.870 ms
```

RTT 约 **224 ms**，无丢包。

路由路径（关键跳点）：

```text
 1  192.168.1.1        2.9 ms     ← 家庭网关
 2  59.173.216.249    10.0 ms
 4  172.29.77.133      8.5 ms
 6  202.97.65.157     24.0 ms     ← 国内骨干（电信国际出口）
 7  202.97.24.190     23.9 ms
 8  202.97.39.189     24.0 ms
10  218.30.54.214    166.9 ms     ← 跨洋跳变：24ms → 167ms
11  141.101.72.141   166.7 ms     ← 进入 Cloudflare
```

### ⑥ 边缘节点分布

| 对象 | 实际位置 |
| --- | --- |
| 隧道连接（`cloudflared tunnel info` 的 EDGE） | `2xlax01`, `1xlax10`, `1xlax12` → **洛杉矶 LAX** |
| 访问 `app.x-pages.cc.cd` 的入口（`cf-ray` 后缀） | **AMS（阿姆斯特丹）** |
| 访问 `cloudflare.com` 的入口（`cdn-cgi/trace`） | `colo=LAX`, `loc=CN`, `ip=59.173.216.250` |

**这是最关键的发现**：同一网络访问不同 Cloudflare 域名时，入口边缘不一致——自己的域名被路由到阿姆斯特丹，`cloudflare.com` 走洛杉矶。重建完整路径：

```text
浏览器(上海) ──► AMS(阿姆斯特丹) ──► LAX(洛杉矶) ──► 隧道 ──► Mac mini(上海)
                224ms RTT            CF 骨干          公网回程
                       ↑                  ↑
                  两次跨洋，路径被拉长
```

这是 Cloudflare 社区中记录过的 anycast 前缀错配现象，`cloudflared` 选节点不按地理位置而是按网络路由，国内网络容易被分配到 SJC/LAX/HKG 等远端节点。

**由此得出的判断**：单次 API 请求 2 秒 = 握手 ~0.7 秒 + 两次跨洋往返 + 重传。既不是代码问题，也不是 Mac mini 性能问题。在链路层不变的前提下，最有效的优化是**减少请求次数**和**减少握手次数**。

## 附录：只读鉴权测量

测带鉴权的接口需要一个合法会话。为避免污染数据，可以**铸造一个只读令牌**，只发 GET 请求。

在服务器上执行（容器内用虚拟环境的 Python）：

```bash
# 1. 取一个已有用户的 ID（只读查询）
docker compose --profile deploy exec -T postgres \
  psql -U retouch -d retouch -t -A -c "select id from users limit 1;"

# 2. 用应用自身的签名逻辑铸造令牌
TOKEN=$(docker compose --profile deploy exec -T app \
  /app/backend/.venv/bin/python -c "
import uuid
from app.security import issue_token
print(issue_token(uuid.UUID('<上一步的用户 ID>')))
" | tr -d '\r')

# 3. 带上 Cookie 测接口
curl -s -o /dev/null -w "%{time_total}s\n" \
  -H "Cookie: session=$TOKEN" http://127.0.0.1:7302/api/auth/me
```

> **注意**：容器内必须用 `/app/backend/.venv/bin/python`，直接用系统 `python3` 会报 `ModuleNotFoundError: pydantic_settings`（依赖装在虚拟环境里）。
>
> 该令牌具备完整权限，仅用于本地只读诊断，不要写入脚本或日志，用完随进程丢弃。

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [deploy-mac-mini.md](./deploy-mac-mini.md) | 部署流水线与故障排查 |
| [macmini-as-cloud-server.md](./macmini-as-cloud-server.md) | Mac mini 常驻与内网穿透配置 |
