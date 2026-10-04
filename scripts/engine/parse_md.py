# -*- coding: utf-8 -*-
"""
parse_md.py —— 从《高性价比人生指南.md》解析出结构化条目。

原则：
  1. 不改动原文，不增删内容。
  2. 只做「切分」和「字段归位」，把每一块原文原样保存到对应字段。
  3. 解析结果存成 raw_entries.json，作为后续建立索引的中间产物。
"""
import re
import json
import hashlib
from pathlib import Path

MD_PATH = Path(__file__).resolve().parent.parent / "高性价比人生指南.md"

FIELD_KEYS = ["成本", "说人话", "收益", "证据等级", "来源", "备注"]


def parse(md_path: Path = MD_PATH) -> list[dict]:
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")

    entries = []
    cur = None
    chapter_num = None
    chapter_title = ""

    for idx, line in enumerate(lines, start=1):
        m_ch = re.match(r"^# (\d+)\.\s+(.+)$", line)
        if m_ch:
            chapter_num = int(m_ch.group(1))
            chapter_title = m_ch.group(2).strip()
            continue

        m = re.match(r"^###\s+(.+)", line)
        if m:
            if cur is not None:
                entries.append(cur)
            raw_title = m.group(1).strip()
            # 去掉条目序号前缀，例如 "1. 系安全带..." -> "系安全带..."
            title = re.sub(r"^\d+\.\s*", "", raw_title)
            cur = {
                "chapter_num": chapter_num,
                "chapter_title": chapter_title,
                "raw_title": raw_title,
                "title": title,
                "start_line": idx,
                "cost_tag": "",
                "fields": {},
            }
            continue

        if cur is None:
            continue

        if line.startswith("<!-- 成本标签"):
            cur["cost_tag"] = line.strip()
        for fk in FIELD_KEYS:
            if line.startswith(f"- {fk}："):
                cur["fields"][fk] = line

    if cur is not None:
        entries.append(cur)

    return entries


def normalize(entry: dict) -> dict:
    """把解析出的 entry 规整为后续建索引要用的原始条目。"""
    fields = entry["fields"]
    evidence_raw = fields.get("证据等级", "")
    # 证据等级可能出现 "A（争议）" 这类写法，取核心字母
    m = re.search(r"([ABC])", evidence_raw)
    evidence_level = m.group(1) if m else ""

    def clean(value: str) -> str:
        # 去掉 "- 字段：" 前缀，保留字段正文
        return re.sub(r"^-\s*[^：:]+[：:]\s*", "", value).strip()

    # 组装内容原文（用于展示与追溯），保持原文顺序
    content_parts = [f"### {entry['raw_title']}"]
    if entry["cost_tag"]:
        content_parts.append(entry["cost_tag"])
    for fk in FIELD_KEYS:
        if fk in fields:
            content_parts.append(fields[fk])
    content = "\n".join(content_parts)

    return {
        "chapter_num": entry["chapter_num"],
        "chapter_title": entry["chapter_title"],
        "title": entry["title"],
        "start_line": entry["start_line"],
        "cost_tag": entry["cost_tag"],
        "成本": clean(fields.get("成本", "")),
        "说人话": clean(fields.get("说人话", "")),
        "收益": clean(fields.get("收益", "")),
        "证据等级_raw": evidence_raw,
        "evidence_level": evidence_level,
        "来源": clean(fields.get("来源", "")),
        "备注": clean(fields.get("备注", "")),
        "content": content,
    }


if __name__ == "__main__":
    raw = parse()
    normalized = [normalize(e) for e in raw]
    out = Path(__file__).resolve().parent.parent.parent / "references" / "raw_entries.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"解析完成：共 {len(normalized)} 条")
    print(f"已写入 {out}")
    from collections import Counter
    print("证据等级分布:", dict(Counter(e['evidence_level'] for e in normalized)))
