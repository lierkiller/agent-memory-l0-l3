#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分层记忆库预算校验（L0–L3）。

四层的约定：
  L0  常驻规则   AGENTS.md        每轮随系统提示注入，最贵
  L1  索引       MEMORY.md        每会话开场读一次，只放路由键
  L2  主题记忆   memory/*.md      命中才读
  L3  冷档       memory/*-detail/ 几乎不读，不限预算

检查：
  1. L0 体积是否超预算
  2. L1 体积是否超预算、索引行是否过长
  3. L1 里的每条链接是否指向真实文件
  4. 每个 L2 文件是否都能从 L1 找到（登记完整性）
  5. L2 超预算时，是否带「先读这里」头部摘要
  6. 汇总每轮固定开销（L0 + L1）

用法：
  python memory-budget.py --home ~/.agent-home
  python memory-budget.py --home /path/to/home --agents AGENTS.md --memory memory
退出码 0 = 全部通过，1 = 有违规。
"""
import argparse
import fnmatch
import os
import re
import sys

# 中文 Windows 的控制台常是 GBK：先尝试切到 UTF-8，失败也不影响判定
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 预算：改这里，或改成从配置文件读 ────────────────────────────────
L0_BUDGET_BYTES = 2600          # L0 上限
L1_BUDGET_BYTES = 15360         # L1 上限
INDEX_LINE_MAX = 200            # 单条索引行的最大字符数
L2_MAX_TOKENS = 4000            # 单条 L2 的 token 上限
L2_MAX_LINES = 200              # 单条 L2 的行数上限
HEADER_SCAN_LINES = 45          # 在前多少行内找头部摘要
HEADER_MARK = "先读这里"         # 头部摘要的标记

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def est_tokens(text):
    """粗估 token：CJK 约 1.6 字/token，其余约 4 字符/token。"""
    cjk = len(CJK_RE.findall(text))
    return int(cjk / 1.6 + (len(text) - cjk) / 4)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def human(nbytes):
    return f"{nbytes} B" if nbytes < 1024 else f"{nbytes / 1024:.1f} KB"


def main():
    ap = argparse.ArgumentParser(description="校验 L0–L3 分层记忆库")
    ap.add_argument("--home", default=os.path.expanduser("~/.agent-home"), help="记忆库所在的 home 目录")
    ap.add_argument("--agents", default="AGENTS.md", help="L0 文件名（相对 home）")
    ap.add_argument("--memory", default="memory", help="记忆库目录名（相对 home）")
    ap.add_argument(
        "--cold",
        default="*-inventory.md,*-catalog.md",
        help="放在 memory/ 顶层但按冷档对待的文件（逗号分隔的 glob）",
    )
    args = ap.parse_args()

    home = os.path.abspath(os.path.expanduser(args.home))
    mem = os.path.join(home, args.memory)
    l0 = os.path.join(home, args.agents)
    l1 = os.path.join(mem, "MEMORY.md")

    problems = []
    notes = []

    if not os.path.isdir(mem):
        print(f"[FAIL] 找不到记忆库目录：{mem}")
        return 1

    # ── L0 ────────────────────────────────────────────────────────────
    if not os.path.isfile(l0):
        problems.append(f"L0 缺失：{l0}")
        l0_size = 0
        l0_tok = 0
    else:
        text0 = read(l0)
        l0_size = os.path.getsize(l0)
        l0_tok = est_tokens(text0)
        if l0_size > L0_BUDGET_BYTES:
            problems.append(f"L0 超预算：{human(l0_size)} > {human(L0_BUDGET_BYTES)}")
        print(f"L0  {human(l0_size):>8}  ~{l0_tok:>5} tok   {os.path.relpath(l0, home)}")

    # ── L1 ────────────────────────────────────────────────────────────
    if not os.path.isfile(l1):
        print(f"[FAIL] 找不到索引：{l1}")
        return 1

    text1 = read(l1)
    l1_size = os.path.getsize(l1)
    l1_tok = est_tokens(text1)
    if l1_size > L1_BUDGET_BYTES:
        problems.append(f"L1 超预算：{human(l1_size)} > {human(L1_BUDGET_BYTES)}")
    print(f"L1  {human(l1_size):>8}  ~{l1_tok:>5} tok   {os.path.relpath(l1, home)}")

    links = []
    long_lines = 0
    for i, line in enumerate(text1.splitlines(), 1):
        for target in LINK_RE.findall(line):
            links.append((i, target))
        if line.strip().startswith("- [") and len(line) > INDEX_LINE_MAX:
            long_lines += 1
            problems.append(f"L1 索引行过长（第 {i} 行，{len(line)} 字 > {INDEX_LINE_MAX}）")
    if long_lines:
        notes.append(f"{long_lines} 条索引行超过 {INDEX_LINE_MAX} 字")

    # ── 链接有效性 ────────────────────────────────────────────────────
    linked_files = set()
    dead = 0
    for lineno, target in links:
        target = target.split("#")[0].strip()
        if not target or "://" in target:
            continue
        path = os.path.normpath(os.path.join(mem, target))
        if not os.path.exists(path):
            dead += 1
            problems.append(f"死链（第 {lineno} 行）：{target}")
        else:
            linked_files.add(os.path.basename(path))

    # ── L2 登记完整性 + 单条预算 ──────────────────────────────────────
    cold_globs = [x.strip() for x in args.cold.split(",") if x.strip()]
    top_md = [
        f for f in os.listdir(mem)
        if f.endswith(".md") and f != "MEMORY.md" and os.path.isfile(os.path.join(mem, f))
    ]
    cold_files = [f for f in top_md if any(fnmatch.fnmatch(f, g) for g in cold_globs)]
    l2_files = sorted(f for f in top_md if f not in cold_files)
    l2_bytes = 0
    l2_tok = 0
    for name in l2_files:
        path = os.path.join(mem, name)
        body = read(path)
        size = os.path.getsize(path)
        tok = est_tokens(body)
        l2_bytes += size
        l2_tok += tok
        if name not in linked_files:
            problems.append(f"L2 未在 L1 登记：{name}")
        over_tok = tok > L2_MAX_TOKENS
        over_lines = len(body.splitlines()) > L2_MAX_LINES
        if over_tok or over_lines:
            head = "\n".join(body.splitlines()[:HEADER_SCAN_LINES])
            if HEADER_MARK not in head:
                why = []
                if over_tok:
                    why.append(f"~{tok} tok > {L2_MAX_TOKENS}")
                if over_lines:
                    why.append(f"{len(body.splitlines())} 行 > {L2_MAX_LINES}")
                problems.append(f"L2 超预算且缺头部摘要：{name}（{'，'.join(why)}）")

    # ── L3 只统计，不校验预算 ─────────────────────────────────────────
    l3_dirs = sorted(
        d for d in os.listdir(mem) if os.path.isdir(os.path.join(mem, d))
    )
    l3_files = 0
    l3_bytes = 0
    for d in l3_dirs:
        for root, _dirs, files in os.walk(os.path.join(mem, d)):
            for f in files:
                l3_files += 1
                l3_bytes += os.path.getsize(os.path.join(root, f))

    # ── 汇总 ──────────────────────────────────────────────────────────
    print(f"L2  {human(l2_bytes):>8}  ~{l2_tok:>5} tok   {len(l2_files)} 个主题记忆")
    if cold_files:
        print(f"    （另有 {len(cold_files)} 个顶层冷档文件按约定不计预算：{', '.join(cold_files[:3])}"
              f"{' …' if len(cold_files) > 3 else ''}）")
    print(f"L3  {human(l3_bytes):>8}  {'':>7}     {len(l3_dirs)} 个冷档目录 / {l3_files} 个文件（不校验预算）")
    print("-" * 62)
    print(f"每轮固定开销 ≈ {l0_tok + l1_tok} tok（L0 {l0_tok} + L1 {l1_tok}）")
    print(f"全库（L2+L3）≈ {l2_tok} tok 文本 / {human(l2_bytes + l3_bytes)}")
    if dead:
        notes.append(f"{dead} 条死链")

    if problems:
        print()
        for p in problems:
            print("[FAIL] " + p)
        print(f"\n[FAIL] 共 {len(problems)} 项违规")
        return 1

    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
