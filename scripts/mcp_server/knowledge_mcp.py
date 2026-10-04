# -*- coding: utf-8 -*-
"""
knowledge_mcp.py —— Knowledge MCP 服务器。

主 Agent 不再直接读取 Markdown，而是通过以下四个工具查询知识：

  1. search_knowledge    —— 按用户问题召回候选知识（只召回 + 排序，不判断适用性）
  2. get_knowledge_item  —— 按 ID 取回完整知识原文、证据等级、来源
  3. get_related_items   —— 按 ID 取回相关知识
  4. verify_knowledge    —— 判断候选知识对当前问题的适用性

启动方式（stdio）：
  python3 knowledge_mcp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

from knowledge_engine import KnowledgeEngine
from llm_parser import get_parser
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("knowledge")

# 第二阶段：优先 LLM 解析，未配置 key 时 get_parser() 返回 None → 自动回退规则版
_engine = KnowledgeEngine(parser=get_parser())


@mcp.tool()
def search_knowledge(
    question: str,
    category: str = "",
    intent: str = "",
    keywords: str = "",
    top_k: int = 18,
) -> dict:
    """按用户的大白话问题召回候选知识。

    参数：
      question: 用户的原问题（大白话）
      category: 可选，领域（章节号/章节名/大白话词，如 "租房"、"15"、"不要浪费钱"）
      intent:   可选，用户意图（如 "消费决策"、"离职维权"）
      keywords: 可选，补充关键词
    返回：候选知识 ID、标题、匹配原因、相关程度、证据等级。
    注意：本工具只负责「召回 + 相关性排序」，不判断是否真正适用。
    """
    return _engine.search_knowledge(
        question=question,
        category=category or None,
        intent=intent or None,
        keywords=keywords or None,
        top_k=top_k,
    )


@mcp.tool()
def get_knowledge_item(knowledge_id: str) -> dict:
    """按知识 ID 取回完整内容。

    返回：该条知识的标题、正文原文、证据等级、来源、来源 ID、适用/不适用条件等。
    """
    return _engine.get_knowledge_item(knowledge_id)


@mcp.tool()
def get_related_items(knowledge_id: str, top_k: int = 8) -> dict:
    """按知识 ID 取回相关知识（同领域 / 同主题 / 同意图）。"""
    return _engine.get_related_items(knowledge_id, top_k=top_k)


@mcp.tool()
def verify_knowledge(question: str, candidate_ids: list[str]) -> dict:
    """判断候选知识对当前问题是否适用。

    参数：
      question:      用户的原问题
      candidate_ids: 候选知识 ID 列表
    返回：每条知识的判定结果——applicable / possibly_applicable / not_applicable，
          并附带判断依据。
    """
    return _engine.verify_knowledge(question, candidate_ids)


if __name__ == "__main__":
    mcp.run()
