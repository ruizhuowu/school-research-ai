-- ============================================================
-- 学校调研多智能体分析平台 · Supabase 建表 SQL（PostgreSQL）
-- ------------------------------------------------------------
-- 用途：可选云端持久化方案。
--   本地运行时 Streamlit 版默认使用 SQLite（零配置）；
--   如需部署到 Streamlit Cloud 且希望历史记录跨重启保留，
--   可在 Supabase Studio → SQL Editor 中执行本脚本。
-- ============================================================

-- 历史分析记录表（按用户名隔离：每个用户只能查/删自己名下的数据）
CREATE TABLE IF NOT EXISTS public.analyses (
  id                BIGSERIAL PRIMARY KEY,           -- 自增主键
  username          TEXT NOT NULL DEFAULT '访客',    -- 所属用户（数据隔离依据）
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(), -- 分析时间
  mode              TEXT NOT NULL,                   -- 分析模式：ai / rule
  total_pain_points INTEGER,                         -- 提取痛点总数
  p0                INTEGER,                         -- P0 紧急问题数
  p1                INTEGER,                         -- P1 问题数
  p2                INTEGER,                         -- P2 问题数
  top_category      TEXT,                            -- 最大问题类别
  strategy_count    INTEGER,                         -- 优化策略数量
  input_snippet     TEXT,                            -- 输入摘要（前120字）
  input_text        TEXT,                            -- 完整输入（前500字）
  result_json       JSONB                            -- 完整分析结果
);

-- 常用索引：按用户 + 时间倒序查询（历史列表页）
CREATE INDEX IF NOT EXISTS idx_analyses_user_time
  ON public.analyses (username, created_at DESC);

-- 行级安全策略：默认开启 RLS（Supabase 最佳实践）
ALTER TABLE public.analyses ENABLE ROW LEVEL SECURITY;

-- 允许匿名用户读写（配合 anon key 使用；如需更严格可改为仅认证用户）
DROP POLICY IF EXISTS "anon_all" ON public.analyses;
CREATE POLICY "anon_all" ON public.analyses
  FOR ALL USING (true) WITH CHECK (true);
