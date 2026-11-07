#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Cloudflare IP 优选脚本 · Termux 定时任务设置
# 依赖：cronie + termux-services
# ---------------------------------------------------------------------------

PROJECT_DIR="${1:-$(cd "$(dirname "$0")"; pwd)}"
cd "$PROJECT_DIR"

CRON_TIME="${CRON_TIME:-30 4 * * *}"  # 默认每天凌晨 4:30

echo "============================================================"
echo "  Cloudflare IP · Termux 定时任务设置"
echo "============================================================"

# 检查 crond 是否可用
if ! command -v crond >/dev/null 2>&1; then
  echo "[ERROR] 未找到 crond，请先运行 termux_setup.sh 安装 cronie。"
  exit 1
fi

# 检查 termux-services
if [ ! -d "$PREFIX/var/service" ]; then
  echo "[WARN] 未检测到 termux-services，尝试安装..."
  pkg install -y termux-services 2>/dev/null || true
fi

# 启动 crond 服务
echo "[1/4] 启动 crond 服务..."
sv-enable crond 2>/dev/null || true
sv up crond 2>/dev/null || crond 2>/dev/null || true
sleep 1

# 写入 crontab（去重）
echo "[2/4] 写入 crontab 定时任务..."
EXISTING=$(crontab -l 2>/dev/null | grep -F "cloudflare_ip/auto.sh" || true)
if [ -z "$EXISTING" ]; then
  (
    crontab -l 2>/dev/null || true
    echo "$CRON_TIME TERM=xterm stdbuf -oL -eL script -q -c \"bash $PROJECT_DIR/auto.sh\" /dev/null | col -b >> $PROJECT_DIR/cron_log.log 2>&1"
  ) | crontab -
  echo "[INFO] 已添加定时任务：$CRON_TIME"
else
  echo "[INFO] 定时任务已存在，跳过。"
fi

# 显示当前 crontab
echo "[3/4] 当前 crontab 列表："
crontab -l 2>/dev/null || echo "(空)"

# 常用管理命令
echo ""
echo "[4/4] 常用管理命令："
echo "  查看定时任务：  crontab -l"
echo "  查看 crond 状态： sv status crond"
echo "  重启 crond：    sv restart crond"
echo "  停止 crond：    sv down crond"
echo "  查看运行日志：  tail -f $PROJECT_DIR/cron_log.log"
echo ""
echo "✅ 定时任务设置完成。"
echo "   脚本将在每天 $CRON_TIME 运行测速，日志保存在 $PROJECT_DIR/cron_log.log"
