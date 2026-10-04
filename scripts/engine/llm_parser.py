# -*- coding: utf-8 -*-
"""
llm_parser.py —— 第二阶段：用 LLM 把大白话问题解析成结构化情境。

替代 lexicon.py 里规则式的 parse_question()，但输出契约完全一致。

红线（务必遵守）：
  * 只替换「解析」环节，绝不碰 knowledge_engine._resolve_cond 的适用性判定。
    verify 的判定必须保持确定、可解释（用户要的是「为什么这条不适用」，
    而不是「AI 觉得不适用」）。
  * 输出必须与 lexicon.parse_question 同构，且严格受控：
      - domain   ⊆ {1..34}（章节编号）
      - intent   ∈ INTENT_VOCAB（12 个受控词）
      - features 的 key 必须是 _resolve_cond 会消费的那几个
  * LLM 不可用 / 输出非法 / 识别不出领域时，回退到规则版 parse_question，
    保证系统永不瘫痪。

配置（按优先级，找到即用）：
  1. 环境变量 DEEPSEEK_API_KEY
  2. 项目根目录 llm_config.json 的 api_key 字段
两者都没有 → get_parser() 返回 None → 引擎自动用规则版。
"""
import json
import os
import re
import urllib.request
from pathlib import Path

from lexicon import INTENT_VOCAB, CHAPTER_NAMES, parse_question as rule_parse

# ---------------------------------------------------------------------------
# 受控 schema
# ---------------------------------------------------------------------------
VALID_DOMAINS = set(range(1, 35))

# features 里 LLM 可以输出的 key（与 _resolve_cond 消费的字段对齐）
FEATURE_KEYS = ["landlord_type", "housing_type", "resign_type", "prepay", "budget", "duration_years"]

# 各 feature 的合法取值（其余一律置 None，不臆造）
FEATURE_ENUMS = {
    "landlord_type": {"个人房东", "长租公寓/转租企业"},
    "housing_type": {"租房", "买房"},
    "resign_type": {"主动辞职", "被裁/被辞退"},
}

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = SKILL_ROOT / "llm_config.json"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 20


def _build_system_prompt() -> str:
    chapters = "\n".join(f"  {n} = {name}" for n, name in sorted(CHAPTER_NAMES.items()))
    intents = "、".join(INTENT_VOCAB)
    return f"""你是一个「人生决策知识库」的查询解析器。你的唯一任务：把用户的大白话问题，解析成一个结构化 JSON。不要回答用户的问题，不要给建议，只做解析。

## 章节编号表（domain 只能从这些编号里选，用数组）
{chapters}

## 用户意图受控词表（intent 只能从这里面选一个）
{intents}

## features 字段说明（不确定的填 null，绝对不要猜）
- landlord_type：房东类型。仅当问题涉及租房时填。「个人房东」或「长租公寓/转租企业」
- housing_type：租房还是买房。「租房」或「买房」
- resign_type：离职类型。「主动辞职」或「被裁/被辞退」
- prepay：是否涉及「一次性预付多月/一年」这类预付。布尔值
- budget：提到的预算金额（如「6000块」）。没有则 null
- duration_years：提到的使用/持有年限数字字符串。没有则 null

## 关键判定（务必准确，这直接影响下游适用性过滤）
- 问题里出现「房东」「房租」「租金」「押金」等，通常 landlord_type=个人房东；
  出现「长租公寓」「自如」「蛋壳」「品牌公寓」「转租」等才是「长租公寓/转租企业」。
- 「主动辞职」和「被裁」要分清：说「我想辞职」「要不要辞职」是主动辞职；
  说「被裁」「被优化」「公司辞退我」才是被裁/被辞退。

## 输出要求
- 只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。
- JSON 结构固定为：
  {{"domain": [章节编号数组], "object": "对象名", "intent": "意图", "risk": "风险线索词或null", "features": {{"landlord_type": null, "housing_type": null, "resign_type": null, "prepay": false, "budget": null, "duration_years": null}}}}
- object 用简短名词（如 电子设备、汽车、房屋、租赁、工作、学习、健康、投资、保险）。
- risk 只填用户明确表达的担心词（担心/怕/风险/会不会/值不值等），没有就 null。
"""


_FEW_SHOTS = [
    ("房东让我一次交一年房租，我有点担心。",
     {"domain": [15], "object": "租赁", "intent": "租房买房", "risk": "担心",
      "features": {"landlord_type": "个人房东", "housing_type": "租房", "resign_type": None,
                   "prepay": True, "budget": None, "duration_years": None}}),
    ("我不知道要不要辞职。",
     {"domain": [19], "object": "工作", "intent": "离职维权", "risk": None,
      "features": {"landlord_type": None, "housing_type": None, "resign_type": "主动辞职",
                   "prepay": False, "budget": None, "duration_years": None}}),
    ("我准备买一台6000块左右的电脑。",
     {"domain": [5], "object": "电子设备", "intent": "消费决策", "risk": None,
      "features": {"landlord_type": None, "housing_type": None, "resign_type": None,
                   "prepay": False, "budget": "6000块", "duration_years": None}}),
]


def _build_messages(question: str) -> list:
    msgs = [{"role": "system", "content": _build_system_prompt()}]
    for q, a in _FEW_SHOTS:
        msgs.append({"role": "user", "content": q})
        msgs.append({"role": "assistant", "content": json.dumps(a, ensure_ascii=False)})
    msgs.append({"role": "user", "content": question})
    return msgs


class LLMParser:
    """LLM 情境解析器。输出与 lexicon.parse_question 同构。"""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL,
                 model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout
        self._cache = {}

    def _call(self, question: str) -> dict:
        payload = json.dumps({
            "model": self.model,
            "messages": _build_messages(question),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        # 容错：某些兼容实现会包一层 markdown 代码块
        content = re.sub(r"^```(json)?\s*|\s*```$", "", content.strip())
        return json.loads(content)

    def _normalize(self, raw: dict, question: str) -> dict:
        domain = []
        for d in raw.get("domain") or []:
            try:
                d = int(d)
            except (TypeError, ValueError):
                continue
            if d in VALID_DOMAINS:
                domain.append(d)
        domain = list(dict.fromkeys(domain))

        intent = raw.get("intent") or ""
        if intent not in INTENT_VOCAB:
            intent = ""

        features = {}
        src = raw.get("features") or {}
        for k in FEATURE_KEYS:
            v = src.get(k)
            if k in FEATURE_ENUMS:
                features[k] = v if v in FEATURE_ENUMS[k] else None
            elif k == "prepay":
                features[k] = bool(v)
            else:
                features[k] = str(v) if v not in (None, "") else None

        return {
            "question": question,
            "domain": domain,
            "object": str(raw.get("object") or "").strip(),
            "intent": intent,
            "risk": str(raw.get("risk") or "").strip() or "",
            "features": features,
        }

    def parse(self, question: str) -> dict:
        """解析问题。LLM 结果若识别不出领域，回退到规则版。"""
        if question in self._cache:
            return self._cache[question]
        try:
            raw = self._call(question)
            sit = self._normalize(raw, question)
        except Exception:
            sit = None

        # 领域是召回的门槛；LLM 连领域都没识别出来 → 规则版兜底更可靠
        if sit is None or not sit["domain"]:
            sit = rule_parse(question)

        self._cache[question] = sit
        return sit

    def __call__(self, question: str) -> dict:
        """让 LLMParser 对象可以像函数一样被引擎调用：engine(question)。"""
        return self.parse(question)


def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.is_file():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    return cfg


def get_parser():
    """返回 LLMParser；无可用 key 时返回 None（调用方回退规则版）。"""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    cfg = load_config()
    if not api_key:
        api_key = cfg.get("api_key", "")
    if not api_key:
        return None
    return LLMParser(
        api_key=api_key,
        base_url=cfg.get("base_url", DEFAULT_BASE_URL),
        model=cfg.get("model", DEFAULT_MODEL),
        timeout=int(cfg.get("timeout", DEFAULT_TIMEOUT)),
    )


if __name__ == "__main__":
    p = get_parser()
    if p is None:
        print("未配置 DEEPSEEK_API_KEY，使用规则版演示：")
        for q, _ in _FEW_SHOTS:
            print("  Q:", q)
            print("  →", json.dumps(rule_parse(q), ensure_ascii=False))
    else:
        for q, _ in _FEW_SHOTS:
            print("  Q:", q)
            print("  →", json.dumps(p.parse(q), ensure_ascii=False))
