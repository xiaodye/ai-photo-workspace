#!/usr/bin/env bash
# 在服务器上准备部署所需的三个本地配置文件。
# 幂等：已存在的文件默认跳过（--force 覆盖）。
set -euo pipefail

# macOS 上 docker 装在 /usr/local/bin，通过 SSH 非登录 shell 时 PATH 可能不含它
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"

APP_DIR="$HOME/apps/ai-photo-workspace"
FORCE=0
MIRROR=1

show_help() {
  cat <<'EOF'
用法: scripts/bootstrap-mac-mini.sh [选项]

在服务器上生成部署所需的三个本地配置文件：
  .env                          从 .env.example 复制，JWT_SECRET 自动随机
  docker-compose.override.yml   从 docker-compose.override.example.yml 复制
  Dockerfile.local              从 Dockerfile 生成（默认换国内镜像源）

选项:
  --dir <路径>    部署目录，默认 ~/apps/ai-photo-workspace
  --force         覆盖已存在的文件（默认跳过，保护手改过的配置）
  --no-mirror     不换国内源
  -h, --help      显示本帮助

S3_PUBLIC_ENDPOINT 从 .env 读取（docker-compose.yml 里做插值），
脚本不会写死域名；换域名只需改 .env 那一行。
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dir)
      if [ $# -lt 2 ]; then echo "--dir 需要一个路径" >&2; exit 2; fi
      APP_DIR="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --no-mirror) MIRROR=0; shift ;;
    -h|--help) show_help; exit 0 ;;
    *) echo "未知参数: $1" >&2; show_help; exit 2 ;;
  esac
done

mkdir -p "$APP_DIR"
cd "$APP_DIR"

for f in .env.example docker-compose.override.example.yml Dockerfile; do
  if [ ! -f "$f" ]; then
    echo "[错误] 当前目录缺少 $f" >&2
    echo "       部署目录应包含仓库内容（CI 部署时由 rsync 同步）" >&2
    exit 1
  fi
done

echo "[目录] $APP_DIR"

# --- 1. .env ---
if [ -f .env ] && [ "$FORCE" -eq 0 ]; then
  echo "[跳过] .env 已存在（--force 可覆盖）"
else
  cp .env.example .env
  python3 - <<'PY'
import base64, pathlib, re, secrets

p = pathlib.Path('.env')
text = p.read_text()
text = re.sub(r'^JWT_SECRET=.*$', 'JWT_SECRET=' + secrets.token_hex(32), text, flags=re.M)
# 用户模型 Key 的加密主密钥：随机生成一次后必须长期稳定，换值会让已保存的 Key 无法解密
text = re.sub(
    r'^CREDENTIAL_ENCRYPTION_KEY=.*$',
    # Fernet 密钥 = 32 字节随机数的 urlsafe base64，用标准库即可，不依赖 cryptography
    'CREDENTIAL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    text,
    flags=re.M,
)
p.write_text(text)
print('[生成] .env（JWT_SECRET 与 CREDENTIAL_ENCRYPTION_KEY 已随机化）')
PY
  chmod 600 .env
  echo '[权限] .env 设为 600'
fi

# --- 2. docker-compose.override.yml ---
if [ -f docker-compose.override.yml ] && [ "$FORCE" -eq 0 ]; then
  echo "[跳过] docker-compose.override.yml 已存在"
else
  cp docker-compose.override.example.yml docker-compose.override.yml
  echo '[生成] docker-compose.override.yml'
fi

# --- 3. Dockerfile.local ---
if [ -f Dockerfile.local ] && [ "$FORCE" -eq 0 ]; then
  echo "[跳过] Dockerfile.local 已存在"
else
  python3 - "$MIRROR" <<'PY'
import pathlib, sys

mirror = sys.argv[1] == '1'
text = pathlib.Path('Dockerfile').read_text()
NL = chr(10)

if mirror:
    subs = [
        ("RUN npm install --global pnpm@11.23.0",
         "RUN npm install --global pnpm@11.23.0 && pnpm config set registry https://registry.npmmirror.com"),
        ("RUN apt-get update",
         NL.join([
             "RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true",
             "RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true",
             "RUN apt-get update",
         ])),
        ("COPY backend/pyproject.toml backend/uv.lock ./",
         NL.join([
             "COPY backend/pyproject.toml backend/uv.lock ./",
             "ENV UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple",
         ])),
    ]
    for old, new in subs:
        if old not in text:
            sys.exit('[错误] Dockerfile 中找不到片段，脚本需要同步更新：' + old[:50])
        text = text.replace(old, new, 1)

pathlib.Path('Dockerfile.local').write_text(text)
print('[生成] Dockerfile.local' + ('（已换国内源）' if mirror else '（未换源）'))
PY
fi

# --- 4. S3_PUBLIC_ENDPOINT 检查 ---
PUBLIC=$(python3 - <<'PY'
import pathlib
for line in pathlib.Path('.env').read_text().splitlines():
    if line.startswith('S3_PUBLIC_ENDPOINT='):
        print(line.split('=', 1)[1].strip())
        break
PY
)

if [ -z "$PUBLIC" ]; then
  echo
  echo '[待办] .env 的 S3_PUBLIC_ENDPOINT 为空'
  echo '       公网访问时图片会指向 http://localhost:7313 而打不开'
  echo '       编辑 .env，例如：S3_PUBLIC_ENDPOINT=https://s3.example.com'
else
  echo "[信息] S3_PUBLIC_ENDPOINT = $PUBLIC"
fi

# --- 5. 自检 ---
if command -v docker >/dev/null 2>&1; then
  if docker compose --env-file .env --profile deploy config --quiet >/dev/null 2>&1; then
    echo '[自检] docker compose 配置解析通过'
  else
    echo '[自检] docker compose 解析失败，手动查看原因：'
    echo '       docker compose --env-file .env --profile deploy config'
  fi
else
  echo '[跳过自检] 未找到 docker 命令'
fi

cat <<'EOF'

下一步:
  1. 编辑 .env：确认 IMAGE_PROVIDER=dashscope，ALLOW_PLATFORM_KEY_FALLBACK=false
     （模型 Key 由每个用户在自己的「模型设置」里填写，平台 Key 默认不参与）
  2. 备份 .env 里的 CREDENTIAL_ENCRYPTION_KEY：换值会让已保存的用户 Key 全部失效
  3. 仓库 Settings 里确认 3 个 Secrets：SSH_PRIVATE_KEY / CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET
  4. 合并到 main 触发部署，或手动运行 deploy workflow
EOF
