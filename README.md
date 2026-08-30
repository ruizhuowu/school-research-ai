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

## 历史记录持久化（双后端 + 按用户隔离 + 双重搜索）

**个人数据仓库**：侧边栏输入「用户名」后，每次分析结果自动保存到**自己名下**；「历史记录」页只显示自己名下的数据，支持**关键词搜索**和**AI 语义检索**，随时找回之前提交的分析。

**本地（默认，零配置）**：数据保存到项目目录下的 `analysis_history.db`（本地 SQLite），重启不丢失，无需任何环境变量或云服务。

**云端（可选部署方案）**：仓库附带 `supabase_schema.sql`（PostgreSQL 建表脚本，含 `username` 用户隔离、索引与 RLS 安全策略）。如需在 Streamlit Cloud 上实现跨设备持久化，可在 Supabase Studio → SQL Editor 中执行该脚本，再配置 `SUPABASE_URL` / `SUPABASE_ANON_KEY` 环境变量即可；未配置时自动使用本地 SQLite，不影响任何功能。

## AI 语义检索（用一句话找历史）

历史记录页内置「AI 语义检索」：输入一句自然语言问题（如"哪些记录提到了设备死机？"），系统会自动找出语义最相关的历史分析。

- 原理：每次分析保存时，把「原文 + 类别 + 摘要」编码为向量（embedding）；检索时把问题编码为向量，按余弦相似度排序返回 top-10
- 需要配置 `EMBEDDING_API_KEY`（默认对接**硅基流动 SiliconFlow 的免费 bge-m3 模型**，注册即送额度，OpenAI 兼容接口）
- 未配置时语义检索自动隐藏，关键词搜索不受影响

### 获取免费 Embedding Key（硅基流动，2 分钟）

1. 打开 <https://cloud.siliconflow.cn> 注册登录（手机号即可）
2. 左侧「API 密钥」→ 新建密钥 → 复制（形如 `sk-...`）
3. 填入下方任一位置即可

### 配置方式

**Streamlit Cloud（推荐）**：Settings → Secrets 里加入：

```toml
DEEPSEEK_API_KEY = "sk-..."
EMBEDDING_API_KEY = "sk-..."
# 可选：默认已指向硅基流动，也可换其他 OpenAI 兼容服务
# EMBEDDING_BASE_URL = "https://api.siliconflow.cn/v1"
# EMBEDDING_MODEL = "BAAI/bge-m3"
SUPABASE_URL = "https://你的项目.supabase.co"
SUPABASE_ANON_KEY = "eyJ..."
```

**本地运行**：设置环境变量（PowerShell）：
```powershell
$env:EMBEDDING_API_KEY="sk-..."
streamlit run streamlit_app.py
```

> 注意：只有配置 Key 之后**新产生**的历史记录才会带向量；更早的记录可通过重新分析补上向量。

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
