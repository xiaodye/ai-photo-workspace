# 把 Mac mini 变成常驻云服务器 / 云电脑

本文讲怎么让一台 **Mac mini** 长期无人值守地跑服务，或在外网像云电脑一样远程操作它。

Mac mini 是 Apple 目前在售机型里唯一适合常驻的：无电池、无内建屏幕、可长期接管电源，散热与噪音也适合放在角落。笔记本类机型合盖会强制休眠、依赖电池，不适合作为服务器，本文不展开。

不绑定具体项目。本仓库的部署流程见 [deploy-mac-mini.md](./deploy-mac-mini.md)，本文只解决它依赖的**基础设施**：不断电、不休眠、开机自启、安全的内网穿透入口。

> 本文所有命令均在 macOS 27 上验证过语法。标记「需 root」的命令要用管理员账户执行。

## 目标与拆解

一个「云服务器」要同时满足四件事，缺一不可：

| 维度 | 问题 | 本文对应章节 |
| --- | --- | --- |
| 可用性 | 断电/崩溃后能自己起来吗？ | [断电重启](#断电重启)、[定时重启](#定时重启) |
| 在线性 | 没人操作时会休眠断网吗？ | [防休眠](#防休眠) |
| 可达性 | 外网怎么连进来？ | [内网穿透](#内网穿透-cloudflare-tunnel) |
| 安全性 | 连进来的门是不是敞开的？ | [安全加固](#安全加固) |

## 确认机器与系统环境

先记录基线，后面每一步都基于它：

```bash
system_profiler SPHardwareDataType | grep -E 'Model Name|Model Identifier|Chip|Memory'
sw_vers
pmset -g custom
```

Apple Silicon（M 系列）与 Intel 的 Mac mini 在电源管理和常驻方式上有差异，下文会在涉及处标注。**Intel 机型已停产且不支持最新的 macOS 大版本**，新部署建议用 Apple Silicon。

## 防休眠

休眠会断网、停掉所有服务，是常驻服务器的头号敌人。

### 查看当前电源策略

```bash
pmset -g custom
```

关注两个值：

- `sleep`：系统休眠倒计时（分钟，`0` 表示不休眠）
- `disksleep`：硬盘休眠倒计时

### 永久关闭休眠（需 root）

Mac mini 没有电池，`-c`（接通电源）与 `-a`（所有电源模式）等价，统一用 `-a`：

```bash
sudo pmset -a sleep 0 disksleep 0 powernap 0 displaysleep 10
```

| 参数 | 含义 |
| --- | --- |
| `sleep 0` | 系统永不休眠 |
| `disksleep 0` | 磁盘永不休眠 |
| `powernap 0` | 关闭 Power Nap，避免后台被唤醒或重复唤醒 |
| `displaysleep 10` | 屏幕 10 分钟后关闭，不影响服务运行；接显示器时可省电 |

> **注意**：`displaysleep` 只是关屏幕，不会让进程停摆。Mac mini 常年无显示器也不影响运行——但**首次装机与排障时需要接一台显示器**，否则无法完成初始化、自动登录等 GUI 设置。

### 临时阻止休眠（推荐用于部署窗口）

不想改全局策略时，用 `caffeinate` 包住一条命令：

```bash
caffeinate -dimsu <命令>
# 例：部署期间保持唤醒
caffeinate -dimsu docker compose --profile deploy up -d --build
```

| 标志 | 作用 |
| --- | --- |
| `-d` | 阻止显示器休眠 |
| `-i` | 阻止系统空闲休眠 |
| `-m` | 阻止磁盘休眠 |
| `-s` | 接通电源时阻止系统休眠 |
| `-u` | 模拟用户活动，保持会话活跃 |

`caffeinate -t 3600` 可指定持续秒数。

### 验证是否真的没在睡

```bash
pmset -g            # 看 SleepDisabled 与 sleep 值
pmset -g assertions # 看当前有哪些进程阻止了休眠
```

`pmset -g assertions` 的 `PreventUserIdleSystemSleep` 为 1 表示正被阻止。

## 断电重启

停电或崩溃后，机器必须能自动开机，否则「云」就断了。

### 硬件层：来电自启

这是**固件行为**，Mac mini 按芯片区分：

| 芯片 | 行为 |
| --- | --- |
| **Apple Silicon（M1/M2/M4）** | 无「来电自启」开关，默认**断电恢复后自动开机** |
| Intel Mac mini | 开机进入固件设置勾选「断电后自动启动」，或「系统设置 → 能源」中开启 |

```bash
# 崩溃后自动重启（需 root）
sudo pmset -a autorestart 1
```

验证：

```bash
pmset -g | grep autorestart
```

> **重要**：Apple Silicon 上真正的「来电自启」由固件决定且不可配置（默认开启），`pmset autorestart` 管的是**内核崩溃后自动重启**，两者不等价。要 100% 扛住市电波动与瞬间断电，最稳的还是给 Mac mini 接一台 UPS。

### 软件层：登录后自动拉起服务

开机只是第一步，服务还得自己起来。三种方式，按可靠性排序：

**① LaunchDaemon（系统级，最早启动，无需登录）**

适合系统服务（如 `cloudflared`、`sshd`）。放在 `/Library/LaunchDaemons/`，开机即启，不依赖任何用户登录。

**② LaunchAgent（用户级，需用户登录）**

适合用户态服务。放在 `~/Library/LaunchAgents/` 或 `/Library/LaunchAgents/`。**必须有人登录 GUI 会话才会运行**——这是常驻服务最常见的坑（见下节）。

**③ 登录项 / `docker compose` 的 restart 策略**

容器自身的可靠性交给编排层：

```yaml
services:
  app:
    restart: unless-stopped   # 崩溃或重启后自动拉起
```

配合 Docker Desktop 的「开机启动」，容器可在登录后自动恢复。

### 桌面会话的隐性依赖

**很多 GUI 能力（屏幕共享、Docker Desktop、依赖 Keychain 的操作）只在用户真正登录后可用。**

- 机器重启后停在登录窗口，`cloudflared` 若作为 LaunchAgent 就**不会启动**
- Docker Desktop 需要 GUI 会话才能提供 `docker` socket
- 任何访问钥匙串的操作（如拉取镜像）在无 GUI 会话时会报 `keychain cannot be accessed`

解法只有两个：

1. 让**必须常驻的服务走 LaunchDaemon**（不依赖登录）
2. 配置**自动登录**（系统设置 → 用户与群组 → 自动登录）

> 自动登录意味着物理接触机器即可进入系统，只有机器放在你能物理控制的场所时才建议开启，并且务必配合全盘加密（FileVault）。

### 验证服务自启

```bash
# 查看 LaunchDaemon 是否已加载并运行
sudo launchctl print system/<label> | head -20

# 查看退出码（0 = 正常运行，非 0 表示反复失败）
launchctl list | grep <label>
```

`launchctl list` 的中间列是上次退出码，`0` 或 `-` 才算健康。

## 定时重启

长期运行会累积内存碎片、文件句柄泄漏、`launchd` 状态异常，定期重启能显著降低「跑一周后莫名变卡」的概率。

### 方式一：`pmset` 定时开关机（推荐）

```bash
# 每天凌晨 4:00 重启
sudo pmset repeat restart MTWRFSU 04:00:00
```

| 字段 | 含义 |
| --- | --- |
| `restart` | 动作，也可用 `shutdown` / `wake` / `poweron` |
| `MTWRFSU` | 星期缩写：Mon Tue Wed Thu Fri Sat Sun |
| `04:00:00` | 24 小时制时间 |

只工作日重启：

```bash
sudo pmset repeat restart MTWRF 04:00:00
```

查看：`pmset -g sched`。取消：`sudo pmset repeat cancel`。

> `pmset repeat` 的重启是**优雅重启**，会给进程发终止信号。务必确认容器和服务都能在启动后自动恢复（见上一节）。

### 方式二：`launchd` 定时任务

需要更精细控制（比如重启前跑备份）时，用 LaunchDaemon 执行脚本：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.scheduled-restart</string>
    <key>ProgramArguments</key>
    <array>
        <string>/sbin/shutdown</string>
        <string>-r</string>
        <string>now</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

存为 `/Library/LaunchDaemons/local.scheduled-restart.plist`，然后：

```bash
sudo chown root:wheel /Library/LaunchDaemons/local.scheduled-restart.plist
sudo chmod 644 /Library/LaunchDaemons/local.scheduled-restart.plist
sudo launchctl bootout system /Library/LaunchDaemons/local.scheduled-restart.plist 2>/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/local.scheduled-restart.plist
```

> `launchctl load/unload` 是旧接口，macOS 新版本用 `bootstrap` / `bootout`。

### 重启前先检查

定时重启会打断正在跑的长任务。若服务里有长耗时的构建或队列，重启前应确认空闲：

```bash
# 例：只在没有活跃容器任务时才重启
if [ -z "$(docker ps -q --filter 'status=running' --filter 'name=worker')" ]; then
  /sbin/shutdown -r now
fi
```

## 内网穿透（Cloudflare Tunnel）

家庭宽带通常没有公网 IP，且多数运营商封锁 80/443。Cloudflare Tunnel 让 Mac **主动出站**连到 Cloudflare，无需任何端口映射，也无需公网 IP。

### 为什么选它

| 方案 | 公网 IP | 端口映射 | 天然 TLS | 适用 |
| --- | --- | --- | --- | --- |
| **Cloudflare Tunnel** | 不需要 | 不需要 | ✅ 自动 | 首选 |
| 路由器端口转发 + DDNS | 需要 | 需要 | 需自签 | 运营商可能封端口 |
| Tailscale / ZeroTier | 不需要 | 不需要 | ✅ | 纯私有组网，无公开域名 |
| frp / ngrok | 不需要 | 不需要 | 视服务 | 需另找中转服务器 |

### 安装

```bash
brew install cloudflared
cloudflared --version
```

### 登录并创建隧道

```bash
# 浏览器授权，写入证书到 ~/.cloudflared/
cloudflared tunnel login

# 创建命名隧道（名字自取）
cloudflared tunnel create mac-server

# 查看隧道列表与 ID
cloudflared tunnel list
```

创建后 `~/.cloudflared/` 下会有一个 `<隧道ID>.json` 凭据文件，**这是密钥，权限应为 600**。

### 配置路由

新建 `~/.cloudflared/config.yml`：

```yaml
tunnel: <隧道ID>
credentials-file: /Users/<用户名>/.cloudflared/<隧道ID>.json

ingress:
  # SSH：仅本机 sshd
  - hostname: ssh.example.com
    service: ssh://localhost:22
  # HTTP 服务
  - hostname: app.example.com
    service: http://localhost:8080
  # 兜底规则，必须存在且放最后
  - service: http_status:404
```

### 绑定 DNS

```bash
cloudflared tunnel route dns mac-server ssh.example.com
cloudflared tunnel route dns mac-server app.example.com
```

### 以常驻服务方式运行（关键）

**注意**：`cloudflared service install` 安装的是**用户级 LaunchAgent**（`launchctl` 的帮助原文是 "Install cloudflared as an user launch agent"），而不是 LaunchDaemon。差别很关键：

| | LaunchAgent（`service install`） | LaunchDaemon（手写 plist） |
| --- | --- | --- |
| 启动时机 | **用户登录 GUI 会话后** | 开机即启，无需登录 |
| 重启后无人登录 | ❌ 隧道不启动 | ✅ 正常启动 |
| 安装方式 | 一条命令 | 手写 plist |

所以：

- **机器会配置自动登录** → 用 `sudo cloudflared service install` 最省事
- **重启后停在登录窗口、无人登录** → 必须改用手写 LaunchDaemon，否则隧道永远起不来

一条命令安装（用户级）：

```bash
sudo cloudflared --config /Users/<用户名>/.cloudflared/config.yml service install
```

### 手写 LaunchDaemon（不依赖登录）

在 `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist` 写入：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.cloudflare.cloudflared</string>
    <key>ProgramArguments</key>
    <array>
        <string>/opt/homebrew/bin/cloudflared</string>
        <string>--no-autoupdate</string>
        <string>tunnel</string>
        <string>--config</string>
        <string>/etc/cloudflared/config.yml</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/var/log/cloudflared.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/cloudflared.err.log</string>
</dict>
</plist>
```

加载与验证：

```bash
sudo chown root:wheel /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo chmod 644 /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl bootout system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist 2>/dev/null
sudo launchctl bootstrap system /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl print system/com.cloudflare.cloudflared | head -20
```

> **路径要点**：`/opt/homebrew/bin/cloudflared` 是 Apple Silicon 的 Homebrew 路径，Intel Mac 为 `/usr/local/bin/cloudflared`。LaunchDaemon 以 root 运行，`config.yml` 和凭据文件必须对 root 可读，建议统一放到 `/etc/cloudflared/`（属主 `root:wheel`、权限 `600`）而不是用户家目录。
>
> `KeepAlive` 让进程崩溃后被自动重启，是常驻服务的必备项。

### 验证隧道

```bash
# 本机看隧道连接状态
cloudflared tunnel info mac-server

# 从外网验证（另找一台机器）
curl -I https://app.example.com
ssh -o ProxyCommand="cloudflared access ssh --hostname %h" user@ssh.example.com
```

## 云电脑：远程桌面

「云服务器」给机器用，「云电脑」给人用——需要图形界面。Mac 自带 **屏幕共享（VNC）**。

### 开启屏幕共享

系统设置 → 通用 → 共享 → **屏幕共享** 打开。

命令行方式（需 root，且 macOS 版本间有差异）：

```bash
sudo systemsetup -setremotelogin on          # 开 SSH
# 屏幕共享建议用 GUI 开关，命令行实现随版本变化
```

需要先执行 `sudo systemsetup -getremotelogin` 确认当前状态。

### 通过隧道暴露 VNC

在 `config.yml` 增加：

```yaml
  - hostname: screen.example.com
    service: tcp://localhost:5900
```

> **强烈建议**：VNC 不要直接暴露到公网。VNC 协议本身加密弱，必须套在 Cloudflare Access 或 SSH 隧道之后。

更安全的做法是 `localhost` 绑定 + SSH 端口转发：

```bash
ssh -L 5900:localhost:5900 user@ssh.example.com
# 然后本地用屏幕共享客户端连 localhost:5900
```

### 替代方案

| 方案 | 优势 | 代价 |
| --- | --- | --- |
| 屏幕共享 (VNC) | 系统自带，零成本 | 带宽开销大，延迟高 |
| **Sunshine + Moonlight** | 硬件编码，低延迟，适合操作 | 需额外安装配置 |
| Parsec | 体验好，云游戏级 | 商业服务 |
| Jump Desktop | 易用 | 付费 |

做日常编码/办公，VNC 够用；要流畅操作图形，选 Sunshine/Moonlight。

### 登录窗口陷阱

**屏幕共享连上后如果机器停在登录界面，你是看不到桌面内容的**，只能看到登录框。这就是为什么常驻机器通常要配置自动登录。

## 安全加固

暴露到公网后，默认配置基本都不够安全。

### SSH

```bash
# 1. 优先用密钥，禁用密码
# 编辑 /etc/ssh/sshd_config
PasswordAuthentication no
PermitRootLogin no
PubkeyAuthentication yes

# 2. 只允许特定用户
AllowUsers youruser

# 3. 重载
sudo launchctl kickstart -k system/com.openssh.sshd
```

> 改 `sshd_config` 前**先确认公钥登录可用**，否则禁用密码后可能把自己锁在门外。改完保持一个已连上的会话不关，另开窗口验证。

### Cloudflare Access

给隧道入口套一层身份验证，比裸奔强得多：

1. Zero Trust → Access → Applications → 新建应用，绑定 `ssh.example.com` / `app.example.com`
2. 策略选 `Allow` + `Emails`，只放行自己的邮箱
3. 浏览器访问会先跳转登录页，验证码/邮箱验证后才到服务

> CI 等非交互场景要用 **Service Auth** 策略 + Service Token，`Allow` 策略无法用于自动化。

### 防火墙与最小暴露

```bash
# 查看防火墙状态
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
# 打开
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
```

原则：**只让必要端口监听，且尽量绑 `127.0.0.1`**。服务若经隧道进入，根本不需要监听 `0.0.0.0`。

```bash
# 检查哪些端口在对外监听
sudo lsof -iTCP -sTCP:LISTEN -P -n | grep -v 127.0.0.1
```

### 数据安全

- **FileVault 全盘加密**必须开启（系统设置 → 隐私与安全性 → FileVault）。机器被盗时这是最后防线
- 自动登录 + FileVault 会形成矛盾（自动登录需要明文密钥），二者取舍需权衡
- 定期备份：`Time Machine` 或异地备份

## 长期维护

| 项目 | 建议 | 检查命令 |
| --- | --- | --- |
| 系统更新 | 关闭自动大版本升级，只打安全补丁 | `softwareupdate -l` |
| 磁盘空间 | 定期清理镜像/日志 | `df -h`、`docker system df` |
| 温度与降频 | Mac mini 注意通风 | `sudo powermetrics --samplers smc -n 1` |
| 进程健康 | 确认常驻服务存活 | `launchctl list`、`docker ps` |
| 日志 | 排查历史问题 | `log show --last 1h --predicate 'process == "cloudflared"'` |

### 监控建议

无人值守的机器需要能主动告警：

- 外部探活：用 Cloudflare Health Checks 或第三方监控定期访问健康检查端点
- 简单脚本：`curl --fail` 失败时发通知

## 完整落地清单

按顺序执行，每步验证后再继续：

```text
① 确认 Mac mini 型号与电源策略 → pmset -g custom
② 关闭休眠（插电时）          → sudo pmset -a sleep 0 disksleep 0
③ 开启崩溃自动重启            → sudo pmset -a autorestart 1
④ 确认来电自启（固件/UPS）    → Apple Silicon 默认开启，建议加 UPS
⑤ 开启 SSH                    → 系统设置 → 共享 → 远程登录
⑥ 安装并配置 Cloudflare Tunnel → cloudflared tunnel create
⑦ 隧道常驻（二选一）         → service install（需自动登录）
                               或 手写 LaunchDaemon（无需登录）
⑧ 套 Cloudflare Access 策略   → Zero Trust → Access
⑨ 配置定时重启                → sudo pmset repeat restart MTWRFSU 04:00:00
⑩ 开启 FileVault 与防火墙     → 系统设置
⑪ 自动登录（可选，权衡安全）  → 系统设置 → 用户与群组
⑫ 验证：断电模拟、外网访问、重启后服务自恢复
```

### 最终验收

真正可靠的部署要能通过这三个测试：

1. **拔电测试**：直接断电，恢复供电后确认自动开机且服务能访问
2. **重启测试**：`sudo reboot`，确认无需人工干预即可恢复
3. **外部测试**：用另一台机器（最好走移动网络）验证 SSH / HTTP / 远程桌面均可用

任何一项需要人工介入，都说明还有环节没配好。

## 常见误区

| 误区 | 事实 |
| --- | --- |
| 「LaunchAgent 开机就会跑」 | 需要用户登录 GUI 会话才运行 |
| 「`cloudflared service install` 装的是系统服务」 | 装的是**用户级 LaunchAgent**，重启后无人登录则不启动 |
| 「`pmset autorestart` 等于来电自启」 | 前者管崩溃重启，来电自启由 Apple Silicon 固件决定 |
| 「`sleep 0` 就能一直在线」 | 还要考虑网络断连、DNS、ISP 重拨 |
| 「Mac mini 没显示器所以不用管显示设置」 | 首次装机与 GUI 设置（如自动登录）仍需接显示器 |
| 「VNC 有密码就安全」 | VNC 加密弱，必须套 Access 或 SSH |
| 「定时重启没必要」 | 长期运行的状态泄露是真实存在的 |

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [deploy-mac-mini.md](./deploy-mac-mini.md) | 本仓库如何在 Mac 上部署（CI + Tunnel 的流水线） |
| [AGENTS.md](../AGENTS.md) | 项目协作与验证约定 |
