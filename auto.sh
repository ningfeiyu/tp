#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Cloudflare IP 优选自动化入口（重构版）
# 阶段化执行：配置 -> 测速 -> 生成输出 -> 可选上传 -> 可选通知
# 测速核心失败时触发安全熔断，不上传旧/损坏数据
# ---------------------------------------------------------------------------

ROOT_DIR=$(cd "$(dirname "$0")"; pwd)
cd "$ROOT_DIR"

# Termux 环境提示
if [ -n "${TERMUX_VERSION:-}" ] || [ -d "/data/data/com.termux" ]; then
  echo "⚠️  Termux 环境检测到：请确保已开启 'Acquire wakelock' 并设置电池优化为'无限制'，否则测速可能被系统杀后台中断。"
fi

# 载入 .env（若存在）
if [ -f .env ]; then
  set -a; source .env; set +a
else
  echo "[WARN] 未找到 .env 文件，请从 .env.example 复制并填写敏感配置。"
fi

# 载入 config.yaml 中的非密钥配置（若 python3 + PyYAML 可用）
load_yaml_val() {
  local key="$1"
  python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from update import get_config
    print(get_config('$key'))
except Exception:
    print('')
" 2>/dev/null || true
}

# 默认值（可被环境变量覆盖）
DEFAULT_MODE="${DEFAULT_MODE:-$(load_yaml_val default_mode)}"
DEFAULT_MODE="${DEFAULT_MODE:-local}"

INPUT_URL="${INPUT_URL:-$(load_yaml_val input_url)}"
INPUT_URL="${INPUT_URL:-https://raw.githubusercontent.com/ningfeiyu/cloudflare_ip/main/full_ips.txt}"

TCP_WORKERS="${TCP_WORKERS:-$(load_yaml_val tcp_workers)}"
TCP_WORKERS="${TCP_WORKERS:-100}"
TCP_TIMEOUT="${TCP_TIMEOUT:-$(load_yaml_val tcp_timeout)}"
TCP_TIMEOUT="${TCP_TIMEOUT:-1.5}"

SPEED_WORKERS="${SPEED_WORKERS:-$(load_yaml_val speed_workers)}"
SPEED_WORKERS="${SPEED_WORKERS:-4}"
SPEED_TIMEOUT="${SPEED_TIMEOUT:-$(load_yaml_val speed_timeout)}"
SPEED_TIMEOUT="${SPEED_TIMEOUT:-6.0}"
SPEED_MIN="${SPEED_MIN:-$(load_yaml_val speed_min_mbps)}"
SPEED_MIN="${SPEED_MIN:-5.0}"

USE_R2="${USE_R2:-$(load_yaml_val use_r2)}"
USE_R2="${USE_R2:-false}"
USE_GH="${USE_GH:-$(load_yaml_val use_github)}"
USE_GH="${USE_GH:-false}"
USE_TG="${USE_TG:-$(load_yaml_val use_telegram)}"
USE_TG="${USE_TG:-false}"
USE_MAIL="${USE_MAIL:-$(load_yaml_val use_email)}"
USE_MAIL="${USE_MAIL:-false}"

GH_SYNC_MODE="${GH_SYNC_MODE:-$(load_yaml_val github_sync_mode)}"
GH_SYNC_MODE="${GH_SYNC_MODE:-api}"

NOTIFY_ON_FAILURE="${NOTIFY_ON_FAILURE:-$(load_yaml_val notify_on_failure)}"
NOTIFY_ON_FAILURE="${NOTIFY_ON_FAILURE:-true}"

# 协议头自动补齐
fix_protocol() {
  local val="$1"
  if [[ -n "$val" && ! "$val" =~ ^[a-zA-Z0-9]+:// ]]; then
    echo "http://$val"
  else
    echo "$val"
  fi
}
INPUT_URL=$(fix_protocol "$INPUT_URL")

# 运行模式
if [ -n "${1:-}" ]; then
  FINAL_MODE="$1"
  echo "[$(date '+%H:%M:%S')] 🛰️ 运行模式: $FINAL_MODE (手动参数)"
else
  FINAL_MODE="$DEFAULT_MODE"
  echo "[$(date '+%H:%M:%S')] 🛰️ 运行模式: $FINAL_MODE (配置文件)"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 优选任务开始..."

# 清理可能干扰测速的代理变量（测速必须直连）
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY

TASK_STATUS="SUCCESS"

# 阶段 1：测速
if ! env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY python3 update.py; then
  echo "❌ 测速脚本异常终止。"
  TASK_STATUS="FAILED"
fi

# 安全熔断：测速失败时不上传任何数据
if [ "$TASK_STATUS" == "FAILED" ]; then
  echo -e "\033[1;31m🚨 警告: 测速核心崩溃，已触发安全熔断，跳过所有云端上传。\033[0m"
  if [ "$NOTIFY_ON_FAILURE" == "true" ]; then
    echo "[INFO] 测速失败，但通知开关已开启，将继续尝试发送失败通知。"
  fi
fi

# 本地模式：测速后直接退出
if [ "$FINAL_MODE" == "local" ]; then
  echo "💡 本地模式：上传已跳过。"
  exit 0
fi

# 阶段 2：Cloudflare R2 上传（可选）
R2_MSG="🚫 已禁用"
if [ "$USE_R2" == "true" ] && [ "$TASK_STATUS" != "FAILED" ]; then
  echo "[$(date '+%H:%M:%S')] ☁️ 上传至 Cloudflare R2 存储..."
  R2_MSG="❌ 上传失败"
  # 此处可集成 AWS CLI 或 rclone 上传逻辑（保持轻量，不引入付费依赖）
  echo "[INFO] R2 上传逻辑需根据你的工具链（awscli/rclone）自行集成。"
elif [ "$USE_R2" == "true" ] && [ "$TASK_STATUS" == "FAILED" ]; then
  R2_MSG="🚫 熔断跳过"
fi
echo " └─ $R2_MSG"

# 阶段 3：GitHub 上传（可选）
GH_MSG="🚫 已禁用"
if [ "$USE_GH" == "true" ] && [ "$TASK_STATUS" != "FAILED" ]; then
  echo "[$(date '+%H:%M:%S')] 🐙 上传至 GitHub..."
  if [ -z "${GH_TOKEN:-}" ] || [ -z "${GH_OWNER:-}" ] || [ -z "${GH_REPO_NAME:-}" ]; then
    echo "❌ GitHub 凭据缺失（GH_TOKEN / GH_OWNER / GH_REPO_NAME），跳过上传。"
    GH_MSG="❌ 凭据缺失"
  else
    if [ "$GH_SYNC_MODE" == "api" ]; then
      python3 upload_github.py && GH_MSG="✅ 成功 (API)" || GH_MSG="❌ 失败 (API)"
    else
      git add best_ips.txt full_ips.txt README.md 2>/dev/null || true
      git commit -m "Update Cloudflare IP: $(date '+%Y-%m-%d %H:%M:%S')" 2>/dev/null || true
      git push origin main 2>/dev/null && GH_MSG="✅ 成功 (Push)" || GH_MSG="❌ 失败 (Push)"
    fi
  fi
elif [ "$USE_GH" == "true" ] && [ "$TASK_STATUS" == "FAILED" ]; then
  GH_MSG="🚫 熔断跳过"
fi
echo " └─ $GH_MSG"

# 阶段 4：构造战报
if [ "$TASK_STATUS" == "FAILED" ]; then
  MAIL_TAG="崩溃"
  MSG_TEXT="<b>🚨 优选任务崩溃警报</b>
<b>任务状态</b>: 测速引擎执行失败 (FAILED)
<b>可能原因</b>: 找不到依赖、网络断流或配置解析异常
<b>R2 存储</b>: $R2_MSG
<b>GitHub 上传</b>: $GH_MSG
<b>时间</b>: $(date '+%Y-%m-%d %H:%M:%S')"
else
  MAIL_TAG="完成"
  TOTAL_CANDIDATES=$(wc -l < full_ips.txt 2>/dev/null || echo 0)
  FINAL_FAST_COUNT=$(wc -l < best_ips.txt 2>/dev/null || echo 0)
  TOP_IP=$(head -n 1 best_ips.txt 2>/dev/null | awk '{print $1}' || echo "N/A")
  MSG_TEXT="<b>📊 优选战报</b>
<b>优选任务已完成</b>
<b>测速候选</b>: $TOTAL_CANDIDATES
<b>达标优选</b>: $FINAL_FAST_COUNT
<b>最快 IP</b>: $TOP_IP
<b>R2 存储</b>: $R2_MSG
<b>GitHub 上传</b>: $GH_MSG
<b>时间</b>: $(date '+%Y-%m-%d %H:%M:%S')"
fi

# 阶段 5：Telegram 通知（可选）
if [ "$USE_TG" == "true" ]; then
  if [ "$TASK_STATUS" == "FAILED" ] && [ "$NOTIFY_ON_FAILURE" != "true" ]; then
    echo "[INFO] 测速失败且通知开关关闭，跳过 Telegram。"
  else
    echo "[$(date '+%H:%M:%S')] 📢 正在发送 Telegram 战报..."
    TG_API_HOST="${TG_PROXY_DOMAIN:-api.telegram.org}"
    TG_RES=$(curl -s -X POST "https://$TG_API_HOST/bot${TG_BOT_TOKEN}/sendMessage" \
      --connect-timeout 5 --retry 1 \
      -d "chat_id=${TG_CHAT_ID}" \
      -d "parse_mode=HTML" \
      --data-urlencode "text=$MSG_TEXT" 2>/dev/null || echo "")
    if echo "$TG_RES" | grep -q '"ok":true'; then
      echo " └─ ✅ Telegram 战报已发送"
    else
      echo " └─ ❌ Telegram 发送失败"
    fi
  fi
fi

# 阶段 6：Email 通知（可选）
if [ "$USE_MAIL" == "true" ]; then
  if [ "$TASK_STATUS" == "FAILED" ] && [ "$NOTIFY_ON_FAILURE" != "true" ]; then
    echo "[INFO] 测速失败且通知开关关闭，跳过 Email。"
  else
    echo "[$(date '+%H:%M:%S')] 📧 正在发送 Email 战报..."
    python3 - "$MAIL_HOST" "$MAIL_USER" "$MAIL_PASS" "$MAIL_TO" "$MAIL_TAG" <<'PYEOF'
import sys, smtplib
from email.mime.text import MIMEText
from email.header import Header
host, user, pwd, to, tag = sys.argv[1:6]
body = f"""<html><body>{sys.stdin.read() if not sys.stdin.isatty() else ''}</body></html>"""
msg = MIMEText(body, 'html', 'utf-8')
msg['From'] = f"{Header('Cloudflare IP Robot', 'utf-8')} <{user}>"
msg['To'] = f"{Header('Master', 'utf-8')} <{to}>"
msg['Subject'] = Header(f"🚀 IP 优选战报 [{tag}]", 'utf-8')
try:
    s = smtplib.SMTP_SSL(host, 465, timeout=15)
    s.login(user, pwd)
    s.sendmail(user, [to], msg.as_string())
    s.quit()
    print(" └─ ✅ Email 战报已发送")
except Exception as e:
    print(f" └─ ❌ Email 发送失败: {e}")
PYEOF
  fi
fi

echo -e "✨ [$(date '+%Y-%m-%d %H:%M:%S')] 任务全部执行完毕！"