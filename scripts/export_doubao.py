#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_doubao.py —— 把结构化知识库导出为「豆包智能体导入包」。

生成两个文件：
  1. 豆包知识库.md          —— 上传到豆包智能体的知识库（654 条，按章节组织，含适用/不适用条件）
  2. 豆包智能体提示词.txt    —— 复制到豆包智能体的「提示词」框

用法：
    python scripts/export_doubao.py [输出目录]

默认输出到 skill 根下的 exports/doubao/。
"""
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts" / "engine"))

from lexicon import CHAPTER_NAMES

INDEX_PATH = SKILL_ROOT / "references" / "knowledge_index.json"

PROMPT = """# 角色
你是「人生决策顾问」，基于《高性价比人生指南》结构化知识库，帮用户在大额消费、租房买房、职业、保险、健康等人生决策上，给出高性价比、有据可查的建议。

# 核心原则：相关 ≠ 适用
知识库里每条知识都标注了【适用条件】和【不适用条件】。回答前必须先判断：这条知识对用户当前情况是否真的适用。
- 命中【不适用条件】的，坚决不用，并说明为什么不用。
- 无法判断是否适用的，明确说「需结合你的具体情况」。
- 只给真正适用的知识，绝不为了凑字数调用不相关知识。

# 回答规范
1. 先简短复述你理解的情况（用户信息）。
2. 给出依据时，尽量说明知识出处（章节/主题）和证据等级。
3. 知识库没有覆盖的问题，明确说「知识库未覆盖」，不要硬编。
4. 知识库之外的推理，用【AI 建议】标记，与知识库事实分开，不要把推测说成知识库结论。

# 回答风格
说人话，直接给结论，不啰嗦。高性价比导向：省钱、省时间、别踩坑、别交智商税。"""


def _strip_heading(content: str) -> str:
    """去掉 content 开头重复的「### N. 标题」行（标题已由外层输出）。"""
    return re.sub(r"^###\s*\d+\.\s*[^\n]*\n", "", content).strip()


def build_kb_md(data: list) -> str:
    by_chapter: dict[int, list] = {}
    for d in data:
        by_chapter.setdefault(d["chapter"], []).append(d)

    lines = [
        "# 高性价比人生指南 · 结构化知识库（人生决策）",
        "",
        f"> 共 {len(data)} 条知识，按章节组织。每条含【适用条件】【不适用条件】，回答时须先判断适用性。",
        "",
    ]
    for ch in sorted(by_chapter):
        name = CHAPTER_NAMES.get(ch, f"第{ch}章")
        lines.append(f"## 第 {ch} 章 · {name}")
        lines.append("")
        for d in by_chapter[ch]:
            lines.append(f"### {d['id']} · {d['title']}")
            lines.append("")
            if d.get("applies_when"):
                lines.append("【适用条件】" + "；".join(d["applies_when"]))
            if d.get("does_not_apply_when"):
                lines.append("【不适用条件】" + "；".join(d["does_not_apply_when"]))
            lines.append("")
            lines.append(_strip_heading(d["content"]))
            lines.append("")
    return "\n".join(lines)


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else SKILL_ROOT / "exports" / "doubao"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    kb_path = out_dir / "豆包知识库.md"
    kb_path.write_text(build_kb_md(data), encoding="utf-8")

    prompt_path = out_dir / "豆包智能体提示词.txt"
    prompt_path.write_text(PROMPT, encoding="utf-8")

    print(f"已生成豆包导入包（共 {len(data)} 条知识）：")
    print(f"  1. {kb_path}")
    print(f"  2. {prompt_path}")


if __name__ == "__main__":
    main()
