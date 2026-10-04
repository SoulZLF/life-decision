# -*- coding: utf-8 -*-
"""
knowledge_engine.py —— 知识检索与适用性判断核心（与 MCP 无关，可独立测试）。

对外方法：
  search_knowledge(question, category=None, intent=None, keywords=None)
  get_knowledge_item(knowledge_id)
  get_related_items(knowledge_id)
  verify_knowledge(question, candidate_ids)

原则：
  * 检索只做「召回 + 相关性排序」，不判断适用性。
  * 适用性由 verify_knowledge 单独判断。
  * 「相关」≠「适用」：召回候选后必须过 verify。
"""
import json
import os
import re
from pathlib import Path

import jieba

from lexicon import CATEGORY_ALIASES, INTENT_VOCAB, CHAPTER_NAMES, MEANINGFUL_SINGLE, STOPWORDS, parse_question as rule_parse_question

SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = Path(os.environ.get("LIFE_DECISION_INDEX", SKILL_ROOT / "references" / "knowledge_index.json"))

TOP_K = 18


def _tokens(text: str) -> list[str]:
    toks = []
    for t in jieba.cut(text):
        t = t.strip()
        if not t:
            continue
        if len(t) == 1 and t not in MEANINGFUL_SINGLE:
            continue
        if t in STOPWORDS:
            continue
        if re.fullmatch(r"[\d\.%＋\-]+", t):
            continue
        toks.append(t)
    return toks


class KnowledgeEngine:
    def __init__(self, index_path: Path = INDEX_PATH, parser=None):
        self.items = json.loads(index_path.read_text(encoding="utf-8"))
        self._by_id = {i["id"]: i for i in self.items}
        # 章节号 → 条目
        self._by_chapter = {}
        for i in self.items:
            self._by_chapter.setdefault(i["chapter"], []).append(i)
        # 情境解析器：默认规则版；可注入 LLM 版（第二阶段）
        self.parser = parser or rule_parse_question

    def _parse(self, question: str) -> dict:
        return self.parser(question)

    # ------------------------------------------------------------------
    # 工具 1：search_knowledge
    # ------------------------------------------------------------------
    def search_knowledge(self, question: str, category=None, intent=None, keywords=None, top_k: int = TOP_K, situation=None):
        if situation is None:
            situation = self._parse(question)
        else:
            situation = dict(situation)
            situation.setdefault("question", question)

        # 确定候选领域
        target_chapters = set()
        if category is not None:
            target_chapters |= self._resolve_category(category)
        if intent is not None:
            for ch, intents in _chapter_of_intent().items():
                if intent in intents:
                    target_chapters.add(ch)
        target_chapters |= set(situation["domain"])

        q_tokens = _tokens(question)
        if keywords:
            q_tokens += _tokens(str(keywords))

        have_domain = bool(target_chapters)
        is_purchase = bool(re.search(r"买|购", question)) and bool(situation.get("object"))

        scored = []
        for it in self.items:
            score = 0.0
            reasons = []

            # 1) 领域（章节）匹配
            cat_match = it["chapter"] in target_chapters
            if cat_match:
                score += 3.0
                reasons.append(f"领域匹配：{it['category']}")

            # 2) 意图匹配（只加权，不作为召回门槛）
            q_intent = intent or situation["intent"]
            intent_match = bool(q_intent and q_intent in it["user_intents"])
            if intent_match:
                score += 2.0
                reasons.append(f"意图匹配：{q_intent}")

            # 3) 关键词命中（标题权重更高）
            title_text = it["title"]
            body_text = it["说人话"]
            title_hits = 0
            body_hits = 0
            for tok in q_tokens:
                if tok in title_text:
                    title_hits += 1
                if tok in body_text:
                    body_hits += 1
            score += title_hits * 1.5 + body_hits * 0.6
            if title_hits:
                reasons.append(f"标题命中 {title_hits} 个关键词")
            if body_hits:
                reasons.append(f"正文命中 {body_hits} 个关键词")

            # 4) 购买场景加权：用户要买东西时，购买决策类条目更相关
            if is_purchase and re.search(
                r"购买|大件|大额|冷静期|退货|延保|分期|消费贷|预付款|三者险|交强险",
                it["title"],
            ):
                score += 2.0
                reasons.append("购买场景命中")

            # 召回门槛：
            #  领域已明确 → 只召回「领域命中」的条目（意图/关键词只用于排序）
            #  领域未明确 → 退化为关键词召回
            if have_domain:
                if not cat_match:
                    continue
            else:
                if title_hits == 0 and body_hits == 0:
                    continue

            if score >= 2.0:
                scored.append((score, it, reasons))

        scored.sort(key=lambda x: -x[0])

        # 每个领域最多保留 top_per_chapter 条，避免单一领域占满结果
        top_per_chapter = 10
        per_chapter = {}
        for s, it, rs in scored:
            ch = it["chapter"]
            if len(per_chapter.get(ch, [])) < top_per_chapter:
                per_chapter.setdefault(ch, []).append((s, it, rs))
        diversified = [x for lst in per_chapter.values() for x in lst]
        diversified.sort(key=lambda x: -x[0])

        results = []
        for score, it, reasons in diversified:
            results.append({
                "knowledge_id": it["id"],
                "title": it["title"],
                "match_reasons": reasons,
                "relevance": round(min(score / 10.0, 1.0), 2),
                "evidence_level": it["evidence_level"],
                "category": it["category"],
            })
            if len(results) >= top_k:
                break
        return {
            "question": question,
            "parsed": {k: v for k, v in situation.items() if k != "question"},
            "candidates": results,
        }

    def _resolve_category(self, category) -> set:
        """category 参数：接受章节号、章节名、或大白话词。"""
        chapters = set()
        if isinstance(category, int):
            chapters.add(category)
            return chapters
        s = str(category)
        # 直接是章节号
        if re.fullmatch(r"\d+", s):
            chapters.add(int(s))
            return chapters
        # 章节名
        for ch, name in CHAPTER_NAMES.items():
            if s in name or name in s:
                chapters.add(ch)
        # 大白话别名
        for alias, chs in CATEGORY_ALIASES.items():
            if alias in s or s in alias:
                chapters.update(chs)
        return chapters

    # ------------------------------------------------------------------
    # 工具 2：get_knowledge_item
    # ------------------------------------------------------------------
    def get_knowledge_item(self, knowledge_id: str):
        it = self._by_id.get(knowledge_id)
        if it is None:
            return {"found": False, "knowledge_id": knowledge_id}
        return {"found": True, "item": it}

    # ------------------------------------------------------------------
    # 工具 3：get_related_items
    # ------------------------------------------------------------------
    def get_related_items(self, knowledge_id: str, top_k: int = 8):
        base = self._by_id.get(knowledge_id)
        if base is None:
            return {"found": False, "knowledge_id": knowledge_id}
        base_kw = set(base["keywords"])
        base_topics = set(base["topics"])
        base_intents = set(base["user_intents"])
        scored = []
        for it in self.items:
            if it["id"] == knowledge_id:
                continue
            s = 0.0
            if it["chapter"] == base["chapter"]:
                s += 3.0
            s += len(base_kw & set(it["keywords"])) * 0.5
            s += len(base_topics & set(it["topics"])) * 1.0
            s += len(base_intents & set(it["user_intents"])) * 1.0
            if s > 0:
                scored.append((s, it))
        scored.sort(key=lambda x: -x[0])
        return {
            "found": True,
            "knowledge_id": knowledge_id,
            "related": [
                {
                    "knowledge_id": it["id"],
                    "title": it["title"],
                    "category": it["category"],
                    "evidence_level": it["evidence_level"],
                }
                for _, it in scored[:top_k]
            ],
        }

    # ------------------------------------------------------------------
    # 工具 4：verify_knowledge
    # ------------------------------------------------------------------
    def verify_knowledge(self, question: str, candidate_ids, situation=None):
        if situation is None:
            situation = self._parse(question)
        else:
            situation = dict(situation)
            situation.setdefault("question", question)
        verdicts = []
        for cid in candidate_ids:
            it = self._by_id.get(cid)
            if it is None:
                verdicts.append({"knowledge_id": cid, "verdict": "not_applicable",
                                 "reasons": ["知识库中不存在该 ID"]})
                continue
            verdicts.append(self._verify_one(it, situation))
        return {
            "question": question,
            "situation": {k: v for k, v in situation.items() if k != "question"},
            "results": verdicts,
        }

    def _verify_one(self, it: dict, situation: dict) -> dict:
        applies = it.get("applies_when") or []
        not_applies = it.get("does_not_apply_when") or []
        reasons = []

        # 1) 不适用条件：任一命中 → 不适用
        for cond in not_applies:
            r = self._resolve_cond(cond, situation)
            if r is True:
                reasons.append(f"命中「不适用」条件：{cond}")
                return {"knowledge_id": it["id"], "title": it["title"],
                        "verdict": "not_applicable", "reasons": reasons}

        # 2) 适用条件：逐条判断
        all_true = True
        has_explicit_false = False
        for cond in applies:
            r = self._resolve_cond(cond, situation)
            if r is False:
                has_explicit_false = True
                reasons.append(f"不满足「适用」条件：{cond}")
                all_true = False
            elif r is None:
                reasons.append(f"无法确定是否满足：{cond}")
                all_true = False

        if not applies:
            # 无显式适用条件：不做「明确适用」判定，交由上下文确认
            reasons.append("本条无显式适用条件，需结合上下文判断")
            return {"knowledge_id": it["id"], "title": it["title"],
                    "verdict": "possibly_applicable", "reasons": reasons}

        if has_explicit_false:
            return {"knowledge_id": it["id"], "title": it["title"],
                    "verdict": "not_applicable", "reasons": reasons}
        if all_true:
            reasons.append("适用条件全部满足")
            return {"knowledge_id": it["id"], "title": it["title"],
                    "verdict": "applicable", "reasons": reasons}
        reasons.append("部分条件无法确认，需结合上下文")
        return {"knowledge_id": it["id"], "title": it["title"],
                "verdict": "possibly_applicable", "reasons": reasons}

    # 把条件短语解析成「针对当前情境」的真/假/未知
    def _resolve_cond(self, cond: str, situation: dict):
        q = situation["question"]
        f = situation.get("features", {})
        obj = situation.get("object", "")

        def has(*words):
            return any(w in q for w in words)

        # === 离职类型 ===
        if "主动辞职" in cond:
            return f.get("resign_type") == "主动辞职"
        if any(k in cond for k in ["被裁", "裁员", "辞退", "解雇"]) and "主动" not in cond:
            return f.get("resign_type") == "被裁/被辞退"
        if any(k in cond for k in ["违法解除", "合法解除", "经济性裁员"]):
            return None

        # === 房东 / 中介 ===
        if "个人房东" in cond or "房东是个人" in cond:
            return f.get("landlord_type") == "个人房东"
        if "长租公寓" in cond or "转租" in cond:
            return f.get("landlord_type") == "长租公寓/转租企业"
        if "中介" in cond:
            # 否定语义：「无中介参与」「不含中介」→ 要求问题里没有中介
            if "无中介" in cond or "不含中介" in cond:
                return "中介" not in q
            return True if "中介" in q else None

        # === 租期内房屋被转卖 / 买卖不破租赁 ===
        if any(k in cond for k in ["被转卖", "被卖掉", "买卖不破", "换房东", "换房主"]):
            if has("被卖", "卖掉", "转卖", "卖了", "买卖不破", "换房东", "新房东", "换房主", "过户", "所有权变"):
                return True
            return False

        # === 租房 vs 买房 ===
        if any(k in cond for k in ["租房", "签约", "押金", "房租", "租金"]):
            if has("租房", "房东", "房租", "租金", "押金", "租"):
                return True
            return None
        if "买房" in cond or "购房" in cond or "二手房" in cond:
            if has("买房", "购房", "二手房", "首付", "房贷"):
                return True
            if f.get("housing_type") == "租房":
                return False
            return None
        if "搬到乡下" in cond or "乡下" in cond:
            if has("乡下", "农村", "农房", "宅基地"):
                return True
            return None

        # === 预付 / 充值 ===
        if any(k in cond for k in ["预付", "一次性付", "充值", "预付费", "预付大额"]):
            # 否定语义：「无预付」「一手交钱一手交货」→ 要求没有预付
            if "无预付" in cond or "一手交钱" in cond:
                return not (f.get("prepay", False) or has("充值", "预付", "一次付", "预交"))
            return f.get("prepay", False) or has("充值", "预付", "一次付", "预交")

        # === 离职动作 ===
        if "被要求签" in cond or "被要求" in cond:
            return None
        if "拿到离职" in cond or "获得经济补偿" in cond:
            return None
        if any(k in cond for k in ["离职", "辞职", "裸辞"]):
            return True if has("离职", "辞职", "裸辞", "不干", "跳槽") else None

        # === 对象类型：电子产品 / 大件 ===
        if any(k in cond for k in ["电子产品", "家电", "大件商品", "大件"]):
            if obj == "电子设备":
                return True
            if has("电脑", "笔记本", "手机", "平板", "家电", "冰箱", "洗衣机", "电视", "空调"):
                return True
            if obj == "汽车":
                return False
            return None

        # === 对象类型：汽车 ===
        if "无机动车" in cond or "不开车" in cond:
            return not has("车", "开车")
        if any(k in cond for k in ["汽车", "机动车"]):
            if obj == "汽车" or has("买车", "购车", "车", "开车", "车险", "交强险", "三者险"):
                return True
            return None

        # === 投资 ===
        if any(k in cond for k in ["股票", "基金", "投资", "理财"]):
            return True if has("股票", "基金", "投资", "理财", "炒股") else None

        # === 健身 / 办卡 ===
        if any(k in cond for k in ["健身", "年卡", "办卡"]):
            return True if has("健身", "年卡", "办卡", "会员") else None

        # === 住处 / 通勤 ===
        if "住处" in cond or "通勤" in cond:
            return True if has("搬家", "住处", "通勤", "租房", "买房", "住") else None

        # === 兜底：条件核心词出现在问题里 ===
        core = re.sub(r"[（）()]", "", cond)
        for kw in re.split(r"[、，,，/]", core):
            kw = kw.strip()
            if len(kw) >= 2 and kw in q:
                return True
        return None


def _chapter_of_intent():
    """意图 → 章节（供 search 用）。"""
    from lexicon import CHAPTER_INTENTS
    mapping = {}
    for ch, intents in CHAPTER_INTENTS.items():
        for it in intents:
            mapping.setdefault(it, []).append(ch)
    return mapping


if __name__ == "__main__":
    eng = KnowledgeEngine()
    print("引擎加载完成：", len(eng.items), "条知识")
