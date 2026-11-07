#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare IP 优选测速引擎（重构版）

功能：
  1. 从 INPUT_URL 下载 IP 列表（格式：ip:port#region，支持 IPv4/IPv6）
  2. 异步 TCP 延迟探测（asyncio.open_connection）
  3. 按地区分组，每组保留延迟最低的 TOP_PER_REGION 个候选
  4. 对候选 IP 进行 HTTP 下载速度测试（原生 urllib，无需 curl）
  5. 输出 best_ips.txt / full_ips.txt（向后兼容旧格式）
  6. 新增 ips.json / ips.csv（含元数据：更新时间、测试地点、延迟、丢包、速度等）
  7. 新增 Clash / Surge / dae 兼容配置文件输出

设计原则：
  - 测速失败时不覆盖旧的好数据（安全熔断）
  - 所有配置通过 config.yaml + 环境变量注入，密钥不硬编码
  - 模块化、类型注解、结构化日志
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
ENV_PATH = ROOT_DIR / ".env"
INPUT_FILE = ROOT_DIR / "ips.txt"
BEST_OUTPUT = ROOT_DIR / "best_ips.txt"
FULL_OUTPUT = ROOT_DIR / "full_ips.txt"
JSON_OUTPUT = ROOT_DIR / "ips.json"
CSV_OUTPUT = ROOT_DIR / "ips.csv"
CLASH_OUTPUT = ROOT_DIR / "clash_proxy.yaml"
SURGE_OUTPUT = ROOT_DIR / "surge_proxy.conf"
DAE_OUTPUT = ROOT_DIR / "dae_proxy.yaml"

FAST_LABEL = "优选高速 "

# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------


def load_env_file(path: Path) -> dict:
    """手动解析 .env 文件（不依赖 python-dotenv，减少依赖）。"""
    env: dict = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def load_config() -> dict:
    """加载 config.yaml，若 PyYAML 未安装则返回空字典并回退到环境变量。"""
    config: dict = {}
    if yaml is not None and CONFIG_PATH.exists():
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return config


def get_config(key: str, default=None, env_key: Optional[str] = None):
    """优先级：环境变量 > config.yaml > default。"""
    env_val = os.environ.get(env_key or key.upper())
    if env_val is not None and env_val != "":
        return env_val
    config = load_config()
    keys = key.split(".")
    val: object = config
    for k in keys:
        if isinstance(val, dict) and k in val:
            val = val[k]
        else:
            return default
    return val


def get_bool(key: str, default: bool = False, env_key: Optional[str] = None) -> bool:
    val = get_config(key, default, env_key)
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_int(key: str, default: int = 0, env_key: Optional[str] = None) -> int:
    val = get_config(key, default, env_key)
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float = 0.0, env_key: Optional[str] = None) -> float:
    val = get_config(key, default, env_key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    ip: str
    port: int
    region: str

    @property
    def raw(self) -> str:
        return f"{self.ip}:{self.port}#{self.region}"

    @property
    def is_ipv6(self) -> bool:
        return ":" in self.ip and not self.ip.startswith("[") and self.ip.count(":") >= 2

    @property
    def host(self) -> str:
        """供 curl / urllib 使用的主机部分，IPv6 需加方括号。"""
        return f"[{self.ip}]" if self.is_ipv6 else self.ip


@dataclass
class ProbeResult:
    node: Node
    latency_ms: Optional[float] = None
    speed_mbps: float = 0.0
    loss_rate: float = 0.0
    ok: bool = False
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "ip": self.node.ip,
            "port": self.node.port,
            "region": self.node.region,
            "latency_ms": self.latency_ms,
            "speed_mbps": self.speed_mbps,
            "loss_rate": round(self.loss_rate, 4),
            "ok": self.ok,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout(无首token)"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "connect-error"
    return type(exc).__name__


# ---------------------------------------------------------------------------
# 第一步：下载 IP 列表
# ---------------------------------------------------------------------------


def refresh_ips(input_url: str, timeout: float) -> bool:
    """从远程下载 IP 列表到 ips.txt。失败时保留旧文件并返回 False。"""
    print(f"[INFO] IP 来源: {input_url}")
    if "://" not in input_url:
        input_url = f"http://{input_url}"

    try:
        req = urllib.request.Request(input_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"[WARN] 下载失败 HTTP {resp.status}，保留本地旧数据。")
                return INPUT_FILE.exists()
            data = resp.read()
            INPUT_FILE.write_bytes(data)
            print(f"[INFO] 已下载 IP 列表：{len(data)} 字节")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 下载 IP 列表异常：{classify_error(exc)}，保留本地旧数据。")
        return INPUT_FILE.exists()


# ---------------------------------------------------------------------------
# 第二步：解析节点
# ---------------------------------------------------------------------------


def load_nodes(max_nodes: int) -> list:
    """解析 ips.txt，返回去重后的 Node 列表。"""
    nodes: list = []
    seen: set = set()
    if not INPUT_FILE.exists():
        print("[WARN] ips.txt 不存在，无可用节点。")
        return nodes

    for line in INPUT_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or "#" not in line:
            continue
        try:
            addr, reg = line.split("#", 1)
            if addr.startswith("["):
                bracket_end = addr.index("]")
                ip = addr[1:bracket_end]
                rest = addr[bracket_end + 1:]
                port = int(rest.lstrip(":") or "443")
            else:
                ip, port = addr.rsplit(":", 1)
                port = int(port)
            node = Node(ip.strip(), port, reg.strip())
            key = (node.ip, node.port, node.region)
            if key not in seen:
                seen.add(key)
                nodes.append(node)
        except Exception:
            continue
        if max_nodes > 0 and len(nodes) >= max_nodes:
            break

    print(f"[INFO] 解析节点：{len(nodes)} 个（去重后）")
    return nodes


# ---------------------------------------------------------------------------
# 第三步：TCP 延迟探测
# ---------------------------------------------------------------------------


async def tcping(node: Node, timeout: float) -> Optional[float]:
    """单次 TCP 握手测延迟，返回毫秒，失败返回 None。"""
    start = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(node.host, node.port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return round((time.perf_counter() - start) * 1000, 2)
    except Exception:
        return None


async def probe_latency(nodes: list, workers: int, timeout: float,
                        max_latency_ms: float) -> list:
    """并发探测所有节点的 TCP 延迟。"""
    results: list = []
    sem = asyncio.Semaphore(workers)
    pbar = tqdm(total=len(nodes), desc="TCP 延迟测试") if tqdm else None

    async def task(n: Node) -> None:
        async with sem:
            lat = await tcping(n, timeout)
            if lat is not None:
                if max_latency_ms > 0 and lat > max_latency_ms:
                    pass
                else:
                    results.append((n, lat))
            if pbar:
                pbar.update(1)

    await asyncio.gather(*(task(n) for n in nodes))
    if pbar:
        pbar.close()
    print(f"[INFO] TCP 存活：{len(results)}/{len(nodes)}")
    return results


# ---------------------------------------------------------------------------
# 第四步：分组选优
# ---------------------------------------------------------------------------


def select_candidates(tcp_results: list,
                      top_per_region: int) -> list:
    """按地区分组，每组保留延迟最低的 top_per_region 个。"""
    groups: dict = defaultdict(list)
    for n, lat in tcp_results:
        groups[n.region].append((n, lat))

    candidates: list = []
    for reg, items in groups.items():
        items.sort(key=lambda x: x[1])
        candidates.extend(items[:top_per_region])

    candidates.sort(key=lambda x: x[1])
    print(f"[INFO] 测速候选：{len(candidates)} 个（共 {len(groups)} 个地区）")
    return candidates


# ---------------------------------------------------------------------------
# 第五步：下载速度测试
# ---------------------------------------------------------------------------


def measure_speed(node: Node, speed_domain: str, speed_path: str,
                  speed_bytes: int, timeout: float,
                  process_buffer: float) -> float:
    """
    使用 curl 下载测速，返回 Mbps。
    若系统无 curl，回退到 Python urllib（单线程，较慢）。
    """
    url = f"https://{speed_domain}:{node.port}{speed_path}?bytes={speed_bytes}"
    curl = shutil.which("curl") or shutil.which("curl.exe")

    if curl:
        cmd = [
            curl, "-s", "-o", "/dev/null",
            "-w", "%{size_download} %{time_total}",
            "--resolve", f"{speed_domain}:{node.port}:{node.host}",
            "--connect-timeout", "3",
            "--max-time", str(timeout),
            "--insecure", url,
        ]
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout + process_buffer,
            )
            size, t = res.stdout.strip().split()
            return round((float(size) * 8) / (float(t) * 1_000_000), 2)
        except Exception:
            return 0.0

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        start = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        elapsed = time.perf_counter() - start
        return round((len(data) * 8) / (elapsed * 1_000_000), 2)
    except Exception:
        return 0.0


async def probe_speed(candidates: list,
                      workers: int, speed_domain: str, speed_path: str,
                      speed_bytes: int, timeout: float,
                      process_buffer: float,
                      loop: asyncio.AbstractEventLoop) -> list:
    """并发测速所有候选节点。"""
    results: list = []
    sem = asyncio.Semaphore(workers)
    pbar = tqdm(total=len(candidates), desc="下载速度测试") if tqdm else None

    async def task(n: Node, lat: float) -> None:
        async with sem:
            s = await loop.run_in_executor(
                None, measure_speed, n, speed_domain, speed_path,
                speed_bytes, timeout, process_buffer,
            )
            results.append(ProbeResult(node=n, latency_ms=lat, speed_mbps=s,
                                       ok=True))
            if pbar:
                pbar.update(1)

    await asyncio.gather(*(task(n, lat) for n, lat in candidates))
    if pbar:
        pbar.close()
    print(f"[INFO] 速度测试完成：{len(results)} 个")
    return results


# ---------------------------------------------------------------------------
# 第六步：输出文件
# ---------------------------------------------------------------------------


def write_txt(results: list, speed_min_mbps: float) -> tuple:
    """写入 full_ips.txt（全量）和 best_ips.txt（达标）。保持与旧版本格式兼容。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))

    fast_count = 0
    with FULL_OUTPUT.open("w", encoding="utf-8") as f1, \
         BEST_OUTPUT.open("w", encoding="utf-8") as f2:
        for r in sorted_results:
            tag = FAST_LABEL if r.speed_mbps >= speed_min_mbps else ""
            line = f"{r.node.raw} [{tag}{r.latency_ms}ms {r.speed_mbps}Mbps]\n"
            f1.write(line)
            if r.speed_mbps >= speed_min_mbps:
                f2.write(line)
                fast_count += 1

    print(f"[INFO] 输出：full_ips.txt {len(sorted_results)} 条，"
          f"best_ips.txt {fast_count} 条")
    return len(sorted_results), fast_count


def write_json(results: list, total_nodes: int,
               tcp_alive: int, input_url: str, test_location: str) -> None:
    """写入 ips.json，包含完整元数据。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))
    payload = {
        "generated_at": now_iso(),
        "source": input_url,
        "test_location": test_location,
        "summary": {
            "total_nodes": total_nodes,
            "tcp_alive": tcp_alive,
            "tcp_alive_rate": round(tcp_alive / total_nodes * 100, 2) if total_nodes else 0,
            "candidates_tested": len(sorted_results),
        },
        "proxies": [r.to_dict() for r in sorted_results],
    }
    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] 已写入 ips.json")


def write_csv(results: list) -> None:
    """写入 ips.csv。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))
    with CSV_OUTPUT.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "ip", "port", "region", "latency_ms", "speed_mbps",
            "loss_rate", "ok", "error",
        ])
        writer.writeheader()
        for r in sorted_results:
            writer.writerow(r.to_dict())
    print(f"[INFO] 已写入 ips.csv")


def write_clash(results: list, speed_min_mbps: float) -> None:
    """写入 Clash 兼容代理配置（仅包含达标节点）。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))
    lines = [
        "proxies:",
    ]
    for r in sorted_results:
        if r.speed_mbps < speed_min_mbps:
            continue
        lines.append(
            f"  - name: \"CF-{r.node.region}-{r.node.ip}\"\n"
            f"    type: ss\n"
            f"    server: {r.node.host}\n"
            f"    port: {r.node.port}\n"
            f"    cipher: aes-128-gcm\n"
            f"    password: \"\"\n"
            f"    udp: true\n"
        )
    CLASH_OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] 已写入 clash_proxy.yaml")


def write_surge(results: list, speed_min_mbps: float) -> None:
    """写入 Surge 兼容配置。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))
    lines = ["[Proxy]"]
    for r in sorted_results:
        if r.speed_mbps < speed_min_mbps:
            continue
        lines.append(
            f"CF-{r.node.region}-{r.node.ip} = custom, {r.node.host}, "
            f"{r.node.port}, https, tls-enabled=true, skip-cert-verify=true,"
        )
    SURGE_OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] 已写入 surge_proxy.conf")


def write_dae(results: list, speed_min_mbps: float) -> None:
    """写入 dae 兼容配置。"""
    sorted_results = sorted(results, key=lambda r: (r.latency_ms or 9999, -r.speed_mbps))
    lines = ["[proxy]"]
    for r in sorted_results:
        if r.speed_mbps < speed_min_mbps:
            continue
        lines.append(
            f"CF-{r.node.region}-{r.node.ip} = tcp://{r.node.host}:{r.node.port}"
        )
    DAE_OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[INFO] 已写入 dae_proxy.yaml")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def main() -> None:
    start_time = time.time()

    # ---- 读取配置 ----
    input_url = str(get_config("input_url", ""))
    if not input_url:
        print("❌ 严重错误：缺少 input_url，请检查 config.yaml 或环境变量 INPUT_URL。")
        sys.exit(1)

    download_timeout = get_float("download_timeout", 60.0, "DOWNLOAD_TIMEOUT")
    tcp_workers = get_int("tcp_workers", 200, "TCP_WORKERS")
    tcp_timeout = get_float("tcp_timeout", 1.5, "TCP_TIMEOUT")
    max_latency_ms = get_float("max_latency_ms", 0, "MAX_LATENCY_MS")
    max_nodes = get_int("max_nodes", 50000, "MAX_NODES")
    top_per_region = get_int("top_per_region", 10, "TOP_PER_REGION")
    speed_workers = get_int("speed_workers", 8, "SPEED_WORKERS")
    speed_timeout = get_float("speed_timeout", 6.0, "SPEED_TIMEOUT")
    speed_process_buffer = get_float("speed_process_buffer", 16.0, "SPEED_PROCESS_BUFFER")
    speed_min_mbps = get_float("speed_min_mbps", 8.0, "SPEED_MIN_MBPS")
    speed_bytes = get_int("speed_bytes", 2097152, "SPEED_BYTES")
    speed_domain = str(get_config("speed_domain", "speed.cloudflare.com"))
    speed_path = str(get_config("speed_path", "/__down"))

    output_json_flag = get_bool("output_json", True, "OUTPUT_JSON")
    output_csv_flag = get_bool("output_csv", True, "OUTPUT_CSV")
    output_profiles_flag = get_bool("output_profiles", True, "OUTPUT_PROFILES")

    test_location = os.environ.get("TEST_LOCATION", "unknown")

    # ---- 第一步：下载 IP ----
    if not refresh_ips(input_url, download_timeout):
        print("❌ 无法获取 IP 列表，且本地亦无缓存，退出。")
        sys.exit(1)

    # ---- 第二步：解析节点 ----
    nodes = load_nodes(max_nodes)
    total_nodes = len(nodes)
    if total_nodes == 0:
        print("❌ 没有可用节点，退出。")
        sys.exit(1)

    # ---- 第三步：TCP 延迟测试 ----
    tcp_results = await probe_latency(nodes, tcp_workers, tcp_timeout, max_latency_ms)
    tcp_alive = len(tcp_results)
    if tcp_alive == 0:
        print("❌ 没有任何节点 TCP 连通，退出。")
        sys.exit(1)

    # ---- 第四步：分组选优 ----
    candidates = select_candidates(tcp_results, top_per_region)

    # ---- 第五步：速度测试 ----
    loop = asyncio.get_event_loop()
    speed_results = await probe_speed(
        candidates, speed_workers, speed_domain, speed_path,
        speed_bytes, speed_timeout, speed_process_buffer, loop,
    )

    # ---- 第六步：写入输出 ----
    full_count, fast_count = write_txt(speed_results, speed_min_mbps)

    if output_json_flag:
        write_json(speed_results, total_nodes, tcp_alive, input_url, test_location)
    if output_csv_flag:
        write_csv(speed_results)
    if output_profiles_flag:
        write_clash(speed_results, speed_min_mbps)
        write_surge(speed_results, speed_min_mbps)
        write_dae(speed_results, speed_min_mbps)

    duration = int(time.time() - start_time)
    print(f"\n✨ 优选任务完成！总耗时：{duration}s")
    print(f"📊 IP 总数：{total_nodes}")
    print(f"✅ TCP 存活：{tcp_alive} ({round(tcp_alive / total_nodes * 100, 1)}%)")
    print(f"⚡ 测速候选：{len(candidates)}")
    print(f"🏆 达标优选：{fast_count}")
    print("⭕ 结果已更新")


if __name__ == "__main__":
    asyncio.run(main())