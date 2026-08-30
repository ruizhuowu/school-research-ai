# 学校调研多智能体分析平台（Streamlit 版）

基于 **6 智能体流水线** 的学校调研数据分析工具，完整保留原 Web 版的六大防护层：

| 防护层 | 说明 | 实现 |
|---|---|---|
| L1 降级兜底 | 无 API Key / AI 超时自动切换规则引擎，产品永远可用 | `rule_engine.py` |
| L2 风险提示 | AI 结果须人工核对提示 | Streamlit UI |
| L3 模式透明 | AI / 规则模式徽章明示 | Streamlit UI |
| L4 人工确认 | 优先级矩阵可编辑，得分自动重算 | `st.data_editor` |
| L5 来源追溯 | 每条痛点带原文 source 片段 | 数据模型 |
| L6 上下文工程 | 输入清洗 + 长文本分块并行提取 + 上下文裁剪 | `analyzer.py` |

## 三大 AI 工程

- **提示词工程**：6 个智能体独立 SYSTEM_PROMPT（角色 + 铁律），JSON Schema 锚定、CoT 引导、温度控制、V3/R1 模型分工
- **上下文工程**：输入清洗（去重/去噪）→ 长文本按句分块并行提取合并去重 → 策略员上下文裁剪（只喂 top-5 高分痛点）
- **Harness 工程**：JSON 三级容错解析、两级降级兜底、输入校验、结果可编辑闭环、SQLite 历史持久化

## 本地运行

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

- 不填 API Key → 自动降级为规则模式（可完整体验全流程）
- 填入 DeepSeek API Key → 使用完整 6 智能体 AI 流水线

## 部署到 Streamlit Community Cloud（免费）

1. 将本项目推送到 GitHub 仓库（`streamlit_app.py`、`requirements.txt`、`.streamlit/` 均在根目录，Streamlit 会自动识别）
2. 打开 [share.streamlit.io](https://share.streamlit.io) → 用 GitHub 登录 → **Create app**
3. 选择仓库 / 分支 / 主文件为 `streamlit_app.py` → **Deploy**
4. （可选）在 App 的 **Settings → Secrets** 中配置 `DEEPSEEK_API_KEY`，这样无需在页面手填 Key 也能使用 AI 模式

## 历史记录持久化（双后端 + 按用户隔离 + 搜索）

**个人数据仓库**：侧边栏输入「用户名」后，每次分析结果自动保存到**自己名下**；「历史记录」页只显示自己名下的数据，支持**关键词搜索**（如：维修、广告、网络…），随时找回之前提交的分析。

**本地（默认，零配置）**：数据保存到项目目录下的 `analysis_history.db`（本地 SQLite），重启不丢失，无需任何环境变量或云服务。

**云端（可选部署方案）**：仓库附带 `supabase_schema.sql`（PostgreSQL 建表脚本，含 `username` 用户隔离、索引与 RLS 安全策略）。如需在 Streamlit Cloud 上实现跨设备持久化，可在 Supabase Studio → SQL Editor 中执行该脚本，再配置 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 环境变量即可；未配置时自动使用本地 SQLite，不影响任何功能。

## 文件结构

```
streamlit_app.py    # 主应用（UI + 编排）
analyzer.py         # 6 智能体流水线 + 上下文工程 + 降级（DeepSeek API）
rule_engine.py      # 规则模式引擎（零依赖兜底）
supabase_schema.sql # 可选：Supabase 云端持久化建表脚本（PostgreSQL）
requirements.txt    # 依赖
.streamlit/config.toml  # 暗色主题
```

> 仓库同时保留 Vercel 版（`api/` + `index.html`），两者可并存，互不影响。
