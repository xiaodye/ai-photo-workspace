# 部署到 Mac Mini（GitHub Actions + Cloudflare Tunnel）

本文记录生产环境的部署方式：代码合并到 `main` 后，由 GitHub Actions 经 Cloudflare Tunnel 自动部署到家里的 Mac Mini。

不依赖 self-hosted runner，因此**仓库即使公开也是安全的**：外部 PR 的代码永远不会在你的机器上执行。

## 为什么是这个方案

Mac Mini 位于家庭宽带 NAT 之后，没有公网 IP，GitHub 的托管 runner 无法主动连进去。在三种解法中选「SSH over Cloudflare Tunnel」：

| 方案 | 需要暴露什么 | 公开仓库是否安全 | 复杂度 |
| --- | --- | --- | --- |
| **SSH over Cloudflare Tunnel（本方案）** | 已有的 `ssh.<域名>` 隧道入口 | ✅ 安全 | 低 |
| self-hosted runner | 无 | ❌ 有风险 | 高 |
| 定时 git 轮询 | 无 | ✅ 安全 | 低，但有分钟级延迟 |

理由是复用已有的隧道与 Access 能力，同时保留 Actions 的完整日志与手动重跑能力，又不必给公开仓库引入自托管 runner。

> GitHub 官方明确不建议把 self-hosted runner 挂到公开仓库：`pull_request` 事件会执行工作流所在分支的代码，攻击者 fork 后修改 workflow 即可在你的机器上执行任意命令。

隧道本身怎么搭（安装、创建、绑 DNS、开机自启）属于 Mac mini 的基础设施配置，见 [把 Mac mini 变成常驻云服务器](./macmini-as-cloud-server.md#内网穿透-cloudflare-tunnel)，本文不重复。

## 架构

```text
PR ──push──▶ GitHub 托管 runner
             └─ ci.yml：后端 ruff、前端 lint + build（不接触你的机器）

合并到 main ──▶ GitHub 托管 runner
             └─ deploy.yml
                  ├─ 安装 cloudflared
                  ├─ 写入部署私钥 + 固定 sshd 主机指纹
                  └─ cloudflared access ssh（Service Token 免交互）
                        │  隧道
                        ▼
                    Mac Mini: ~/apps/ai-photo-workspace
                        ├─ rsync 增量同步代码 + .git（排除 .env 等本地配置）
                        ├─ docker compose --profile deploy up -d --build
                        ├─ alembic upgrade head
                        ├─ /api/health 健康检查
                        └─ /editor/smoke SPA 深层路由验收
```

流量方向是「从内到外」：runner 出站连 Cloudflare，cloudflared 把 SSH 流量送进家里的 Mac Mini，全程不需要公网端口。

## 前置条件

在 Mac Mini 上已经具备：

- Docker Desktop（`docker` 在 `/usr/local/bin`）
- `cloudflared` 以 LaunchDaemon 方式运行，隧道已绑定 `ssh.<域名>` → `ssh://localhost:22`
- Cloudflare Access 应用保护该主机名（邮箱策略，人工登录用）

> 以上三项属于通用的「让 Mac 常驻在线」配置，搭建方法见 [把 Mac mini 变成常驻云服务器](./macmini-as-cloud-server.md)。`cloudflared` 必须用 LaunchDaemon 而非 LaunchAgent，否则重启后无人登录时隧道不会启动。

- 部署目录 `~/apps/ai-photo-workspace`，其中包含三个**本地配置文件**（`rsync` 时被排除，不会被覆盖或删除）：
  - `.env`：生产环境变量（从 `.env.example` 复制后填真实值）
  - `docker-compose.override.yml`：端口收敛、`S3_PUBLIC_ENDPOINT`、构建入口（从 `docker-compose.override.example.yml` 复制后改占位符）
  - `Dockerfile.local`：apt / PyPI / npm 换国内源

> 国内网络下构建必须用 `Dockerfile.local`：官方 `Dockerfile` 里的 `deb.debian.org` 会超时或极慢，`uv sync` 直连 pypi 源站实测只有 ~15 KB/s（阿里云镜像 ~9 MB/s），一个 250 MB 的依赖集要跑几个小时。

> **为什么 PyPI 不能只靠环境变量换源**：`uv.lock` 给每个包记录的是 pypi 官方下载 URL（`files.pythonhosted.org`），`uv sync --frozen` 会直接按这些 URL 下载，`UV_DEFAULT_INDEX` / `--index-url` 都不会改变它们。所以 `Dockerfile.local` 是在镜像内用 `sed` 改写这份 lock 的副本（仓库里的 `uv.lock` 不动，版本和 sha256 校验值都不变，只换下载主机）。

**这三个文件不存在时，部署会失败**（`docker compose` 会报 `env file .env not found`）。全新机器上一条命令生成：

```bash
cd ~/apps/ai-photo-workspace
./scripts/bootstrap-mac-mini.sh          # 幂等：已存在的文件会跳过，--force 覆盖
```

它会做四件事：

| 产出 | 说明 |
| --- | --- |
| `.env` | 从 `.env.example` 复制，随机生成 `JWT_SECRET` 与 `CREDENTIAL_ENCRYPTION_KEY`，权限设 `600` |
| `docker-compose.override.yml` | 从模板生成：端口只绑 `127.0.0.1`、使用 `Dockerfile.local` |
| `Dockerfile.local` | 从 `Dockerfile` 生成并替换 4 处为国内源；**上游 Dockerfile 变动导致替换点找不到时会直接报错**，不会生成坏文件 |
| 自检 | 结尾跑 `docker compose config --quiet` |

然后确认 `.env` 里这些值（`CREDENTIAL_ENCRYPTION_KEY` 已自动生成，不要改动）：

| 变量 | 说明 |
| --- | --- |
| `S3_PUBLIC_ENDPOINT` | **对外访问对象存储的域名**。留空会回退 `http://localhost:7313`，外网图片打不开。`docker-compose.yml` 通过 `${S3_PUBLIC_ENDPOINT:-http://localhost:7313}` 插值读取，**换域名只改这一行，不用动 compose 或 override** |
| `CREDENTIAL_ENCRYPTION_KEY` | 用户模型 Key 的加密主密钥，bootstrap 已随机生成。**必须长期稳定并单独备份**；换值后所有已保存的用户 Key 都无法解密，需要用户重新填写。API 与 Worker 必须一致 |
| `ALLOW_PLATFORM_KEY_FALLBACK` | 是否允许未配置 Key 的访客使用平台额度，**公网部署保持 `false`** |
| `DASHSCOPE_API_KEY` | 仅在 `ALLOW_PLATFORM_KEY_FALLBACK=true` 时作为兜底使用；正常部署留空 |
| `IMAGE_PROVIDER` | `mock`（仅本地开发）或 `dashscope`（真实模型，公网部署必须用这个） |

> 模型 Key 不放在 `.env`：每个用户登录后在自己的「模型设置」里填写，费用由各自百炼账户承担。服务端只保存加密后的密文与尾号。

> `.gitignore` 已排除这三个本地文件，避免误提交密钥或机器相关配置。手动准备也可以，按上面表格里的来源逐个复制即可。

## 一次性配置

### 1. 生成部署专用密钥

在**本地开发机**（不是 Mac Mini）执行：

```bash
ssh-keygen -t ed25519 -N "" -C "github-actions-deploy@mac-mini" -f ~/.ssh/deploy_macmini
```

- 私钥 `~/.ssh/deploy_macmini`：只存在于本地与 GitHub Secrets
- 公钥 `~/.ssh/deploy_macmini.pub`：追加到 Mac Mini 的 `~/.ssh/authorized_keys`

```bash
cat ~/.ssh/deploy_macmini.pub | ssh macmini 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

原则：**私钥跟着发起方走，公钥放在被登录的一方**。不要把这把私钥放到 Mac Mini 上。

### 2. 创建 Cloudflare Service Token

Zero Trust → Access → **Service Auth** → Create Service Token：

| 字段 | 建议值 |
| --- | --- |
| Name | `github-actions-deploy` |
| Duration | 1 年（不建议 Non-expiring，泄露后无边界） |

生成后立即复制 **Client ID** 与 **Client Secret**（Secret 只显示一次）。

### 3. 在 Access 应用上放行该 token

打开 `ssh.<域名>` 对应的 Access 应用 → Policies → 新增一条：

```text
Action:  Service Auth
Include: Service Token → github-actions-deploy
```

原有的 `Allow + Emails` 策略保留不动，两条策略是 OR 关系：人工用邮箱登录，CI 用 token 通过。

> Action 必须是 **Service Auth**，选 `Allow` 无法用于非交互场景。

### 4. 配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions：

| Secret | 值 |
| --- | --- |
| `SSH_PRIVATE_KEY` | `cat ~/.ssh/deploy_macmini` 的完整输出（含 BEGIN/END 行） |
| `CF_ACCESS_CLIENT_ID` | 第 2 步的 Client ID |
| `CF_ACCESS_CLIENT_SECRET` | 第 2 步的 Client Secret |

## 工作流说明

### `ci.yml`

- 触发：`pull_request`、`workflow_dispatch`
- 运行在 GitHub 托管 runner，只读仓库权限
- 后端：`astral-sh/ruff-action` 检查 `backend/`
- 前端：`pnpm install --frozen-lockfile` + `pnpm lint`（oxlint）+ `pnpm build`（`tsc -b && vite build`）

> 当前未包含 `pytest`：后端测试需要 PostgreSQL / Redis / MinIO，需在 CI 里用 `services:` 起依赖，会显著拉长单次 PR 时长。

### `deploy.yml`

- 触发：`push` 到 `main`、`workflow_dispatch`
- `concurrency` 串行化，避免连续合并并发部署
- `if: github.repository_owner == 'xiaodye'`，fork 出来的仓库无法命中
- 步骤：
  1. `actions/checkout` 取到本次提交的代码
  2. 下载并安装 `cloudflared`
  3. 写入 `SSH_PRIVATE_KEY`，用 `ssh-keygen -y` 先校验私钥可用，再把 Mac Mini 的 **sshd 主机公钥写死**进 `known_hosts`
  4. `rsync` 经隧道把代码增量同步到 Mac Mini
  5. **检查服务器本地配置**：`.env` / `docker-compose.override.yml` / `Dockerfile.local` 缺任何一个就立即失败，并提示准备命令
  6. 经 `cloudflared access ssh` 连入 Mac Mini，执行构建/迁移/健康检查

远程脚本（内嵌在 workflow 中）：

```bash
set -euo pipefail
cd ~/apps/ai-photo-workspace
docker compose --profile deploy up -d --build
docker compose --profile deploy exec -T app alembic upgrade head
# 健康检查（最多 60s）
# SPA 深层路由验收：GET /editor/smoke 必须是 200
```

### 为什么由 CI 推送代码，而不是让 Mac Mini 自己 `git pull`

家庭宽带访问 GitHub 很不稳定：同一台机器上用 `curl` 有时 0.1 秒连通，`git fetch` 却可能 75 秒后报 `Operation timed out`；不同 DNS 还会解析到可用性不同的 IP。早期版本让 Mac Mini 执行 `git fetch origin main`，结果部署频繁失败在拉代码这一步。

现在的做法是把「获取代码」交给 runner（Azure 机房，访问 GitHub 稳定），再用 `rsync` 走已有隧道增量同步。

**同步时把 `.git` 一起带上**（`actions/checkout` 用 `fetch-depth: 0` 取完整历史）。这样 Mac Mini 上仍然是一个**干净可用的 git 仓库**：

- `git log` 能看到完整提交历史
- `git status` 是干净的（部署后执行 `git update-index --refresh` 刷新 mtime 缓存）
- 线上出问题时可以 `git reset --hard <旧 commit>` 后重新构建来回滚

代价是每次部署多传约 3~4 MB 的 `.git`(git 的 pack 文件随历史变化整体重写,无法只传增量)。实测隧道上耗时约 2~4 秒,相对整个部署可以接受。

> 顺带收益:Mac Mini 上原来是 `--depth 1` 的 shallow 仓库,同步完整历史后自动变成普通仓库。

`rsync` 用 `--delete` 保证文件与仓库一致，同时排除三类本地配置，避免被覆盖或删除：

| 排除项 | 原因 |
| --- | --- |
| `.env` / `.env.local` | 生产环境变量，不入库 |
| `docker-compose.override.yml` | 端口收敛、`S3_PUBLIC_ENDPOINT`、构建入口 |
| `Dockerfile.local` | 换国内源的构建文件 |
| `.metadata_never_index` | 告诉 Spotlight 不要索引部署目录，避免每次部署后重新扫描 |

## 首次验证

1. 先合并 SPA fallback 修复（`fix/spa-history-fallback`），否则第 4 步的 SPA 验收会**故意失败**
2. 合并本分支
3. Actions → **deploy** → **Run workflow** 手动触发一次
4. 确认日志里出现「部署完成」以及 `{"api":"ok","database":"ok","storage":"ok"}`

确认无误后，之后的合并即自动发布。

## 日常发布

```text
改代码 → 提 PR（ci.yml 跑 lint/build）→ review → 合并 main → deploy.yml 自动部署
```

手动重发：Actions → deploy → Run workflow。

## 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `cloudflared: command not found` | 安装步骤失败 | 看「安装 cloudflared」日志，通常是 GitHub 下载超时，可重跑 |
| `websocket: bad handshake` | Access 拒绝了 Service Token | 应用策略的 Action 必须是「服务身份验证」，不能是「允许」 |
| `服务器缺少本地配置文件` | 新机器还没准备 `.env` 等三件套 | 按提示的 `cp` 命令准备，见「前置条件」 |
| `Load key ... error in libcrypto` | Secret 里的私钥被破坏（最常见是换行丢失） | 用 `gh secret set SSH_PRIVATE_KEY < ~/.ssh/deploy_macmini` 从文件直接写入，别用剪贴板 |
| `Permission denied (publickey)` | Secret 里的私钥不完整，或公钥没加到 Mac Mini | 重新复制完整私钥；`ssh-keygen -lf ~/.ssh/authorized_keys` 核对指纹 |
| `Host key verification failed` | Mac Mini 重装或换了主机密钥 | 更新 workflow 里写死的 Ed25519 公钥 |
| `403` / 登录页卡住 | Service Token 未加入 Access 策略，或 Action 选成了 `Allow` | 改为 `Service Auth` 策略 |
| `/editor/smoke` 返回 404 | SPA fallback 未生效 | 先合并 `fix/spa-history-fallback` |
| 构建超时 / `uv sync` 卡在 Downloading | 国内直连 pypi 源站极慢（实测约 15 KB/s，阿里云镜像约 9 MB/s） | 确认用的是 `Dockerfile.local`，且日志里出现「改写为国内源的 URL 行数」；只设 `UV_DEFAULT_INDEX` 没用，见下方说明 |
| 健康检查失败 | 容器起不来 / 迁移失败 | 日志里有 `docker compose logs --tail=60 app` 输出 |
| 拆分图层 / 抠图报「执行失败，请重试」 | worker 拿不到 rembg 权重，尝试现场下载又被 DNS 拦掉（`release-assets.githubusercontent.com` 被解析到 `127.0.0.1`） | 见下方「预置抠图模型」；同时确认 `MATTING_PROVIDER=auto`，此时会降级为四角抠图而不是整条任务失败 |
| worker 容器被 SIGKILL（exit 137） | 权重太大，超过 Docker VM 内存（`bria-rmbg` 峰值约 7.7 GB） | 改用 `MATTING_MODEL=isnet-general-use`，或把 Docker Desktop 内存调到 12 GB 以上 |

远程调试：

```bash
ssh macmini
cd ~/apps/ai-photo-workspace
docker compose --profile deploy ps
docker compose --profile deploy logs --tail=80 app
```

### 预置模型权重

Mac Mini 所在网络会把 GitHub 的 release 资源域名解析到 `127.0.0.1`，容器里现场下载权重必然失败（`Connection refused`）。权重又必须持久化，否则每次重建镜像都会重下，所以：

- `cv_models` 卷挂在 `/root/.rembg`，也就是 rembg 2.x 的默认家目录，权重统一放 `models/<模型名>/`，不需要额外设环境变量；
- 首次部署在**能访问 GitHub 的机器**上下载一次，再拷进卷里；
- 两个模型各管一段功能：`isnet-general-use` 用于拆分图层的抠图（worker），`sam` 用于画布点选（app）。

```bash
# 1. 在本地开发机下载（会缓存到 ~/.rembg/models/<模型名>/）
cd backend
uv run python -c 'from rembg import new_session; new_session("isnet-general-use")'
uv run python -c 'from rembg import new_session; new_session("sam", sam_quant=True)'

# 2. 拷到 Mac Mini（同局域网时直连 192.168.x.x 比走隧道快得多）
scp ~/.rembg/models/isnet-general-use/isnet-general-use.onnx lansen@192.168.x.x:/tmp/
scp ~/.rembg/models/sam/sam_vit_b_01ec64.encoder.quant.onnx \
    ~/.rembg/models/sam/sam_vit_b_01ec64.decoder.quant.onnx lansen@192.168.x.x:/tmp/

# 3. 放进卷里（容器在跑就行，app 和 worker 共用同一份）
ssh macmini && cd ~/apps/ai-photo-workspace
docker compose exec -T app mkdir -p /root/.rembg/models/isnet-general-use /root/.rembg/models/sam
docker compose cp /tmp/isnet-general-use.onnx \
  app:/root/.rembg/models/isnet-general-use/isnet-general-use.onnx
docker compose cp /tmp/sam_vit_b_01ec64.encoder.quant.onnx \
  app:/root/.rembg/models/sam/sam_vit_b_01ec64.encoder.quant.onnx
docker compose cp /tmp/sam_vit_b_01ec64.decoder.quant.onnx \
  app:/root/.rembg/models/sam/sam_vit_b_01ec64.decoder.quant.onnx

# 4. 自检：不调用任何收费接口，只验证权重能加载
docker compose exec -T worker /app/backend/.venv/bin/python \
  -c 'from rembg import new_session; print(new_session("isnet-general-use"))'
docker compose exec -T app /app/backend/.venv/bin/python \
  -c 'from rembg import new_session; print(new_session("sam", sam_quant=True))'
```

换权重只需要改 `MATTING_MODEL` 并按上面的路径重新拷一份；`bria-rmbg` 质量更好，但 1 GB 权重峰值约 7.7 GB 内存，8 GB 的 Docker VM 跑不动。

## 安全模型

| 项 | 措施 |
| --- | --- |
| 公开仓库风险 | 不使用 self-hosted runner；deploy 只由 `push: main` 触发 |
| 凭证最小化 | 部署私钥与 Service Token 仅存于 GitHub Secrets（加密） |
| 主机身份校验 | 写死 sshd 的 Ed25519 公钥，不用 `ssh-keyscan` |
| 仓库权限 | workflow 声明 `permissions: contents: read` |
| 密钥轮换 | Service Token 设有效期；私钥泄露时从 Mac Mini 的 `authorized_keys` 删除对应公钥即可 |
| 敏感文件 | `.env` 不入库；部署目录中的本地配置被 `rsync` 排除，不会被覆盖或删除 |

## 已知限制

- **部署期间 5~15 秒不可用**：单机重建容器，没有蓝绿或负载均衡；要零停机需要两套端口 + 切换入口。
- **失败不自动回滚**：健康检查失败会让 job 标红并打印日志，但线上停留在新版本，需要手动处理。
- **构建耗时**：Mac Mini 上有层缓存时约 2~4 分钟，全量重建约 8~10 分钟。
- **部署目录由 CI 同步**：`~/apps/ai-photo-workspace` 的文件内容以 `rsync` 结果为准。目录里保留了完整的 `.git`，可以正常 `git log` / `git diff` / 按 commit 回滚，但**不要手动 `git pull` 或 `git push`** —— 下一次部署会用 rsync 覆盖工作区，以 CI 为准。
- **Docker Desktop 的钥匙串限制**：非 GUI 会话里任何需要拉取镜像的步骤都可能报 `keychain cannot be accessed`。当前流程依赖本地已有基础镜像，不触发拉取；若以后要 `docker compose pull`，需给 workflow 指定不含 `credsStore` 的 `DOCKER_CONFIG`。

## 相关文件

| 文件 | 说明 |
| --- | --- |
| `.github/workflows/ci.yml` | PR 校验 |
| `.github/workflows/deploy.yml` | 合并 main 后部署 |
| `Dockerfile` / `Dockerfile.local` | 通用构建 / 换国内源的构建 |
| `docker-compose.override.example.yml` | 服务器本地配置模板（复制成 `docker-compose.override.yml` 再改） |
| `scripts/bootstrap-mac-mini.sh` | 一条命令生成上面三个本地配置文件 |
| `docker-compose.yml` / `docker-compose.override.yml` | 基础编排 / 生产覆盖 |

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [latency-diagnostics.md](./latency-diagnostics.md) | 线上访问慢时如何判断瓶颈在代码、服务器还是网络链路 |
| [container-memory-diagnostics.md](./container-memory-diagnostics.md) | 容器内存占用异常时如何定位来源、判断是否持续增长 |
| [macmini-as-cloud-server.md](./macmini-as-cloud-server.md) | Mac mini 常驻与内网穿透配置 |
