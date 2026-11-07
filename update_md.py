#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
README.MD 时间戳与统计信息自动更新（重构版）

功能：
  - 更新 README 中的“本次更新”时间戳
  - 写入 IP 统计信息（总数、TCP 存活率、达标优选数、最快 IP）
  - 中文为主，保持向后兼容
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

README_PATH = Path(__file__).resolve().parent / "README.md"


def now_iso() -> str:
    return datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S UTC")


def read_stats() -> dict:
    """从输出文件读取最新统计。"""
    stats: dict = {}
    best_path = README_PATH.parent / "best_ips.txt"
    full_path = README_PATH.parent / "full_ips.txt"

    if full_path.exists():
        lines = full_path.read_text(encoding="utf-8").splitlines()
        stats["total_candidates"] = len(lines)
    else:
        stats["total_candidates"] = 0

    if best_path.exists():
        lines = best_path.read_text(encoding="utf-8").splitlines()
        stats["fast_count"] = len(lines)
        stats["top_ip"] = lines[0].split()[0] if lines else "N/A"
    else:
        stats["fast_count"] = 0
        stats["top_ip"] = "N/A"

    return stats


def update_readme(stats: dict) -> None:
    if not README_PATH.exists():
        raise SystemExit(f"未找到 README 文件：{README_PATH}")

    text = README_PATH.read_text(encoding="utf-8")
    updated_at = now_iso()

    # 更新“本次更新”行
    pattern = re.compile(r"^\*\*本次更新\*\*[:：].*$", re.MULTILINE)
    new_line = f"**本次更新**: {updated_at}"
    if pattern.search(text):
        text = pattern.sub(new_line, text, count=1)
    else:
        # 插入到标题后
        text = text.rstrip() + f"\n\n{new_line}\n"

    # 更新或插入统计块
    stats_block = (
        f"\n## 最新统计（自动更新）\n"
        f"- IP 总数：{stats.get('total_candidates', 0)}\n"
        f"- 达标优选：{stats.get('fast_count', 0)}\n"
        f"- 最快 IP：{stats.get('top_ip', 'N/A')}\n"
        f"- 更新时间：{updated_at}\n"
    )
    stats_pattern = re.compile(r"## 最新统计\(自动更新\)\n.*?(?=\n## |\Z)", re.DOTALL)
    if stats_pattern.search(text):
        text = stats_pattern.sub(stats_block.strip(), text, count=1)
    else:
        text = text.rstrip() + "\n" + stats_block.strip() + "\n"

    README_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"已更新 README 时间戳与统计为 {updated_at}")


def main() -> None:
    stats = read_stats()
    update_readme(stats)


if __name__ == "__main__":
    main()