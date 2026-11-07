#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Cloudflare IP 优选脚本 · Termux 一键环境安装
# 适用平台：Android Termux
# ---------------------------------------------------------------------------

echo "============================================================"
echo "  Cloudflare IP 优选脚本 · Termux 环境安装"
echo "============================================================"

# 1. 检测是否在 Termux 中运行
if [ -z "${TERMUX_VERSION:-}" ] && [ ! -d "/data/data/com.termux" ]; then
  echo "[WARN] 检测到非 Termux 环境，部分 Termux 特定步骤可能不适用。"
  read -p "是否继续？(y/N): " confirm
  [[ "$confirm" == "y" || "$confirm" == "Y" ]] || exit 0
fi

# 2. 更新软件包
echo "[1/6] 更新软件包列表..."
pkg update -y || true
pkg upgrade -y || true

# 3. 安装基础工具
echo "[2/6] 安装 Python、Git、curl、cronie、termux-services..."
pkg install -y python git curl cronie termux-services || {
  echo "[ERROR] 软件包安装失败，请检查网络后重试。"
  exit 1
}

# 4. 安装 Python 依赖
echo "[3/6] 安装 Python 依赖 (tqdm, pyyaml)..."
pip install --upgrade pip || true
pip install tqdm pyyaml || {
  echo "[WARN] tqdm/pyyaml 安装失败，脚本会自动回退到标准库模式（进度条/YAML 配置不可用）。"
}

# 5. 创建项目目录
echo "[4/6] 准备项目目录..."
PROJECT_DIR="${HOME}/cloudflare_ip"
if [ ! -d "$PROJECT_DIR" ]; then
  git clone https://github.com/ningfeiyu/cloudflare_ip.git "$PROJECT_DIR" 2>/dev/null || {
    echo "[INFO] 未指定远程仓库，将在当前目录初始化空项目。"
    PROJECT_DIR="$(cd "$(dirname "$0")"; pwd)"
  }
fi
cd "$PROJECT_DIR"

# 6. 配置 .env 权限
echo "[5/6] 配置敏感文件权限..."
if [ -f .env.example ] && [ ! -f .env ]; then
  cp .env.example .env
  echo "[INFO] 已从 .env.example 复制 .env，请编辑填入你的真实密钥。"
fi
if [ -f .env ]; then
  chmod 600 .env
  echo "[INFO] .env 权限已设为 600（仅 owner 可读写）。"
fi

# 7. 赋予脚本执行权限
echo "[6/6] 赋予脚本执行权限..."
chmod +x *.sh *.py 2>/dev/null || true

echo ""
echo "============================================================"
echo "  ✅ Termux 环境安装完成"
echo "============================================================"
echo ""
echo "下一步："
echo "  1. 编辑 $PROJECT_DIR/.env，填入 GH_TOKEN / TG_BOT_TOKEN 等密钥"
echo "  2. 编辑 $PROJECT_DIR/config.yaml，按需调整测速阈值"
echo "  3. 运行测速：bash auto.sh local"
echo "  4. 设置定时任务：bash termux_cron.sh"
echo ""
echo "⚠️  重要：在 Termux 中运行测速前，请关闭 VPN/代理，"
echo "   或在代理软件中为 Termux 设置分应用代理（排除 Termux），"
echo "   否则测出的是代理服务器速度而非本地直连速度。"
echo ""
echo "📋 防止 Android 杀后台："
echo "   - Termux 通知栏点击 'Acquire wakelock'"
echo "   - 系统设置 → 应用 → Termux → 电池优化 → '无限制'"
echo ""
