# 部署到 Mac Mini（GitHub Actions + Cloudflare Tunnel）

本文记录生产环境的部署方式：代码合并到 `main` 后，由 GitHub Actions 经 Cloudflare Tunnel 自动部署到家里的 Mac Mini。

不依赖 self-hosted runner，因此**仓库即使公开也是安全的**：外部 PR 的代码永远不会在你的机器上执行。

## 为什么是这个方案

Mac Mini 位于家庭宽带 NAT 之后，没有公网 IP，GitHub 的托管 runner 无法主动连进去。常见的三种解法对比：

| 方案 | 需要暴露什么 | 密钥数量 | 公开仓库是否安全 | 复杂度 |
| --- | --- | --- | --- | --- |
| **SSH over Cloudflare Tunnel（本方案）** | 已有的 `ssh.<域名>` 隧道入口 | 3 | ✅ 安全 | 低 |
| self-hosted runner | 无 | 0 | ❌ 有风险 | 高 |
| 定时 git 轮询 | 无 | 0 | ✅ 安全 | 低，但有分钟级延迟 |

选择第一种的原因：复用已有的 Cloudflare Tunnel 与 Access 能力，拥有 Actions 的完整日志与手动重跑能力，同时不给公开仓库引入自托管 runner 的风险。

> GitHub 官方明确不建议把 self-hosted runner 挂到公开仓库：`pull_request` 事件会执行工作流所在分支的代码，攻击者 fork 后修改 workflow 即可在你的机器上执行任意命令。

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
                        ├─ git reset --hard origin/main（保留 .env 等未跟踪文件）
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
- 部署目录 `~/apps/ai-photo-workspace`，其中包含三个**未跟踪**文件（`git reset --hard` 不会覆盖它们）：
  - `.env`：生产环境变量
  - `docker-compose.override.yml`：端口收敛、`S3_PUBLIC_ENDPOINT`、构建入口
  - `Dockerfile.local`：apt / PyPI / npm 换国内源

> 国内网络下构建必须用 `Dockerfile.local`：官方 `Dockerfile` 里的 `download.docker.com` 与 `deb.debian.org` 会超时或极慢。

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
  1. 下载并安装 `cloudflared`
  2. 写入 `SSH_PRIVATE_KEY`，并把 Mac Mini 的 **sshd 主机公钥写死**进 `known_hosts`
  3. 经 `cloudflared access ssh` 连入 Mac Mini，执行远程脚本

远程脚本（内嵌在 workflow 中）：

```bash
set -euo pipefail
cd ~/apps/ai-photo-workspace
git fetch origin main --quiet
git reset --hard origin/main          # 未跟踪的 .env / override / Dockerfile.local 保留
docker compose --profile deploy up -d --build
docker compose --profile deploy exec -T app alembic upgrade head
# 健康检查（最多 60s）
# SPA 深层路由验收：GET /editor/smoke 必须是 200
```

选择 `git reset --hard` 而不是 `actions/checkout` + `rsync`，是为了不覆盖 Mac Mini 上的环境文件。

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
| `Permission denied (publickey)` | Secret 里的私钥不完整，或公钥没加到 Mac Mini | 重新复制完整私钥；`ssh-keygen -lf ~/.ssh/authorized_keys` 核对指纹 |
| `Host key verification failed` | Mac Mini 重装或换了主机密钥 | 更新 workflow 里写死的 Ed25519 公钥 |
| `403` / 登录页卡住 | Service Token 未加入 Access 策略，或 Action 选成了 `Allow` | 改为 `Service Auth` 策略 |
| `/editor/smoke` 返回 404 | SPA fallback 未生效 | 先合并 `fix/spa-history-fallback` |
| 构建超时 | 国内网络拉依赖慢 | 确认用的是 `Dockerfile.local`（国内源） |
| 健康检查失败 | 容器起不来 / 迁移失败 | 日志里有 `docker compose logs --tail=60 app` 输出 |

远程调试：

```bash
ssh macmini
cd ~/apps/ai-photo-workspace
docker compose --profile deploy ps
docker compose --profile deploy logs --tail=80 app
```

## 安全模型

| 项 | 措施 |
| --- | --- |
| 公开仓库风险 | 不使用 self-hosted runner；deploy 只由 `push: main` 触发 |
| 凭证最小化 | 部署私钥与 Service Token 仅存于 GitHub Secrets（加密） |
| 主机身份校验 | 写死 sshd 的 Ed25519 公钥，不用 `ssh-keyscan` |
| 仓库权限 | workflow 声明 `permissions: contents: read` |
| 密钥轮换 | Service Token 设有效期；私钥泄露时从 Mac Mini 的 `authorized_keys` 删除对应公钥即可 |
| 敏感文件 | `.env` 不入库；部署目录中的未跟踪文件不被 `git reset` 清理 |

## 已知限制

- **部署期间 5~15 秒不可用**：单机重建容器，没有蓝绿或负载均衡；要零停机需要两套端口 + 切换入口。
- **失败不自动回滚**：健康检查失败会让 job 标红并打印日志，但线上停留在新版本，需要手动处理。
- **构建耗时**：Mac Mini 上有层缓存时约 2~4 分钟，全量重建约 8~10 分钟。
- **Docker Desktop 的钥匙串限制**：非 GUI 会话里任何需要拉取镜像的步骤都可能报 `keychain cannot be accessed`。当前流程依赖本地已有基础镜像，不触发拉取；若以后要 `docker compose pull`，需给 workflow 指定不含 `credsStore` 的 `DOCKER_CONFIG`。

## 相关文件

| 文件 | 说明 |
| --- | --- |
| `.github/workflows/ci.yml` | PR 校验 |
| `.github/workflows/deploy.yml` | 合并 main 后部署 |
| `Dockerfile` / `Dockerfile.local` | 通用构建 / 换国内源的构建 |
| `docker-compose.yml` / `docker-compose.override.yml` | 基础编排 / 生产覆盖 |
