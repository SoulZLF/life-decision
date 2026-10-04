#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync_update.py —— 从 GitHub 仓库同步最新语料，重建索引，重新导出豆包/飞书包。

用法：
  python scripts/sync_update.py [--repo https://github.com/<owner>/<repo>] [--ref main]

默认源：《高性价比人生指南》github.com/eternity4719/HowToLiveBetter（Unlicense 公有领域）

流程：
  1. 用 urllib 直接下载仓库 tarball 到 cache/repo/（不依赖 git，跨应用零依赖）
  2. 定位语料：优先 book/ 目录（34 个章节文件按序号拼接），否则回退单文件 md
  3. parse → references/raw_entries.json
  4. build → references/knowledge_index.json
  5. 重新导出豆包导入包 + 飞书技能包

说明：
  * 为什么不用 git：在 WorkBuddy 等 Electron 环境里，git 子进程做网络操作会崩溃
    （exit 0xC0000005 访问冲突）；改用 Python 标准库 urllib + tarfile 更稳、更可移植。
  * 私有仓库可设环境变量 GITHUB_TOKEN=<token> 走鉴权下载。
"""
DEFAULT_REPO = "https://github.com/eternity4719/HowToLiveBetter"
import argparse
import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts" / "engine"))

from parse_md import parse as parse_md, normalize
from build_index import build as build_index
from export_doubao import build_kb_md, PROMPT

CACHE = SKILL_ROOT / "cache" / "repo"
REFERENCES = SKILL_ROOT / "references"
EXPORTS = SKILL_ROOT / "exports"
FEISHU_TEMPLATE = SKILL_ROOT / "templates" / "feishu_SKILL.md"

USER_AGENT = "life-decision-sync/1.0"


def parse_repo(repo: str) -> tuple[str, str]:
    """从各种 GitHub 地址提取 (owner, repo)。支持：
    https://github.com/o/r | https://github.com/o/r.git | git@github.com:o/r.git | https://github.com/o/r/tree/branch
    """
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?(?:[/?#]|$)", repo)
    if not m:
        raise ValueError(f"无法解析仓库地址：{repo}")
    return m.group(1), m.group(2).rstrip("/")


def _download_tarball(url: str, token: str | None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def download_repo(repo: str, ref: str, token: str | None):
    owner, name = parse_repo(repo)
    if CACHE.exists():
        shutil.rmtree(CACHE)
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    refs = [ref] if ref != "main" else ["main", "master"]
    last_err = None
    for r in refs:
        url = f"https://codeload.github.com/{owner}/{name}/tar.gz/refs/heads/{r}"
        try:
            data = _download_tarball(url, token)
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 404:
                continue  # 换下一个分支名试试
            raise
        _extract_tarball(data)
        print(f"   已下载 {owner}/{name}@{r} → {CACHE}")
        return
    raise RuntimeError(
        f"下载失败（尝试分支 {refs}）：{last_err}。请用 --ref 指定正确分支名。"
    )


def _extract_tarball(data: bytes):
    CACHE.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = tar.getmembers()
        # 确定顶层目录名：取第一个「名字里带 /」的成员的首段（<repo>-<ref>）
        top = ""
        for m in members:
            if "/" in m.name:
                top = m.name.split("/", 1)[0]
                break
        prefix = top + "/" if top else ""
        for m in members:
            name = m.name
            # 跳过顶层目录条目本身（可能带斜杠也可能不带）
            if name == top or name == prefix or name.rstrip("/") == top:
                continue
            rel = name[len(prefix):] if prefix and name.startswith(prefix) else name
            if not rel or ".." in rel.split("/"):
                continue  # 防路径穿越 / 跳过空路径
            target = CACHE / rel
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as f, open(target, "wb") as out:
                    out.write(f.read())


def find_corpus() -> Path | None:
    """定位语料：
    1. 优先 book/ 目录（全书按 34 个章节文件拆分，如 01-不要早死.md），按序号拼接成一份；
    2. 否则回退单文件：文件名含「高性价比/人生」优先，其次取最大的 md。
    """
    book = CACHE / "book"
    if book.is_dir():
        def _num(p: Path) -> int:
            m = re.match(r"^(\d+)", p.name)
            return int(m.group(1)) if m else 10**9
        chapters = sorted([p for p in book.glob("*.md") if p.name != "_combined.md"], key=_num)
        if chapters:
            parts = []
            for p in chapters:
                txt = p.read_text(encoding="utf-8")
                # 去掉每章开头「回总目录」导航行
                txt = re.sub(r"^\[←[^\n]*\]\s*", "", txt, count=1)
                parts.append(txt.strip())
            combined = CACHE / "_combined_高性价比人生指南.md"
            combined.write_text("\n\n".join(parts), encoding="utf-8")
            return combined
    for p in CACHE.rglob("*.md"):
        if "高性价比" in p.name or "人生" in p.name:
            return p
    mds = sorted(CACHE.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    return mds[0] if mds else None


def export_doubao(items: list):
    out = EXPORTS / "doubao"
    out.mkdir(parents=True, exist_ok=True)
    (out / "豆包知识库.md").write_text(build_kb_md(items), encoding="utf-8")
    (out / "豆包智能体提示词.txt").write_text(PROMPT, encoding="utf-8")
    print(f"   豆包导入包 → {out}")


def export_feishu(items: list):
    root = EXPORTS / "feishu" / "life-decision"
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "references" / "人生决策知识库.md").write_text(build_kb_md(items), encoding="utf-8")
    template = FEISHU_TEMPLATE.read_text(encoding="utf-8")
    chapter_count = len({i["chapter"] for i in items})
    template = template.replace("{{ENTRY_COUNT}}", str(len(items))).replace(
        "{{CHAPTER_COUNT}}", str(chapter_count)
    )
    (root / "SKILL.md").write_text(template, encoding="utf-8")

    zip_path = EXPORTS / "feishu" / "life-decision.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(root.parent))
    print(f"   飞书技能包 → {zip_path}")


def main():
    ap = argparse.ArgumentParser(description="同步 GitHub 语料并重建索引/导出")
    ap.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 仓库地址（默认《高性价比人生指南》）")
    ap.add_argument("--ref", default="main", help="分支名（默认 main，404 时自动尝试 master）")
    ap.add_argument("--no-export", action="store_true", help="只重建索引，不导出豆包/飞书包")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or None

    print("1/4 下载仓库 ...")
    download_repo(args.repo.rstrip("/"), args.ref, token)

    md = find_corpus()
    if md is None:
        print("❌ 未找到语料 md 文件"); sys.exit(1)
    print(f"   语料：{md.relative_to(CACHE)}（{md.stat().st_size} 字节）")

    print("2/4 解析 → raw_entries.json ...")
    raw = [normalize(e) for e in parse_md(md)]
    (REFERENCES / "raw_entries.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"   解析 {len(raw)} 条")

    print("3/4 重建索引 → knowledge_index.json ...")
    items = build_index()
    (REFERENCES / "knowledge_index.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 纯文档版知识库：供零依赖消费（飞书 / 任何 AI 直接读 md），随仓库一起分发
    (REFERENCES / "人生决策知识库.md").write_text(build_kb_md(items), encoding="utf-8")
    print(f"   索引 {len(items)} 条")

    if args.no_export:
        print("4/4 跳过导出"); return

    print("4/4 重新导出豆包/飞书包 ...")
    export_doubao(items)
    export_feishu(items)
    print("\n✅ 同步完成")


if __name__ == "__main__":
    main()
