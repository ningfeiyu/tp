#!/data/data/com.termux/files/usr/bin/sh
# ---------------------------------------------------------------------------
# Cloudflare IP · Termux 开机自启动脚本
# 放置路径：~/.termux/boot/start-cron.sh
# ---------------------------------------------------------------------------

termux-wake-lock
crond

echo "[INFO] Termux 开机自启：crond 已启动，Cloudflare IP 定时任务将在设定时间运行。"
