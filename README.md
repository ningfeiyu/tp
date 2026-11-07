# Cloudflare IP 优选脚本（Termux 优化版）

[English](./README.md) | 中文

## 项目简介

本脚本用于自动测速并筛选 **Cloudflare 优选 IP**，支持在 **Android Termux** 上本地运行，无需手动筛选。支持生成 Clash / Surge / dae 兼容配置，可直接导入客户端使用。

**默认测试地**：中国陕西移动（可通过 `TEST_LOCATION` 环境变量自定义）  
**默认运行模式**：`local`（仅本地测速，不上传，适合 Termux 设备）  
**默认更新频率**：建议每天凌晨 4:30（通过 cron 设置）

---

## 目录结构

```
cloudflare_ip/
├── config.yaml          # 集中配置文件（阈值、并发、超时、上传开关，Termux 友好默认值）
├── .env.example         # 敏感密钥模板（复制为 .env 后填写，不提交）
├── .gitignore           # 忽略敏感文件与输出结果
├── update.py            # 核心测速引擎（Python 3，模块化、类型注解）
├── upload_github.py     # GitHub REST API 上传（替代原 shell 脚本脆弱逻辑）
├── update_md.py         # README 时间戳与统计自动更新
├── auto.sh              # 自动化入口（阶段化：测速→输出→上传→通知，Termux 提示）
├── termux_setup.sh      # Termux 一键环境安装（pkg/pip 依赖、权限设置）
├── termux_cron.sh       # Termux 定时任务设置（cronie + crond）
├── .termux/
│   └── boot/
│       └── start-cron.sh # Termux 开机自启脚本
├── tests/
│   └── test_update.py   # 单元测试
├── best_ips.txt         # 输出：高速优选 IP（达标）
├── full_ips.txt         # 输出：所有可用 IP
├── ips.json             # 输出：JSON 格式（含元数据）
├── ips.csv              # 输出：CSV 格式
├── clash_proxy.yaml     # 输出：Clash 兼容配置
├── surge_proxy.conf     # 输出：Surge 兼容配置
├── dae_proxy.yaml       # 输出：dae 兼容配置
└── README.md            # 本文件
```

---

## 快速开始

### 通用步骤（Linux / Termux）

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/cloudflare_ip.git
cd cloudflare_ip

# 2. 安装 Python 依赖
pip install tqdm pyyaml

# 3. 配置敏感信息
cp .env.example .env
# 编辑 .env，填入 GH_TOKEN、TG_BOT_TOKEN 等（可选，本地测速可不填）

# 4. 运行测速（本地模式，不上传）
bash auto.sh local

# 5. 查看输出
cat best_ips.txt
```

### Termux 一键部署（推荐）

在 Termux 中执行：

```bash
# 1. 克隆仓库
git clone https://github.com/你的用户名/cloudflare_ip.git ~/cloudflare_ip
cd ~/cloudflare_ip

# 2. 运行 Termux 一键安装（安装 python/git/cronie 等依赖，设置 .env 权限）
bash termux_setup.sh

# 3. 编辑配置
nano .env            # 填入你的密钥（如需上传/通知）
nano config.yaml     # 按需调整测速阈值

# 4. 手动运行测试
bash auto.sh local

# 5. 设置定时任务（每天凌晨 4:30 自动运行）
bash termux_cron.sh

# 6. 设置开机自启（可选）
cp .termux/boot/start-cron.sh ~/.termux/boot/
chmod +x ~/.termux/boot/start-cron.sh
```

**⚠️ Termux 关键设置（不做会导致测速中途被杀）：**

1. ** wakelock**：Termux 通知栏下拉，点击 **"Acquire wakelock"**
2. **电池优化**：系统设置 → 应用 → Termux → 电池优化 → 选择 **"无限制"**
3. **关闭代理测速**：运行测速前关闭 VPN/代理，或在代理软件中为 Termux 设置分应用代理（排除 Termux），否则测出的是代理服务器速度而非本地直连速度。

---

## 配置说明（config.yaml）

| 配置项 | 说明 | Termux 默认值 |
|--------|------|--------------|
| `default_mode` | `cloud` 上传 / `local` 仅本地 | `local` |
| `input_url` | IP 列表下载地址 | GitHub raw 链接 |
| `tcp_workers` | TCP 延迟并发线程数 | 100 |
| `tcp_timeout` | TCP 连接超时（秒） | 1.5 |
| `max_latency_ms` | 延迟上限（ms），0=不限制 | 0 |
| `max_nodes` | 最大读取 IP 数，0=全量 | 20000 |
| `top_per_region` | 每地区保留最低延迟 IP 数 | 5 |
| `speed_workers` | 下载测速并发数 | 4 |
| `speed_timeout` | 单次下载超时（秒） | 6.0 |
| `speed_min_mbps` | 最低达标速度（Mbps） | 5.0 |
| `use_r2/use_github/use_telegram/use_email` | 上传与通知开关 | `false` |
| `output_json/output_csv/output_profiles` | 额外输出格式开关 | `true` |

所有配置均可通过环境变量覆盖（如 `export TCP_WORKERS=50`）。

---

## 输出格式说明

### best_ips.txt / full_ips.txt（向后兼容）

```
1.2.3.4:443#HK [优选高速 45.2ms 12.5Mbps]
5.6.7.8:443#SG [89.1ms 3.2Mbps]
```

### ips.json（含元数据）

```json
{
  "generated_at": "2026-11-05 12:00:00 UTC",
  "source": "https://...",
  "test_location": "Shaanxi Mobile",
  "summary": {
    "total_nodes": 20000,
    "tcp_alive": 800,
    "tcp_alive_rate": 4.0,
    "candidates_tested": 100
  },
  "proxies": [
    {
      "ip": "1.2.3.4",
      "port": 443,
      "region": "HK",
      "latency_ms": 45.2,
      "speed_mbps": 12.5,
      "loss_rate": 0.0,
      "ok": true,
      "error": null
    }
  ]
}
```

### Clash / Surge / dae

自动生成 `clash_proxy.yaml`、`surge_proxy.conf`、`dae_proxy.yaml`，仅包含达标节点，可直接导入客户端。

---

## 定时自动化（Termux cron）

使用 `termux_cron.sh` 一键设置：

```bash
bash termux_cron.sh
```

默认每天凌晨 4:30 运行，日志保存在 `cron_log.log`。

### 手动 crontab 示例

```bash
crontab -e
```

添加：

```cron
30 4 * * * TERM=xterm stdbuf -oL -eL script -q -c "bash ~/cloudflare_ip/auto.sh" /dev/null | col -b >> ~/cloudflare_ip/cron_log.log 2>&1
```

### 常用管理命令

```bash
crontab -l              # 查看定时任务
sv status crond         # 查看 crond 状态
sv restart crond        # 重启 crond
tail -f cron_log.log    # 查看运行日志
```

---

## 开机自启（可选）

将开机自启脚本复制到 Termux 启动目录：

```bash
cp .termux/boot/start-cron.sh ~/.termux/boot/
chmod +x ~/.termux/boot/start-cron.sh
```

重启设备后，crond 将自动启动，定时任务按计划运行。

---

## 桌面快捷方式（可选）

安装 Termux:Widget 后，可在桌面添加快捷方式：

```bash
mkdir -p ~/.shortcuts/
nano ~/.shortcuts/运行测速.sh
```

内容：

```bash
#!/bin/bash
termux-wake-lock
bash ~/cloudflare_ip/auto.sh local
```

```bash
chmod +x ~/.shortcuts/运行测速.sh
```

返回桌面长按添加小部件，选择 Termux:Widget 即可点击运行。

---

## 安全说明

- **严禁将真实 Token commit 到 GitHub**。请使用 `.env` + `.gitignore`，或 GitHub Secrets。
- `.env` 默认权限设为 `600`，仅 owner 可读写。
- 脚本测速阶段强制直连，不走代理，确保测出的是本地真实 Cloudflare 连接质量。
- 测速失败时触发安全熔断，不会上传旧或损坏的数据。

---

## 免责声明

本脚本仅用于网络诊断与优选 IP 筛选。使用者需自行遵守当地法律法规及 Cloudflare 服务条款。脚本作者不对因使用本脚本产生的任何网络问题或账号风险负责。

---

## 升级指南（从旧版迁移）

1. 备份旧版 `.env` 中的敏感配置。
2. 克隆新版仓库，将 `.env.example` 复制为 `.env` 并填入配置。
3. 旧版 `best_ips.txt` / `full_ips.txt` 文件名与路径保持不变，可直接替换。
4. 新增 `config.yaml`，可按需调整阈值；若不调整，使用默认值即可。
5. 若原使用 `config.sh` 交互式配置，请改为编辑 `config.yaml` + `.env`。

---

## 遗留风险与后续迭代

| 风险项 | 说明 | 建议 |
|--------|------|------|
| Cloudflare IP 归属校验 | 当前未验证 IP 是否属于 Cloudflare 官方 ASN 网段 | 可选：集成公开 IP 范围文件进行校验 |
| R2 上传逻辑 | `auto.sh` 中 R2 上传为占位，需根据工具链（awscli/rclone）集成 | 添加 `aws s3 sync` 或 `rclone` 调用 |
| 测速依赖 curl | 优先使用系统 `curl`，无 curl 时回退到 `urllib`（较慢） | 增加原生 `httpx` / `aiohttp` 异步下载 |
| IPv6 支持 | 已在代码层支持 IPv6 地址解析，但未在实际网络中验证 | 在 IPv6 环境下进行测速验证 |
| 依赖 tqdm/pyyaml | 缺少时自动降级，但进度条与 YAML 配置不可用 | 文档中明确列出推荐依赖 |
| Android 杀后台 | 测速耗时较长，系统可能杀掉 Termux 进程 | 必须开启 wakelock 和电池优化“无限制” |
