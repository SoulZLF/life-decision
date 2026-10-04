# -*- coding: utf-8 -*-
"""
build_index.py —— 从 raw_entries.json 建立结构化知识索引 knowledge_index.json。

每条知识包含字段：
  id, title, category, topics, keywords, user_intents,
  applies_when, does_not_apply_when, content, evidence_level, source, source_id
另有辅助字段：chapter, chapter_title, 各原文字段, start_line（追溯用）。

原则：
  * 语义字段（topics/keywords/user_intents/applies_when/does_not_apply_when）只做
    索引与检索用途，全部从原文字段派生，不引入原文没有的事实。
  * 无法确定的字段留空。
"""
import json
import hashlib
import re
from pathlib import Path

import jieba

from lexicon import (
    CHAPTER_NAMES, CHAPTER_INTENTS, INTENT_VOCAB, TOPIC_RULES, CONDITION_RULES,
    STOPWORDS, MEANINGFUL_SINGLE,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_PATH = SKILL_ROOT / "references" / "raw_entries.json"
OUT_PATH = SKILL_ROOT / "references" / "knowledge_index.json"


def _jieba_tokens(text: str) -> list[str]:
    tokens = []
    for tok in jieba.cut(text):
        tok = tok.strip()
        if not tok:
            continue
        if len(tok) == 1 and tok not in MEANINGFUL_SINGLE:
            continue
        if tok in STOPWORDS:
            continue
        if re.fullmatch(r"[\d\.%＋\-]+", tok):
            continue
        tokens.append(tok)
    return tokens


def extract_keywords(entry: dict) -> list[str]:
    """关键词 = 标题词（权重高，重复 2 次）+ 说人话词。"""
    title_toks = _jieba_tokens(entry["title"])
    body_toks = _jieba_tokens(entry["说人话"])
    counter = {}
    for t in title_toks:
        counter[t] = counter.get(t, 0) + 2
    for t in body_toks:
        counter[t] = counter.get(t, 0) + 1
    # 按权重降序取前 20 个
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:20]]


def derive_topics(entry: dict) -> list[str]:
    """主题标签：章节名 + 标题命中主题规则。"""
    topics = []
    ch_name = entry["chapter_title"]
    if ch_name:
        topics.append(ch_name)
    title = entry["title"]
    for pattern, tag in TOPIC_RULES:
        if re.search(pattern, title):
            if tag not in topics:
                topics.append(tag)
    return topics


def derive_intents(entry: dict) -> list[str]:
    """意图：章节默认意图 + 标题里显式的「不要/不」触发「评估风险/节省开支」。"""
    intents = list(CHAPTER_INTENTS.get(entry["chapter_num"], []))
    title = entry["title"]
    if re.search(r"^(不要|别|不)", title) and "评估风险" not in intents:
        intents.append("评估风险")
    # 反面清单整体是「别做」性质
    if entry["chapter_num"] == 6 and "评估风险" not in intents:
        intents.append("评估风险")
    return intents


def apply_conditions(entry: dict) -> tuple[list[str], list[str]]:
    """适用/不适用条件：优先用人工规则表，否则留空。"""
    for rule in CONDITION_RULES:
        if entry["chapter_num"] == rule["chapter"] and rule["title_contains"] in entry["title"]:
            return rule["applies_when"], rule["does_not_apply_when"]
    return [], []


def build() -> list[dict]:
    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    index = []
    seq_by_chapter = {}
    for e in raw:
        chapter = e["chapter_num"]
        seq_by_chapter[chapter] = seq_by_chapter.get(chapter, 0) + 1
        knowledge_id = f"KB-{chapter:02d}-{seq_by_chapter[chapter]:02d}"

        applies, not_applies = apply_conditions(e)

        source_id = hashlib.sha1(e["来源"].encode("utf-8")).hexdigest()[:16]

        item = {
            "id": knowledge_id,
            "title": e["title"],
            "category": e["chapter_title"],
            "chapter": chapter,
            "topics": derive_topics(e),
            "keywords": extract_keywords(e),
            "user_intents": derive_intents(e),
            "applies_when": applies,
            "does_not_apply_when": not_applies,
            "content": e["content"],
            "evidence_level": e["evidence_level"],
            "source": e["来源"],
            "source_id": source_id,
            # 追溯与检索辅助
            "start_line": e["start_line"],
            "说人话": e["说人话"],
            "备注": e["备注"],
            "成本": e["成本"],
            "收益": e["收益"],
        }
        index.append(item)
    return index


if __name__ == "__main__":
    items = build()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"索引建立完成：共 {len(items)} 条")
    print(f"已写入 {OUT_PATH}")
    # 简单校验
    from collections import Counter
    print("证据等级分布:", dict(Counter(i['evidence_level'] for i in items)))
    print("有 applies_when 的条目数:", sum(1 for i in items if i['applies_when']))
    print("有 does_not_apply_when 的条目数:", sum(1 for i in items if i['does_not_apply_when']))
