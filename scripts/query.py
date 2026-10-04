#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
query.py —— life-decision 本地查询入口。

直接调用知识引擎跑完整决策流程（解析 → 召回 → 适用性过滤 → 覆盖情况），
不依赖 MCP，可作为 skill 的 CLI 能力直接使用。

用法：
    python query.py "房东让我一次交一年房租，我有点担心。"
    python query.py "刚租的房子，签合同要注意什么？" --top-k 8 --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))

from knowledge_engine import KnowledgeEngine
from llm_parser import get_parser


def run(question: str, top_k: int = 18, situation: dict = None) -> dict:
    engine = KnowledgeEngine(parser=get_parser())
    s = engine.search_knowledge(question, top_k=top_k, situation=situation)
    parsed = s["parsed"]
    candidates = s["candidates"]
    ids = [c["knowledge_id"] for c in candidates]
    verdicts = engine.verify_knowledge(question, ids, situation=situation)
    return {
        "question": question,
        "parsed": parsed,
        "candidates": candidates,
        "verdicts": verdicts,
    }


_VERDICT_MARK = {
    "applicable": "[适用]",
    "possibly_applicable": "[可能适用]",
    "not_applicable": "[不适用]",
}


def main():
    ap = argparse.ArgumentParser(description="人生决策知识库本地查询")
    ap.add_argument("question", help="用户的大白话问题")
    ap.add_argument("--top-k", type=int, default=18, help="召回候选数（默认 18）")
    ap.add_argument("--situation", help="预解析的 situation JSON（可选，传入后引擎不再内部解析）")
    ap.add_argument("--json", action="store_true", help="输出完整 JSON")
    args = ap.parse_args()

    situation = json.loads(args.situation) if args.situation else None
    r = run(args.question, top_k=args.top_k, situation=situation)

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    parsed = r["parsed"]
    results = r["verdicts"]["results"]
    kept = [x for x in results if x["verdict"] == "applicable"]
    maybe = [x for x in results if x["verdict"] == "possibly_applicable"]
    rejected = [x for x in results if x["verdict"] == "not_applicable"]

    print("=" * 62)
    print("问题：", r["question"])
    print("-" * 62)
    print("【解析】")
    print(f"  领域 domain={parsed['domain']}  对象={parsed['object']!r}")
    print(f"  意图={parsed['intent']!r}  风险={parsed['risk']!r}")
    print(f"  特征 features={parsed['features']}")
    print("-" * 62)
    print(f"【召回】{len(r['candidates'])} 条候选：")
    for c in r["candidates"]:
        print(f"  {c['knowledge_id']}  {c['title']}")
    print("-" * 62)
    print("【适用性判定】")
    for v in results:
        mark = _VERDICT_MARK.get(v["verdict"], "[?]")
        print(f"  {mark} {v['knowledge_id']}  {v.get('title', '')[:36]}")
        for reason in v.get("reasons", []):
            print(f"        ↳ {reason}")
    print("-" * 62)
    print(f"【覆盖情况】适用 {len(kept)} / 可能适用 {len(maybe)} / 不适用 {len(rejected)}（共 {len(results)}）")


if __name__ == "__main__":
    main()
