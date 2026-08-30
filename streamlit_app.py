# -*- coding: utf-8 -*-
"""
学校调研多智能体分析平台 — Streamlit 版
------------------------------------------------------------
六大防护层完整保留：
  L1 降级兜底（规则引擎）   L2 风险提示    L3 模式透明
  L4 人工确认（结果可编辑） L5 来源追溯    L6 上下文工程（清洗/分块/裁剪）
"""
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components

from analyzer import analyze, get_top_category

st.set_page_config(
    page_title='学校调研多智能体分析平台',
    page_icon='🤖',
    layout='wide',
    initial_sidebar_state='expanded',
)

# ============================================================
# 全局样式（GitHub Dark 风格，还原原版视觉效果）
# ============================================================
CSS = """
<style>
  .grad-header {
    background: linear-gradient(135deg, #1a1f35 0%, #0d1117 100%);
    border: 1px solid #21262d;
    border-radius: 12px;
    padding: 18px 24px;
    margin-bottom: 8px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .grad-header .t { font-size: 22px; font-weight: 800; color: #fff; }
  .grad-header .s { font-size: 12px; color: #8b949e; margin-top: 2px; }
  .grad-header .b {
    background: linear-gradient(135deg, #7c3aed22, #3b82f622);
    border: 1px solid #7c3aed44; color: #a78bfa;
    padding: 4px 14px; border-radius: 20px; font-size: 12px;
  }
  .arch-row { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0 14px 0; }
  .arch-item {
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 6px 12px; font-size: 12px; color: #8b949e;
  }
  .v3-tag { background: #0d4a3a; color: #3ddc84; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600; }
  .r1-tag { background: #1a0a3a; color: #a78bfa; border-radius: 4px; padding: 1px 6px; font-size: 10px; font-weight: 600; }
  .mode-badge-ai {
    display: inline-block; background: #0d4a3a; color: #3ddc84;
    border: 1px solid #3ddc8444; border-radius: 20px; padding: 4px 16px;
    font-size: 13px; font-weight: 600; margin-bottom: 8px;
  }
  .mode-badge-rule {
    display: inline-block; background: #1a0a3a; color: #a78bfa;
    border: 1px solid #a78bfa44; border-radius: 20px; padding: 4px 16px;
    font-size: 13px; font-weight: 600; margin-bottom: 8px;
  }
  .strategy-card {
    background: #0d1117; border: 1px solid #21262d; border-left: 3px solid #7c3aed;
    border-radius: 8px; padding: 14px 16px; height: 100%;
  }
  .strategy-card .t { font-size: 15px; font-weight: 600; color: #fff; margin-bottom: 8px; }
  .strategy-card .a { font-size: 13px; color: #8b949e; line-height: 1.6; margin-bottom: 8px; }
  .strategy-card .e { font-size: 12px; color: #3ddc84; margin-bottom: 8px; }
  .strategy-tag {
    display: inline-block; background: #21262d; color: #8b949e;
    border-radius: 4px; padding: 2px 8px; font-size: 11px; margin-right: 6px;
  }
  .source-box {
    background: #0d1117; border: 1px solid #21262d; border-left: 3px solid #7c3aed;
    border-radius: 4px; padding: 8px 10px; margin-top: 4px;
    font-size: 12px; color: #8b949e; line-height: 1.5;
  }
  .report-sec h5 { color: #8b949e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
  .report-sec p { font-size: 14px; color: #c9d1d9; line-height: 1.7; margin-bottom: 12px; }
  .exec-summary {
    background: linear-gradient(135deg, #1a1f35, #0d1117); border: 1px solid #7c3aed44;
    border-radius: 8px; padding: 14px 16px; font-size: 14px; color: #a78bfa; line-height: 1.7;
  }
  .log-line { font-family: 'Courier New', monospace; font-size: 13px; color: #3ddc84; margin: 2px 0; }
  .muted { color: #8b949e; font-size: 12px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ============================================================
# 样本数据（与 Vercel 版一致）
# ============================================================
SAMPLES = {
    '📍 成都双流实验小学': """成都双流实验小学调研数据（2024年秋季）

家长访谈记录：
- 王女士（3年级家长）：设备三个月就摔坏了，屏幕碎了，维修要等两周，孩子这段时间完全没法用。售后态度还不好，说是人为损坏不保修，但我们孩子只是正常使用。
- 李先生（4年级家长）：APP每次更新后都要重新设置，孩子不会弄，我也不懂，每次都要打客服电话，等了半小时才接通。
- 张女士（2年级家长）：英语听力模块声音质量很差，发音不准，老师说跟标准发音差距很大，会影响孩子语音习惯。
- 刘先生（5年级家长）：充电线太容易断，三个月换了两根，还要自己去买，原装的买不到。

教师反馈：
- 陈老师（语文）：备课功能不好用，不能自定义题型，只能用系统内置的，很多时候满足不了教学需求。
- 王老师（数学）：班级里有8个孩子的设备这学期出现过死机问题，影响课堂进度，每次都要单独处理。
- 刘老师（英语）：内容库的英语视频太老了，有些还是五年前录制的，跟现在的教材对不上。

学生反馈：
- 多名学生反映游戏模式太难，打击积极性。
- 有学生说广告太多，做题时突然弹出广告很烦。""",

    '📍 重庆南岸农村小学': """重庆南岸农村小学调研数据（2024年）

现场走访记录：
- 校长反映：学校网络不稳定，设备经常因为断网无法使用，但设备不支持离线模式，导致课程进行到一半就中断了。这个问题已经反映半年了，厂家说在开发但一直没有上线。
- 多位家长表示：家里长辈不会用APP，孩子作业完成情况无法及时了解。家长端界面太复杂，老人完全不会操作，经常打电话给孩子家长，家长也很烦。
- 李老师反馈：山区孩子基础差，但设备内容难度调节范围太窄，最低难度对这里的孩子来说还是太难，导致很多孩子失去学习兴趣，直接玩游戏去了。
- 维修问题：距离最近的售后网点60公里，设备坏了要寄回去修，往返要两周，运费还要家长出。农村家庭觉得太麻烦，很多已经放弃使用了。
- 数据隐私：有家长反映收到了推销电话，怀疑是购买设备时留的联系方式被泄露了，表示非常不满。""",

    '📍 广州番禺民办学校': """广州番禺某民办学校调研（2025年初）

焦点小组讨论记录：
- 家长代表反映：设备每天使用时间限制不合理，孩子正在做作业突然锁屏，非常影响学习，但家长端解锁流程太复杂。
- 多位家长提出：同班同学之间作业进度互相可见，涉及孩子隐私，担心造成不必要的比较和压力。
- 教师团队反馈：系统没有与学校现有教务系统对接，老师要在两个平台分别操作，工作量翻倍，强烈要求打通系统。
- 技术老师说：设备管理后台权限设计不合理，学校没有办法批量管理设备，只能一台一台设置，全校300台设备设置花了整整三天。
- 家长王先生：孩子班上有同学破解了家长控制，自己在玩游戏，家长完全不知道，系统安全性存在漏洞。
- 付费内容问题：很多核心内容要单独收费，已经买了设备还要继续付费购买课程，家长觉得被套路了，购买前没有说清楚。""",
}

# ============================================================
# 历史记录持久化（双后端）
#   默认：本地 SQLite，数据保存在项目目录 analysis_history.db，重启不丢失
#   可选：配置 SUPABASE_URL + SUPABASE_ANON_KEY 环境变量后自动切 Supabase 云端
#     （跨重启/跨设备保留，按用户名隔离；未配置时不影响任何功能）
# ============================================================
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = (
    os.environ.get('SUPABASE_ANON_KEY')
    or os.environ.get('SUPABASE_SECRET_KEY')
    or ''
)
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_history.db')

# ============================================================
# 语义检索（可选）：嵌入向量 + 相似度搜索
#   配置 EMBEDDING_API_KEY 后启用；默认对接硅基流动 SiliconFlow 免费 bge-m3
#   （OpenAI 兼容 /embeddings 接口，也可换 OpenAI、DeepSeek 之外任意兼容服务）
#   未配置时：历史页仅提供关键词搜索，不影响任何功能
# ============================================================
EMBEDDING_API_KEY = os.environ.get('EMBEDDING_API_KEY', '')
EMBEDDING_BASE_URL = os.environ.get('EMBEDDING_BASE_URL', 'https://api.siliconflow.cn/v1').rstrip('/')
EMBEDDING_MODEL = os.environ.get('EMBEDDING_MODEL', 'BAAI/bge-m3')
USE_EMBEDDING = bool(EMBEDDING_API_KEY)


def _sb_headers() -> dict:
    """Supabase REST API 通用请求头"""
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
    }


def embed_text(text: str) -> list:
    """调用 embedding API 生成向量；未配置 Key 或调用失败时返回空列表"""
    if not USE_EMBEDDING or not (text or '').strip():
        return []
    try:
        r = requests.post(
            f'{EMBEDDING_BASE_URL}/embeddings',
            headers={'Authorization': f'Bearer {EMBEDDING_API_KEY}', 'Content-Type': 'application/json'},
            json={'model': EMBEDDING_MODEL, 'input': (text or '')[:2000]},
            timeout=30,
        )
        if not r.ok:
            print(f'[Embedding] 失败 {r.status_code}: {r.text[:200]}')
            return []
        return r.json()['data'][0]['embedding']
    except Exception as e:  # noqa: BLE001
        print(f'[Embedding] 异常: {e}')
        return []


def cosine_similarity(a: list, b: list) -> float:
    """余弦相似度（0~1），任一为空/维度不一致返回 0"""
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _build_record(username: str, input_text: str, result: dict) -> dict:
    """将单次分析结果打包为待写入的记录（含所属用户名 + 语义向量）"""
    record = {
        'username': (username or '').strip() or '访客',
        'mode': result.get('mode', 'ai'),
        'total_pain_points': result.get('extract', {}).get('totalCount', 0),
        'p0': result.get('score', {}).get('prioritySummary', {}).get('P0', 0),
        'p1': result.get('score', {}).get('prioritySummary', {}).get('P1', 0),
        'p2': result.get('score', {}).get('prioritySummary', {}).get('P2', 0),
        'top_category': get_top_category(result.get('classify', {}).get('distribution')),
        'strategy_count': len(result.get('strategy', {}).get('strategies', [])),
        'input_snippet': (input_text or '')[:120],
        'input_text': (input_text or '')[:500],
        'result_json': result,
    }
    # 语义检索向量：原文 + 类别 + 摘要 组合后嵌入，JSON 数组字符串存储
    combo = '\n'.join([
        (input_text or '')[:2000],
        f"最大问题类别：{record['top_category']}",
        record['input_snippet'],
    ])
    record['embedding'] = json.dumps(embed_text(combo), ensure_ascii=False)
    return record


def init_db() -> None:
    if USE_SUPABASE:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL DEFAULT '访客',
            created_at TEXT NOT NULL,
            mode TEXT NOT NULL,
            total_pain_points INTEGER,
            p0 INTEGER, p1 INTEGER, p2 INTEGER,
            top_category TEXT,
            strategy_count INTEGER,
            input_snippet TEXT,
            input_text TEXT,
            result_json TEXT
        )
    ''')
    # 兼容旧版本表结构：缺列时自动补列（保留已有数据）
    existing = {r[1] for r in conn.execute('PRAGMA table_info(analyses)')}
    for col, ddl in [
        ('username', "username TEXT NOT NULL DEFAULT '访客'"),
        ('input_text', 'input_text TEXT'),
        ('result_json', 'result_json TEXT'),
        ('embedding', 'embedding TEXT'),
    ]:
        if col not in existing:
            conn.execute(f'ALTER TABLE analyses ADD COLUMN {ddl}')
    conn.commit()
    conn.close()


def save_analysis(username: str, input_text: str, result: dict) -> None:
    record = _build_record(username, input_text, result)
    if USE_SUPABASE:
        try:
            r = requests.post(
                f'{SUPABASE_URL}/rest/v1/analyses',
                headers={**_sb_headers(), 'Prefer': 'return=minimal'},
                data=json.dumps(record, ensure_ascii=False),
                timeout=10,
            )
            if not r.ok:
                print(f'[Supabase] 保存失败 {r.status_code}: {r.text[:200]}')
        except Exception as e:  # noqa: BLE001
            print(f'[Supabase] 保存异常: {e}')
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'INSERT INTO analyses (username, created_at, mode, total_pain_points, p0, p1, p2, '
        'top_category, strategy_count, input_snippet, input_text, result_json, embedding) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (
            record['username'],
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            record['mode'],
            record['total_pain_points'],
            record['p0'],
            record['p1'],
            record['p2'],
            record['top_category'],
            record['strategy_count'],
            record['input_snippet'],
            record['input_text'],
            json.dumps(record['result_json'], ensure_ascii=False),
            record['embedding'],
        ),
    )
    conn.commit()
    conn.close()


def load_history(username: str = '', keyword: str = '', limit: int = 100) -> pd.DataFrame:
    columns = ['id', '用户名', '分析时间', '模式', '痛点数', 'P0', 'P1', 'P2', '最大类别', '策略数', '输入摘要']
    uname = (username or '').strip() or '访客'
    kw = (keyword or '').strip()
    if USE_SUPABASE:
        try:
            params = {
                'select': 'id,username,created_at,mode,total_pain_points,p0,p1,p2,top_category,strategy_count,input_snippet',
                'username': f'eq.{uname}',
                'order': 'created_at.desc',
                'limit': limit,
            }
            if kw:
                params['or'] = f'(input_snippet.ilike.*{kw}*,input_text.ilike.*{kw}*,top_category.ilike.*{kw}*)'
            r = requests.get(
                f'{SUPABASE_URL}/rest/v1/analyses',
                headers=_sb_headers(),
                params=params,
                timeout=10,
            )
            if r.ok:
                rows = r.json() or []
                df = pd.DataFrame(rows)
                if df.empty:
                    return pd.DataFrame(columns=columns)
                df = df.rename(columns={
                    'created_at': '分析时间', 'mode': '模式', 'total_pain_points': '痛点数',
                    'p0': 'P0', 'p1': 'P1', 'p2': 'P2', 'top_category': '最大类别',
                    'strategy_count': '策略数', 'input_snippet': '输入摘要',
                })
                df['分析时间'] = pd.to_datetime(df['分析时间']).dt.strftime('%Y-%m-%d %H:%M:%S')
                return df[columns]
            print(f'[Supabase] 读取失败 {r.status_code}: {r.text[:200]}')
        except Exception as e:  # noqa: BLE001
            print(f'[Supabase] 读取异常: {e}')
        return pd.DataFrame(columns=columns)
    conn = sqlite3.connect(DB_PATH)
    sql = (
        'SELECT id, username AS 用户名, created_at AS 分析时间, mode AS 模式, '
        'total_pain_points AS 痛点数, p0 AS P0, p1 AS P1, p2 AS P2, '
        'top_category AS 最大类别, strategy_count AS 策略数, input_snippet AS 输入摘要 '
        'FROM analyses WHERE username = ?'
    )
    params: list = [uname]
    if kw:
        sql += ' AND (input_snippet LIKE ? OR input_text LIKE ? OR top_category LIKE ?)'
        like = f'%{kw}%'
        params += [like, like, like]
    sql += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df


def clear_history(username: str = '') -> None:
    uname = (username or '').strip() or '访客'
    if USE_SUPABASE:
        try:
            r = requests.delete(
                f'{SUPABASE_URL}/rest/v1/analyses',
                headers=_sb_headers(),
                params={'username': f'eq.{uname}'},
                timeout=10,
            )
            if not r.ok:
                print(f'[Supabase] 清空失败 {r.status_code}: {r.text[:200]}')
        except Exception as e:  # noqa: BLE001
            print(f'[Supabase] 清空异常: {e}')
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM analyses WHERE username = ?', (uname,))
    conn.commit()
    conn.close()


def semantic_search(username: str = '', query: str = '', top_n: int = 10) -> pd.DataFrame:
    """语义检索：问题 → 向量 → 与本人历史记录比对相似度，返回 topN（按相似度倒序）"""
    qv = embed_text(query)
    if not qv:
        return pd.DataFrame()
    uname = (username or '').strip() or '访客'
    rows: list = []
    if USE_SUPABASE:
        try:
            r = requests.get(
                f'{SUPABASE_URL}/rest/v1/analyses',
                headers=_sb_headers(),
                params={
                    'select': 'id,username,created_at,mode,total_pain_points,p0,p1,p2,'
                              'top_category,strategy_count,input_snippet,embedding',
                    'username': f'eq.{uname}',
                    'order': 'created_at.desc',
                    'limit': 500,
                },
                timeout=15,
            )
            if r.ok:
                rows = r.json() or []
            else:
                print(f'[Supabase] 语义检索读取失败 {r.status_code}: {r.text[:200]}')
        except Exception as e:  # noqa: BLE001
            print(f'[Supabase] 语义检索读取异常: {e}')
    else:
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(
                'SELECT id, username, created_at, mode, total_pain_points, p0, p1, p2, '
                'top_category, strategy_count, input_snippet, embedding '
                'FROM analyses WHERE username = ? ORDER BY id DESC LIMIT 500', (uname,))
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()

    hits = []
    for row in rows:
        try:
            ev = json.loads(row.get('embedding') or '[]')
        except Exception:  # noqa: BLE001
            ev = []
        sim = cosine_similarity(qv, ev)
        if sim >= 0.45:  # 阈值：低于该值视为不相关
            hits.append({**row, '相似度': round(sim * 100, 1)})
    hits.sort(key=lambda x: x['相似度'], reverse=True)
    if not hits:
        return pd.DataFrame()
    df = pd.DataFrame(hits[:top_n])
    df['分析时间'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M')
    df = df.rename(columns={
        'mode': '模式', 'total_pain_points': '痛点数', 'top_category': '最大类别',
        'strategy_count': '策略数', 'input_snippet': '输入摘要',
    })
    return df[['id', '分析时间', '模式', '痛点数', '最大类别', '策略数', '输入摘要', '相似度']]


def load_detail(record_id: int) -> dict:
    """读取单条记录详情：{input_text, result}"""
    if USE_SUPABASE:
        try:
            r = requests.get(
                f'{SUPABASE_URL}/rest/v1/analyses',
                headers=_sb_headers(),
                params={'select': 'input_text,result_json', 'id': f'eq.{record_id}'},
                timeout=10,
            )
            if r.ok and r.json():
                row = r.json()[0]
                return {'input_text': row.get('input_text', ''), 'result': row.get('result_json') or {}}
            print(f'[Supabase] 详情读取失败 {r.status_code}: {r.text[:200]}')
        except Exception as e:  # noqa: BLE001
            print(f'[Supabase] 详情读取异常: {e}')
        return {}
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT input_text, result_json FROM analyses WHERE id = ?', (record_id,)).fetchone()
    conn.close()
    if not row:
        return {}
    return {'input_text': row[0] or '', 'result': json.loads(row[1] or '{}')}


init_db()

# ============================================================
# 顶栏
# ============================================================
st.markdown("""
<div class="grad-header">
  <div>
    <div class="t">🤖 学校调研多智能体分析平台</div>
    <div class="s">School Research Multi-Agent Analysis System · 六层防护 · 混合模型架构</div>
  </div>
  <div class="b">⚡ 6 Agents · V3 + R1</div>
</div>
<div class="arch-row">
  <span class="arch-item">🔀 路由员 <span class="v3-tag">V3</span></span>
  <span class="arch-item">📋 提取员 <span class="v3-tag">V3</span></span>
  <span class="arch-item">🗂️ 分类员 <span class="v3-tag">V3</span></span>
  <span class="arch-item">⚖️ 评分员 <span class="v3-tag">V3-CoT</span></span>
  <span class="arch-item">🧠 策略员 <span class="r1-tag">R1 推理</span></span>
  <span class="arch-item">📝 报告员 <span class="v3-tag">V3</span></span>
</div>
""", unsafe_allow_html=True)

# ============================================================
# 侧边栏
# ============================================================
with st.sidebar:
    st.markdown('### 👤 我的身份')
    username = st.text_input(
        '用户名（数据按人隔离）',
        value=st.session_state.get('username', ''),
        placeholder='例如：小王 / 李老师',
        help='填上自己的名字，历史记录只显示你自己的；换名字就看不到别人的数据',
    )
    st.session_state['username'] = (username or '').strip() or '访客'
    st.caption(f'当前身份：**{st.session_state["username"]}**')

    st.markdown('---')
    st.markdown('### 🔑 模型配置')
    default_key = os.environ.get('DEEPSEEK_API_KEY', '')
    api_key = st.text_input(
        'DeepSeek API Key',
        value=st.session_state.get('api_key', default_key),
        type='password',
        help='留空则自动降级到【规则模式】演示（无需 AI 也能分析）',
    )
    st.session_state['api_key'] = api_key

    st.markdown('---')
    st.markdown('### 🛡️ 六层防护体系')
    st.markdown("""
1. **降级兜底** — 无 Key/超时自动切规则引擎
2. **风险提示** — AI 结果须人工核对
3. **模式透明** — AI / 规则徽章明示
4. **人工确认** — 结果可编辑再导出
5. **来源追溯** — 每条痛点可查原文
6. **上下文工程** — 清洗/分块/裁剪
""")
    st.markdown('---')
    st.markdown('### 💾 历史记录存储')
    if USE_SUPABASE:
        host = SUPABASE_URL.replace('https://', '').replace('http://', '')
        st.markdown(f'✅ **Supabase 云端** · `{host}`')
        st.caption('跨设备保留，按用户名隔离')
    else:
        st.markdown('✅ **本地 SQLite**')
        st.caption('数据在项目目录 `analysis_history.db`，重启不丢失')
    if USE_EMBEDDING:
        st.caption(f'🧠 语义检索已启用（{EMBEDDING_MODEL}）')
    else:
        st.caption('🧠 语义检索未配置（配 `EMBEDDING_API_KEY` 后启用）')
    st.markdown('---')
    st.markdown('> 部署：`streamlit run streamlit_app.py`')
    st.markdown('> 说明：本地演示推荐留空 API Key，体验 AI → 规则自动降级；填入 Key 后使用完整 6 智能体流水线。')

# ============================================================
# 主区域
# ============================================================
tab_analyze, tab_history = st.tabs(['📊 调研分析', '🗂️ 历史记录'])


# ---------- 工具：流水线日志渲染 ----------
def render_pipeline_logs(result: dict) -> None:
    """根据 result 渲染流水线日志（含上下文工程信息）"""
    logs = [
        '🔀 路由员启动：正在检测输入数据质量...',
        '🔀 路由员完成：数据质量合格，准入主流程 ✓',
        '📋 提取员启动 (DeepSeek V3)：正在抽取痛点信息...',
        '🗂️ 分类员启动 (DeepSeek V3)：正在对痛点进行归类...',
        '⚖️ 评分员启动 (DeepSeek V3 CoT)：正在计算影响力×紧迫度...',
        '🧠 策略员启动 (DeepSeek R1 推理模型)：深度推理中...',
        '🧠 策略员思考完成：生成优化策略 ✓',
        '📝 报告员启动 (DeepSeek V3)：正在生成分析报告...',
    ]
    ctx = result.get('contextInfo') or {}
    if ctx.get('removedLines', 0) > 0:
        logs.append(f'🧹 输入清洗：移除 {ctx["removedLines"]} 行噪声/重复内容'
                    f'（{ctx.get("originalChars", 0)} → {ctx.get("cleanedChars", 0)} 字符）')
    if ctx.get('chunkCount', 1) > 1:
        logs.append(f'📦 长文本分块：拆为 {ctx["chunkCount"]} 块并行提取，去重 {ctx.get("dedupCount", 0)} 条')
    if ctx.get('trimmedCount', 0) > 0:
        logs.append(f'✂️ 上下文裁剪：策略员仅接收 top 高分痛点，裁剪 {ctx["trimmedCount"]} 条上下文')
    if not any(ctx.get(k, 0) > 0 for k in ('removedLines', 'chunkCount', 'trimmedCount')) and ctx.get('chunkCount', 1) == 1:
        logs.append('🧹 输入检查：文本干净，无需清洗/分块/裁剪')
    logs.append('✅ 分析完成！')

    if result.get('mode') == 'rule':
        logs.insert(0, '⚠️ AI 服务不可用，已自动降级到【基础规则模式】（无需 AI 也能分析）')

    for line in logs:
        st.markdown(f'<div class="log-line">[{datetime.now().strftime("%H:%M:%S")}] {line}</div>',
                    unsafe_allow_html=True)


# ---------- 工具：词云（复用原版 WordCloud2.js，浏览器渲染中文） ----------
def render_wordcloud(keywords: list) -> None:
    freq = Counter(k for k in (keywords or []) if k and len(k) >= 2)
    if not freq:
        st.markdown('<p class="muted">暂无关键词数据</p>', unsafe_allow_html=True)
        return
    word_list = [[w, c * 16 + 12] for w, c in freq.most_common(60)]
    payload = json.dumps(word_list, ensure_ascii=False).replace('</', '<\\/')
    html = f"""
    <div style="width:100%;display:flex;justify-content:center;">
      <canvas id="wc-canvas" width="520" height="280" style="max-width:100%;"></canvas>
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/wordcloud2.js/1.2.2/wordcloud2.min.js"></script>
    <script>
      const words = {payload};
      const colors = ['#7c3aed','#3b82f6','#10b981','#f59e0b','#a78bfa','#34d399','#60a5fa','#fbbf24'];
      if (typeof WordCloud !== 'undefined') {{
        WordCloud(document.getElementById('wc-canvas'), {{
          list: words, gridSize: 10, weightFactor: 1.2,
          fontFamily: 'PingFang SC, Microsoft YaHei, sans-serif',
          color: () => colors[Math.floor(Math.random() * colors.length)],
          backgroundColor: 'transparent', rotateRatio: 0.2, rotationSteps: 2,
          drawOutOfBound: false, shrinkToFit: true, minSize: 10
        }});
      }} else {{
        document.getElementById('wc-canvas').insertAdjacentHTML(
          'afterend', '<p style="color:#484f58;font-size:12px;">词云组件加载失败（CDN 不可达）</p>');
      }}
    </script>
    """
    components.html(html, height=310)


# ---------- 工具：饼图 ----------
def render_pie(distribution: dict) -> None:
    items = {k: v for k, v in (distribution or {}).items() if v > 0}
    if not items:
        st.markdown('<p class="muted">暂无分类数据</p>', unsafe_allow_html=True)
        return
    colors = ['#7c3aed', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']
    fig = go.Figure(go.Pie(
        labels=list(items.keys()),
        values=list(items.values()),
        hole=0.42,
        marker=dict(colors=colors[:len(items)]),
        textinfo='label+value',
        hovertemplate='%{label}: %{value}条 (%{percent})<extra></extra>',
    ))
    fig.update_layout(
        template='plotly_dark',
        height=330,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#c9d1d9'),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------- 工具：优先级矩阵（可编辑 → 人工确认闭环） ----------
def render_priority_matrix(result: dict) -> None:
    pain_points = result.get('extract', {}).get('painPoints', [])
    scores = result.get('score', {}).get('scores', [])
    if not scores:
        st.markdown('<p class="muted">暂无评分数据</p>', unsafe_allow_html=True)
        return

    pt_by_id = {p['id']: p for p in pain_points}
    rows = []
    for s in sorted(scores, key=lambda x: x.get('score', 0), reverse=True):
        pt = pt_by_id.get(s['id'], {})
        rows.append({
            'id': s['id'],
            '痛点描述': pt.get('text', ''),
            '影响力': s.get('impact', 1),
            '紧迫度': s.get('urgency', 1),
            '综合得分': s.get('score', 0),
            '优先级': s.get('priority', 'P2'),
            '评分理由': s.get('reasoning', ''),
        })
    df = pd.DataFrame(rows)

    st.caption('✏️ 第四层防护 · 人工确认：点击「痛点描述」可修改文字，下拉可调整影响力/紧迫度，得分与优先级自动重算')

    edited = st.data_editor(
        df,
        column_config={
            '痛点描述': st.column_config.TextColumn('痛点描述', width='large'),
            '影响力': st.column_config.SelectboxColumn('影响力', options=[1, 2, 3], required=True),
            '紧迫度': st.column_config.SelectboxColumn('紧迫度', options=[1, 2, 3], required=True),
        },
        disabled=['id', '综合得分', '优先级', '评分理由'],
        hide_index=True,
        key='priority_matrix',
    )

    if edited is not None and not edited.equals(df):
        edited = edited.copy()
        edited['综合得分'] = edited['影响力'] * edited['紧迫度']
        edited['优先级'] = edited['综合得分'].apply(lambda s: 'P0' if s >= 7 else ('P1' if s >= 4 else 'P2'))

        new_scores = []
        for r in edited.to_dict('records'):
            new_scores.append({
                'id': int(r['id']),
                'impact': int(r['影响力']),
                'urgency': int(r['紧迫度']),
                'score': int(r['综合得分']),
                'priority': r['优先级'],
                'reasoning': f"人工调整：影响力{int(r['影响力'])} × 紧迫度{int(r['紧迫度'])}",
            })
            pt = pt_by_id.get(int(r['id']))
            if pt:
                pt['text'] = r['痛点描述']

        result['score']['scores'] = new_scores
        result['score']['prioritySummary'] = {
            'P0': sum(1 for s in new_scores if s['priority'] == 'P0'),
            'P1': sum(1 for s in new_scores if s['priority'] == 'P1'),
            'P2': sum(1 for s in new_scores if s['priority'] == 'P2'),
        }
        st.session_state['result'] = result
        st.success('✅ 已保存人工修改，优先级汇总已同步更新')
        st.rerun()


# ---------- 工具：策略卡片 ----------
def render_strategies(result: dict) -> None:
    strategy = result.get('strategy', {})
    summary = strategy.get('executiveSummary', '')
    st.markdown(f'<div class="exec-summary">🧠 策略员分析摘要（DeepSeek R1 推理）<br>{summary}</div>',
                unsafe_allow_html=True)

    strategies = strategy.get('strategies', [])
    if not strategies:
        st.markdown('<p class="muted">暂无策略</p>', unsafe_allow_html=True)
        return

    cols = st.columns(min(3, len(strategies)))
    for i, s in enumerate(strategies):
        with cols[i % len(cols)]:
            prio = s.get('priority', '中')
            prio_cls = ' class="strategy-tag"' if prio != '高' else ' class="strategy-tag" style="background:#1a0a3a;color:#a78bfa;"'
            st.markdown(
                f'<div class="strategy-card">'
                f'<div class="t">{i + 1}. {s.get("title", "优化策略")}</div>'
                f'<div class="a">{s.get("action", "")}</div>'
                f'<div class="e">🎯 预期效果：{s.get("expectedResult", "")}</div>'
                f'<span{prio_cls}>优先级：{prio}</span>'
                f'<span class="strategy-tag">⏱ {s.get("timeframe", "-")}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ---------- 工具：报告 ----------
def render_report(result: dict) -> None:
    report = result.get('report') or {}
    sections = report.get('sections') or {}
    st.markdown(
        f'<div class="report-sec"><h5>📖 调研概述</h5><p>{sections.get("overview", "-")}</p></div>'
        f'<div class="report-sec"><h5>⚠️ 主要问题</h5><p>{sections.get("mainIssues", "-")}</p></div>'
        f'<div class="report-sec"><h5>✅ 优先处理建议</h5><p>{sections.get("recommendations", "-")}</p></div>'
        f'<div class="report-sec"><h5>🔚 结语</h5><p>{sections.get("conclusion", "-")}</p></div>',
        unsafe_allow_html=True,
    )


# ---------- 工具：导出 ----------
def build_export_text(result: dict) -> str:
    pain_points = result.get('extract', {}).get('painPoints', [])
    scores = result.get('score', {}).get('scores', [])
    strategies = result.get('strategy', {}).get('strategies', [])
    report = result.get('report', {}).get('sections', {})

    lines = ['# 学校调研分析报告', f'- 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
             f'- 分析模式：{"AI 增强模式" if result.get("mode") == "ai" else "规则模式"}', '']
    lines.append('## 一、核心指标')
    lines.append(f"- 提取痛点总数：{len(pain_points)}")
    lines.append(f"- P0 紧急问题：{result.get('score', {}).get('prioritySummary', {}).get('P0', 0)}")
    lines.append(f"- 最大问题类别：{get_top_category(result.get('classify', {}).get('distribution'))}")
    lines.append('')
    lines.append('## 二、痛点优先级矩阵')
    lines.append('| 优先级 | 痛点描述 | 影响力 | 紧迫度 | 综合得分 | 评分理由 |')
    lines.append('| --- | --- | --- | --- | --- | --- |')
    pt_by_id = {p['id']: p for p in pain_points}
    for s in sorted(scores, key=lambda x: x.get('score', 0), reverse=True):
        pt = pt_by_id.get(s['id'], {})
        lines.append(f"| {s.get('priority')} | {pt.get('text', '')} | {s.get('impact')} | {s.get('urgency')} | "
                     f"{s.get('score')} | {s.get('reasoning', '')} |")
    lines.append('')
    lines.append('## 三、优化策略')
    for i, s in enumerate(strategies, 1):
        lines.append(f'{i}. **{s.get("title")}**（优先级：{s.get("priority")} / {s.get("timeframe")}）')
        lines.append(f'   - 执行方案：{s.get("action")}')
        lines.append(f'   - 预期效果：{s.get("expectedResult")}')
    lines.append('')
    lines.append('## 四、报告摘要')
    for k, v in report.items():
        if v:
            lines.append(f'- {k}：{v}')
    return '\n'.join(lines)


# ---------- 主流程 ----------
with tab_analyze:
    # on_click callback：Streamlit 唯一允许在脚本中修改 widget 值的方式
    # （直接在 st.button 的 if 里赋值会触发 StreamlitAPIException）
    def _set_input_text(value: str):
        st.session_state['input_text'] = value

    def _clear_input():
        st.session_state['input_text'] = ''
        st.session_state.pop('result', None)

    input_text = st.text_area(
        '📥 输入调研数据（支持家长反馈、教师意见、学生反馈等）',
        value=st.session_state.get('input_text', ''),
        height=200,
        placeholder='粘贴学校调研原始数据…\n例如：家长王女士反映，设备经常死机，孩子上课时突然黑屏，严重影响学习。另有多位家长表示APP界面太复杂…',
        key='input_text',
    )

    sample_cols = st.columns([1, 3, 3, 3])
    sample_cols[0].markdown('<span class="muted">样本数据：</span>', unsafe_allow_html=True)
    for i, (name, sample) in enumerate(SAMPLES.items()):
        with sample_cols[i + 1]:
            st.button(
                name,
                key=f'sample_{i}',
                use_container_width=True,
                on_click=_set_input_text,
                args=(sample,),
            )

    col_btn = st.columns([1, 1])
    run_clicked = col_btn[0].button('🚀 启动多智能体分析', type='primary', use_container_width=True)
    col_btn[1].button('🔄 清空输入', use_container_width=True, on_click=_clear_input)

    if run_clicked:
        text = (input_text or '').strip()
        if not text:
            st.error('请先输入调研数据或选择样本数据！')
        elif len(text) < 20:
            st.error('输入内容太短，请提供更详细的调研数据（至少20字）')
        else:
            holder = {}

            def worker():
                try:
                    holder['result'] = analyze(text, st.session_state.get('api_key', ''))
                except Exception as e:  # noqa: BLE001
                    holder['error'] = str(e)

            thread = threading.Thread(target=worker, daemon=True)
            thread.start()

            steps = [
                (0.0, '🔀 路由员启动：正在检测输入数据质量...'),
                (2.0, '📋 提取员启动 (DeepSeek V3)：分块抽取痛点...'),
                (4.5, '🗂️ 分类员启动 (DeepSeek V3)：正在对痛点进行归类...'),
                (7.0, '⚖️ 评分员启动 (DeepSeek V3 CoT)：正在计算影响力×紧迫度...'),
                (10.0, '🧠 策略员启动 (DeepSeek R1 推理模型)：深度推理中，请稍候...'),
                (22.0, '📝 报告员启动 (DeepSeek V3)：正在生成分析报告...'),
            ]
            with st.status('🤖 智能体流水线运行中...', expanded=True) as status:
                log_box = st.empty()
                start = time.time()
                idx = 0
                for delay, msg in steps:
                    remain = delay - (time.time() - start)
                    if remain > 0:
                        time.sleep(remain)
                    if 'result' in holder or 'error' in holder:
                        break
                    log_box.markdown(f'<div class="log-line">[{datetime.now().strftime("%H:%M:%S")}] {msg}</div>',
                                     unsafe_allow_html=True)
                    idx += 1
                thread.join()

                if 'error' in holder:
                    status.update(label='❌ 分析失败', state='error')
                    st.error(f'分析失败：{holder["error"]}')
                else:
                    result = holder['result']
                    st.session_state['result'] = result
                    save_analysis(st.session_state.get('username', '访客'), text, result)
                    status.update(label='✅ 分析完成！', state='complete')
                    render_pipeline_logs(result)

    # ---------- 结果展示 ----------
    result = st.session_state.get('result')
    if result:
        st.markdown('---')
        # L3 模式透明 + L2 风险提示
        if result.get('mode') == 'rule':
            st.markdown('<span class="mode-badge-rule">📋 基础模式（规则提取）</span>', unsafe_allow_html=True)
            st.warning('⚠️ ' + result.get('fallbackReason', 'AI服务暂不可用，已自动降级到规则模式'))
            st.info('📋 当前为规则模式结果，非 AI 生成 · 建议在 AI 服务恢复后重新分析以获得更精准建议')
        else:
            st.markdown('<span class="mode-badge-ai">🤖 AI 增强模式</span>', unsafe_allow_html=True)
            st.caption('🤖 本结果由 AI 生成，关键数据请人工核对 · 每条痛点可查看原文溯源验证')

        # 指标卡片
        total_pts = len(result.get('extract', {}).get('painPoints', []))
        p0 = result.get('score', {}).get('prioritySummary', {}).get('P0', 0)
        top_cat = get_top_category(result.get('classify', {}).get('distribution'))
        strat_count = len(result.get('strategy', {}).get('strategies', []))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric('提取痛点总数', total_pts)
        m2.metric('P0 紧急问题', p0)
        m3.metric('最大问题类别', top_cat)
        m4.metric('优化策略数量', strat_count)

        # 图表
        c1, c2 = st.columns(2)
        with c1:
            st.markdown('##### 📊 痛点分类分布')
            render_pie(result.get('classify', {}).get('distribution'))
        with c2:
            st.markdown('##### ☁️ 关键词词云')
            render_wordcloud(result.get('keywords', []))

        # 优先级矩阵（可编辑）
        st.markdown('---')
        st.markdown('##### ⚖️ 痛点优先级矩阵')
        render_priority_matrix(result)

        # 策略
        st.markdown('---')
        st.markdown('##### 🧠 优化策略')
        render_strategies(result)

        # 报告
        st.markdown('---')
        st.markdown('##### 📝 调研分析报告')
        render_report(result)

        # 导出
        st.markdown('---')
        e1, e2, e3 = st.columns(3)
        with e1:
            st.download_button(
                '📄 导出 Markdown 报告',
                data=build_export_text(result),
                file_name=f'调研报告_{datetime.now().strftime("%Y%m%d_%H%M")}.md',
                mime='text/markdown',
                use_container_width=True,
            )
        with e2:
            st.download_button(
                '📦 导出完整 JSON',
                data=json.dumps(result, ensure_ascii=False, indent=2),
                file_name=f'分析结果_{datetime.now().strftime("%Y%m%d_%H%M")}.json',
                mime='application/json',
                use_container_width=True,
            )
        with e3:
            matrix_df = pd.DataFrame([
                {'痛点': p.get('text', ''), '优先级': s.get('priority', ''),
                 '影响力': s.get('impact', ''), '紧迫度': s.get('urgency', ''),
                 '得分': s.get('score', ''), '评分理由': s.get('reasoning', '')}
                for s in sorted(result.get('score', {}).get('scores', []), key=lambda x: x.get('score', 0), reverse=True)
                for p in [next((x for x in result.get('extract', {}).get('painPoints', []) if x['id'] == s['id']), {})]
            ])
            st.download_button(
                '📊 导出矩阵 CSV',
                data=matrix_df.to_csv(index=False).encode('utf-8-sig'),
                file_name=f'痛点矩阵_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
                mime='text/csv',
                use_container_width=True,
            )

# ---------- 历史记录 ----------
with tab_history:
    st.markdown('##### 🗂️ 历史分析记录')
    cur_user = st.session_state.get('username', '访客')
    backend = '☁️ Supabase' if USE_SUPABASE else '💾 本地 SQLite'
    s1, s2 = st.columns([2, 1])
    with s2:
        st.metric('当前身份', cur_user, help='历史记录只显示这个用户名下的数据')

    # —— AI 语义检索（自然语言问题 → 相关历史） ——
    with st.expander('🤖 AI 语义检索（用一句话找相关历史，如"哪些记录提到了设备死机"）',
                     expanded=USE_EMBEDDING):
        if USE_EMBEDDING:
            s_question = st.text_input('🔎 输入你的问题', key='semantic_q',
                                       placeholder='例如：哪些记录提到了设备死机 / 售后维修 / 家长隐私？')
            if st.button('🔍 开始语义检索', type='primary', key='semantic_btn'):
                q = (s_question or '').strip()
                if not q:
                    st.warning('请先输入问题')
                else:
                    st.session_state['semantic_result'] = semantic_search(username=cur_user, query=q)
            sres = st.session_state.get('semantic_result')
            if sres is not None:
                if not sres.empty:
                    st.success(f'找到 {len(sres)} 条相关记录（相似度 ≥ 45%，按相关度排序）')
                    st.dataframe(sres, use_container_width=True, hide_index=True)
                    st.caption('提示：可到下方「记录详情查看」输入对应 #编号 查看完整报告')
                else:
                    st.info('没有找到相似度足够的历史记录，试试换一种问法或放宽条件')
        else:
            st.info('AI 语义检索需要配置 Embedding Key（默认对接硅基流动免费 bge-m3 模型）。'
                    '配置方法见 README「云端部署」一节。当前可先用下方关键词搜索。')

    with s1:
        keyword = st.text_input(
            '🔍 关键词搜索我的历史记录',
            value=st.session_state.get('history_keyword', ''),
            placeholder='输入关键词，如：维修、广告、网络…',
            help='按关键字精确匹配；语义检索见上方展开区',
        )
        st.session_state['history_keyword'] = keyword

    df = load_history(username=cur_user, keyword=keyword)
    st.caption(f'持久化后端：{backend} · 当前显示 {cur_user} 的记录 · 最近 {len(df)} 条'
               + (f'（搜索「{keyword}」）' if keyword.strip() else ''))
    if df.empty:
        st.info(
            '暂无匹配记录 — 先运行一次分析会自动保存；'
            + (f'当前搜索「{keyword}」无结果，可清空搜索框试试' if keyword.strip() else '')
        )
    else:
        h1, h2, h3 = st.columns(3)
        h1.metric('分析次数', len(df))
        h2.metric('累计发现 P0 问题', int(df['P0'].sum()))
        h3.metric('平均每次痛点数', round(float(df['痛点数'].mean()), 1))
        st.dataframe(df, use_container_width=True, hide_index=True)

        # —— 可视化：问题类别分布 ——
        cat_counts = df['最大类别'].dropna().value_counts()
        if len(cat_counts) > 0:
            fig = go.Figure(go.Bar(
                x=list(cat_counts.index),
                y=list(cat_counts.values),
                marker_color='#7c3aed',
                hovertemplate='%{x}: %{y} 次<extra></extra>',
            ))
            fig.update_layout(
                template='plotly_dark', height=260,
                margin=dict(l=10, r=10, t=20, b=10),
                paper_bgcolor='rgba(0,0,0,0)', font=dict(color='#c9d1d9'),
                yaxis_title='分析次数',
            )
            st.markdown('##### 📊 问题类别分布（按当前列表）')
            st.plotly_chart(fig, use_container_width=True)

        # —— 记录详情查看 ——
        with st.expander('📄 记录详情查看', expanded=False):
            id_map = dict(zip(df['id'].astype(str), df['分析时间'].astype(str)))
            pick = st.selectbox(
                '选择一条记录（按时间倒序）',
                list(id_map.keys()),
                format_func=lambda i: f'#{i} · {id_map[i]}',
                key='detail_pick',
            )
            det = load_detail(int(pick))
            if det:
                c1, c2 = st.columns([1, 1])
                with c1:
                    st.markdown('**📥 原始输入（前500字）**')
                    st.text(det['input_text'] or '（无）')
                with c2:
                    st.markdown('**🧠 策略员摘要**')
                    st.text(det['result'].get('strategy', {}).get('executiveSummary', '（无）'))
                st.markdown('**📝 报告结论**')
                st.text(det['result'].get('report', {}).get('sections', {}).get('conclusion', '（无）'))

        if st.button(f'🗑️ 清空 {cur_user} 的历史记录', type='secondary'):
            clear_history(cur_user)
            st.session_state.pop('semantic_result', None)
            st.success(f'已清空 {cur_user} 的历史记录')
            st.rerun()
