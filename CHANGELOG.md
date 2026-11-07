# CHANGELOG

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。所有重大变更均在此记录。

## [v2.1.0] - 2026-11-05 Termux 优化版

### 新增
- `termux_setup.sh`：Termux 一键环境安装脚本（pkg 安装 python/git/cronie，pip 安装 tqdm/pyyaml，.env 权限设为 600）
- `termux_cron.sh`：Termux 定时任务设置脚本（cronie + crond，一键写入 crontab）
- `.termux/boot/start-cron.sh`：Termux 开机自启脚本
- README.md Termux 部署章节：一键安装、定时任务、开机自启、桌面快捷方式、电池优化/wakelock 关键设置
- config.yaml Termux 友好默认值：default_mode=local、tcp_workers=100、max_nodes=20000、top_per_region=5、speed_workers=4、speed_min_mbps=5.0
- auto.sh Termux 环境检测提示（wakelock、电池优化提醒）

### 修复
- config.yaml 默认值从云端模式改为本地模式，更适合 Termux 设备仅本地测速使用
- auto.sh 默认并发和阈值调整为 Termux 低性能设备友好值

### 向后兼容
- `best_ips.txt` / `full_ips.txt` 文件名与格式保持不变
- 原有 `.env` 环境变量名继续有效

---

## [v2.0.0] - 2026-11-05 重构版

### 新增
- `config.yaml` 集中配置文件，所有阈值、并发数、超时、上传开关可调（对应报告 R7）
- `ips.json` 输出，包含 `generated_at`、`source`、`test_location`、`summary`、`proxies` 完整元数据（对应报告 R6）
- `ips.csv` 输出，便于表格分析（对应报告 R6）
- `clash_proxy.yaml`、`surge_proxy.conf`、`dae_proxy.yaml` 客户端兼容配置（对应报告 R6）
- `upload_github.py` GitHub REST API 上传，支持指数退避重试，替代原 shell 脚本脆弱的 `base64` 拼接逻辑（对应报告 R4）
- `tests/test_update.py` 单元测试，涵盖节点解析、去重、分组选优、不可达节点处理（对应报告 R9）
- IPv6 地址解析支持（`[ipv6]:port#region` 格式）（对应报告 R12）
- 丢包率、`loss_rate` 字段预留（对应报告 R5）

### 修复
- `.env` 加入 `.gitignore`，提供 `.env.example` 模板，防止 Token 硬编码泄露（对应报告 R1）
- `refresh_ips()` 下载失败时保留旧数据并明确报错，不静默使用陈旧 IP（对应报告 R2）
- `measure_speed()` 增加 Python `urllib` 回退，不再硬依赖系统 `curl`（对应报告 R3）
- `auto.sh` 重构为阶段化流程，测速失败时触发安全熔断，不上传旧/损坏数据（对应报告 R11）
- `update_md.py` 同步写入 IP 统计信息（总数、达标数、最快 IP、更新时间）到 README（对应报告 R8）
- `MAX_NODES` 默认从 1,000,000 降至 50,000，降低低内存设备 OOM 风险（对应报告 R10）

### 向后兼容
- `best_ips.txt` / `full_ips.txt` 文件名与格式保持不变
- 原有 `.env` 环境变量名继续有效
- 原有 `auto.sh` 调用方式保持兼容（`bash auto.sh local` / `bash auto.sh`）

### 弃用
- `config.sh` 交互式 Shell 控制台不再作为主配置入口，建议改用 `config.yaml` + `.env`
- 原 `auto.sh` 中脆弱的 `base64 -w 0` GitHub API 拼接逻辑已移除

---

## [v1.0.0] - 原版（ningfeiyu/cloudflare_ip）

- 基础 TCP 延迟测试 + 下载速度测试
- 输出 `best_ips.txt` / `full_ips.txt`
- 支持 Cloudflare R2 / GitHub 上传
- 支持 Telegram / Email 通知
- `config.sh` 交互式配置控制台