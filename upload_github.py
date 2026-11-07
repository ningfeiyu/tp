#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub REST API 上传模块（替代 auto.sh 中脆弱的 shell curl 拼接逻辑）

功能：
  - 通过 GitHub Contents API 上传 best_ips.txt、full_ips.txt、README.md
  - 自动获取文件 SHA 并执行 PUT（创建或覆盖）
  - 支持指数退避重试（最多 3 次）
  - 所有凭据通过环境变量注入：GH_TOKEN, GH_OWNER, GH_REPO_NAME
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ["best_ips.txt", "full_ips.txt", "README.md"]
MAX_RETRIES = 3


def github_api_put(path: str, content_bytes: bytes, token: str,
                   owner: str, repo: str, branch: str = "main") -> bool:
    """单文件 PUT 上传到 GitHub Contents API。"""
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    encoded = base64.b64encode(content_bytes).decode("ascii")

    # 先获取现有文件的 SHA（若存在）
    sha = None
    try:
        req = urllib.request.Request(api_url, headers={"Authorization": f"token {token}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sha = data.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"[WARN] 获取 {path} SHA 失败：{e.code}")
            return False
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] 获取 {path} SHA 异常：{exc}")
        return False

    payload: dict = {
        "message": f"Update {path}: $(date '+%Y-%m-%d %H:%M:%S')".replace("$(date '+%Y-%m-%d %H:%M:%S')", time.strftime("%Y-%m-%d %H:%M:%S")),
        "content": encoded,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    body = json.dumps(payload).encode("utf-8")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                api_url,
                data=body,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                    "User-Agent": "cloudflare-ip-updater",
                },
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201):
                    print(f"[INFO] GitHub 上传成功：{path}")
                    return True
                print(f"[WARN] GitHub 上传 {path} 返回 HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            print(f"[WARN] GitHub 上传 {path} 尝试 {attempt}/{MAX_RETRIES} 失败：HTTP {e.code}")
            if e.code in (401, 403):
                print("[ERROR] GitHub Token 无权限，请检查 GH_TOKEN。")
                return False
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] GitHub 上传 {path} 尝试 {attempt}/{MAX_RETRIES} 异常：{exc}")
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
    return False


def main() -> int:
    token = os.environ.get("GH_TOKEN", "")
    owner = os.environ.get("GH_OWNER", "")
    repo = os.environ.get("GH_REPO_NAME", "")

    if not token or not owner or not repo:
        print("❌ 缺少 GitHub 凭据：GH_TOKEN / GH_OWNER / GH_REPO_NAME")
        return 1

    all_ok = True
    for fname in FILES:
        fpath = ROOT / fname
        if not fpath.exists():
            print(f"[WARN] 文件不存在，跳过：{fname}")
            continue
        content = fpath.read_bytes()
        ok = github_api_put(fname, content, token, owner, repo)
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())