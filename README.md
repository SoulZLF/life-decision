# life-decision · 人生决策顾问

基于《高性价比人生指南》的结构化知识库技能：把大白话的人生决策问题，映射到 **654 条循证知识**，只给「真正适用」的建议，过滤掉「看起来相关、实际上不适用」的。

> 核心原则：**相关 ≠ 适用**。每条知识都标注了【适用条件】【不适用条件】和证据等级（A/B/C），回答前先做确定性过滤。

---

## 它解决什么

买房、租房、离职、保险、消费、健康、法律红线……这些人生决策，网上不缺说法，缺的是「每条都有出处、还告诉你值不值」的说法。本技能基于《高性价比人生指南》（每条写明成本、收益、证据等级、原始出处），并加上一层「适用性过滤」，避免 AI 拿「相关但不适用」的知识误导你。

## 三种用法

### 用法 1 · 作为 Agent Skill（WorkBuddy / Claude Code / Cursor）

把整个目录拷到对应工具的 skill 目录即可：

| 工具 | 目标目录 |
|------|----------|
| WorkBuddy | `~/.workbuddy/skills/life-decision/` |
| Claude Code | `~/.claude/skills/life-decision/` |
| Cursor | `~/.cursor/skills/life-decision/` |

装好依赖后，直接问「房东让我一次交一年房租，我有点担心」这类问题即可触发。

### 用法 2 · 走 MCP（任意 MCP 客户端，可编程调用）

把本目录放好，在你的 MCP 客户端配置里加一条：

```json
{
  "mcpServers": {
    "knowledge": {
      "command": "python",
      "args": ["/你的路径/life-decision/scripts/mcp_server/knowledge_mcp.py"]
    }
  }
}
```

暴露 4 个工具：`search_knowledge`（召回）、`verify_knowledge`（适用性判定）、`get_knowledge_item`、`get_related_items`。

### 用法 3 · 纯文档 / 飞书「豆包工作」（零代码、零依赖）

不需要 Python，直接读 `references/人生决策知识库.md`（654 条，含适用/不适用条件），喂给任何 AI 或上传到飞书「豆包工作」的技能里。

飞书操作：豆包工作 → 技能 → 上传技能 → 选择 `life-decision.zip`（或直接传 `references/人生决策知识库.md` + `SKILL.md`）。

---

## 安装依赖（用法 1、2 需要）

需要 **Python 3.10+**：

```bash
pip install -r requirements.txt
```

- `jieba`（必需，中文分词）
- `mcp`（可选，仅走 MCP 时需要）

## 数据从哪来

知识来自开源项目《高性价比人生指南》：[github.com/eternity4719/HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)（Unlicense 公有领域，可自由使用、引用、商用）。

## 更新知识（仓库持续更新）

原作者仓库会持续更新。同步最新知识、重建索引、重新导出飞书包：

```bash
python scripts/sync_update.py
```

它用 `urllib` 直接下载 GitHub tarball（无需 git），把 `book/` 下 34 个章节拼成一份 → 解析 → 重建 `references/knowledge_index.json` 和 `人生决策知识库.md` → 导出 `exports/` 下的飞书/豆包包。

## 目录结构

```
life-decision/
├── SKILL.md                    技能入口（触发条件 + 决策流程 + 铁律）
├── README.md                   本文件
├── requirements.txt            依赖
├── references/                 知识数据（自包含，随目录一起分发）
│   ├── knowledge_index.json      结构化索引（引擎用）
│   ├── raw_entries.json          原始解析结果
│   └── 人生决策知识库.md          纯文档版（零依赖消费 / 飞书用）
├── scripts/
│   ├── query.py                  本地 CLI：解析→召回→判定 一次跑完
│   ├── sync_update.py            从 GitHub 同步最新知识并重建
│   ├── engine/                   引擎（纯 Python，自包含）
│   └── mcp_server/               MCP 接口（可选）
└── templates/                   飞书 SKILL.md 模板
```

## 引擎的工作方式

主 Agent 自己解析用户情境（不走外部大模型）→ 引擎召回候选 → 引擎做**确定性**适用性过滤 → 输出结论。适用性判定是规则逻辑，不由 LLM 替代，避免「相关 ≠ 适用」被大模型糊弄过去。

## 许可

数据源自《高性价比人生指南》（Unlicense）。本目录的代码与整理一并沿用 **Unlicense**，可自由使用、修改、分发、商用。

## 免责声明

知识库给的是通用口径，不替代医生、律师、会计等专业人士。涉及具体病情、案件、税务的，请咨询专业人士。
