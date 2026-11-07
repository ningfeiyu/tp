#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare IP 优选引擎单元测试
运行：python3 -m pytest tests/ 或 python3 tests/test_update.py
"""

import sys
import tempfile
from pathlib import Path

# 将项目根目录加入 import 路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from update import Node, load_nodes, select_candidates, tcping  # noqa: E402


def test_node_raw():
    n = Node("1.2.3.4", 443, "HK")
    assert n.raw == "1.2.3.4:443#HK"


def test_node_is_ipv6():
    n = Node("2400:cb00::1", 443, "SG")
    assert n.is_ipv6 is True
    n2 = Node("1.2.3.4", 443, "HK")
    assert n2.is_ipv6 is False


def test_node_host_brackets_ipv6():
    n = Node("2400:cb00::1", 443, "SG")
    assert n.host == "[2400:cb00::1]"
    n2 = Node("1.2.3.4", 443, "HK")
    assert n2.host == "1.2.3.4"


def test_load_nodes_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "ips.txt").write_text(
            "1.1.1.1:443#HK\n"
            "1.1.1.1:443#HK\n"
            "8.8.8.8:443#US\n"
            "badline\n"
        )
        # 临时替换 INPUT_FILE
        import update
        orig = update.INPUT_FILE
        update.INPUT_FILE = tmp_path / "ips.txt"
        try:
            nodes = update.load_nodes(max_nodes=100)
            assert len(nodes) == 2
            regions = {n.region for n in nodes}
            assert regions == {"HK", "US"}
        finally:
            update.INPUT_FILE = orig


def test_select_candidates_grouping():
    from update import Node as N
    results = [
        (N("1.1.1.1", 443, "HK"), 50.0),
        (N("2.2.2.2", 443, "HK"), 30.0),
        (N("3.3.3.3", 443, "HK"), 80.0),
        (N("4.4.4.4", 443, "SG"), 20.0),
        (N("5.5.5.5", 443, "SG"), 90.0),
    ]
    cands = select_candidates(results, top_per_region=2)
    hk = [c for c in cands if c[0].region == "HK"]
    sg = [c for c in cands if c[0].region == "SG"]
    assert len(hk) == 2
    assert len(sg) == 2
    assert hk[0][1] == 30.0  # HK 最低延迟
    assert sg[0][1] == 20.0  # SG 最低延迟


def test_tcping_unreachable():
    import asyncio
    n = Node("10.255.255.1", 9999, "TEST")
    lat = asyncio.run(tcping(n, timeout=0.5))
    assert lat is None


if __name__ == "__main__":
    test_node_raw()
    test_node_is_ipv6()
    test_node_host_brackets_ipv6()
    test_load_nodes_dedup()
    test_select_candidates_grouping()
    test_tcping_unreachable()
    print("✅ 所有单元测试通过")