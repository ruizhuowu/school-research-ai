# -*- coding: utf-8 -*-
"""
多智能体分析流水线（由 api/analyze.js 移植到 Python）
------------------------------------------------------------
支柱1：Prompt 工程 —— 6 个智能体独立 SYSTEM_PROMPT（角色 + 铁律）
支柱2：上下文工程 —— 输入清洗 + 长文本分块并行提取 + 上下文裁剪
支柱3：Harness 工程 —— 结构化 JSON 容错解析 + 两级降级兜底 + 输入校验

返回结构与 Vercel 版 /api/analyze 完全一致，便于前端复用。
"""
import concurrent.futures
import json
import os
import re
import time
from typing import Any, Optional

import requests

from rule_engine import rule_based_analysis

# ============================================================
# LLM 服务配置（环境变量可覆盖，默认 DeepSeek 官方）
#   硅基流动示例（一个 Key 同时做分析 + 语义检索）：
#     DEEPSEEK_API_KEY        = "sk-..."
#     DEEPSEEK_BASE_URL       = "https://api.siliconflow.cn/v1"
#     DEEPSEEK_V3_MODEL       = "deepseek-ai/DeepSeek-V3"
#     DEEPSEEK_R1_MODEL       = "deepseek-ai/DeepSeek-R1"
# ============================================================
DEEPSEEK_BASE_URL = os.environ.get('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
DEEPSEEK_V3_MODEL = os.environ.get('DEEPSEEK_V3_MODEL', 'deepseek-chat')
DEEPSEEK_R1_MODEL = os.environ.get('DEEPSEEK_R1_MODEL', 'deepseek-reasoner')

# ============================================================
# 支柱1：防幻觉 Prompt 体系
# ============================================================
SYSTEM_PROMPTS = {
    # 路由员：质量预检
    'router': (
        '你是学校调研数据的"质量检测员"。\n铁律：\n'
        '1. 只依据给定文本判断，不得揣测文本之外的意图。\n'
        '2. 文本是乱码/重复字符/与学校调研完全无关 → valid=false。\n'
        '3. 输出必须是合法JSON，不要任何多余文字。'
    ),
    # 提取员：抽取痛点
    'extractor': (
        '你是教育调研数据的"痛点提取员"。\n铁律：\n'
        '1. 只提取文本中明确表达的问题或不满，正面反馈一律忽略。\n'
        '2. keywords 必须逐字来自原文，禁止自行概括或补充原文没有的词。\n'
        '3. source 必须逐字复制原文片段，禁止改写润色。\n'
        '4. 原文中未出现的问题，绝不脑补添加。\n'
        '5. 输出必须是合法JSON，不要任何多余文字。'
    ),
    # 分类员：归类整理
    'classifier': (
        '你是教育产品痛点的"分类专家"。\n铁律：\n'
        '1. 只能使用给定的7大分类体系，禁止新增、合并或改名类别。\n'
        '2. 分类必须依据痛点描述内容，无法明确归类的痛点归入最接近的类别。\n'
        '3. 每个痛点只能归入一个类别。\n'
        '4. 输出必须是合法JSON，不要任何多余文字。'
    ),
    # 评分员：优先级打分
    'scorer': (
        '你是产品优先级的"评分专家"。\n铁律：\n'
        '1. 评分必须基于痛点文本的实际描述。\n'
        '2. 文本未提到影响人数时，影响力按保守评分（1-2分）处理，禁止臆测"大量用户"。\n'
        '3. 综合得分=影响力×紧迫度，优先级必须与得分区间严格对应。\n'
        '4. 输出必须是合法JSON，不要任何多余文字。'
    ),
    # 策略员：制定策略
    'strategist': (
        '你是K12教育智能设备的资深产品经理。\n铁律：\n'
        '1. 策略必须严格针对给定的痛点/分类/优先级数据，禁止套用与数据无关的通用话术。\n'
        '2. 每条策略都要能对应到具体的痛点关键词。\n'
        '3. 输出必须是合法JSON，不要任何多余文字。'
    ),
    # 报告员：生成报告
    'reporter': (
        '你是教育调研报告的"撰写员"。\n铁律：\n'
        '1. 报告中所有数字必须与给定的数据摘要完全一致，禁止改写。\n'
        '2. 不得引入摘要中不存在的结论。\n'
        '3. 输出必须是合法JSON，不要任何多余文字。'
    ),
}

# 7 大分类体系（供分类员 prompt 使用）
CATEGORY_SYSTEM = (
    '- 硬件品质：设备质量、耐用性、外观、充电等\n'
    '- 软件体验：APP操作、界面设计、卡顿、功能使用等\n'
    '- 内容生态：课程内容、题库质量、学科覆盖、内容更新等\n'
    '- 家长端功能：家长监控、通知推送、互动功能等\n'
    '- 教师支持：备课工具、教学辅助、教师培训等\n'
    '- 服务流程：售后服务、维修响应、客服质量等\n'
    '- 隐私权限：数据安全、权限设置、广告等'
)

# 提取员 user prompt 模板（分块提取时注入块号）
EXTRACT_PROMPT = """你是一个专业的教育调研数据提取员。以下是学校调研文本的第 {i}/{n} 块，请提取其中所有用户反馈的痛点和问题。

提取规则：
1. 只提取明确表达的问题或不满，正面反馈一律忽略
2. keywords 必须逐字来自原文，禁止自行概括
3. source 必须逐字复制原文片段，禁止改写润色
4. 原文中未出现的问题，绝不脑补添加
5. 每条痛点单独列出，最多提取10条

文本内容：
{chunk}

请只返回如下JSON，不要有其他内容：
{{
  "painPoints": [
    {{"id": 1, "text": "痛点描述", "keywords": ["关键词1", "关键词2"], "source": "原文片段"}}
  ],
  "totalCount": 数字,
  "summary": "一句话总结"
}}"""


# ============================================================
# LLM 调用层（DeepSeek）
# ============================================================
def call_v3(api_key: str, system_prompt: Optional[str], user_prompt: str) -> str:
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': user_prompt})
    resp = requests.post(
        f'{DEEPSEEK_BASE_URL}/chat/completions',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        json={
            'model': DEEPSEEK_V3_MODEL,
            'messages': messages,
            'response_format': {'type': 'json_object'},
            'temperature': 0.3,
            'max_tokens': 2000,
        },
        timeout=120,
    )
    data = resp.json()
    if 'choices' not in data or not data['choices']:
        raise RuntimeError(f'DeepSeek V3 API返回异常: {json.dumps(data, ensure_ascii=False)}')
    return data['choices'][0]['message']['content']


def call_r1(api_key: str, system_prompt: Optional[str], user_prompt: str) -> str:
    messages = []
    if system_prompt:
        messages.append({'role': 'system', 'content': system_prompt})
    messages.append({'role': 'user', 'content': user_prompt})
    resp = requests.post(
        f'{DEEPSEEK_BASE_URL}/chat/completions',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
        json={
            'model': DEEPSEEK_R1_MODEL,
            'messages': messages,
            'temperature': 1,
            'max_tokens': 4000,
        },
        timeout=180,
    )
    data = resp.json()
    if 'choices' not in data or not data['choices']:
        raise RuntimeError(f'DeepSeek R1 API返回异常: {json.dumps(data, ensure_ascii=False)}')
    return data['choices'][0]['message']['content']


# ============================================================
# 结构化输出容错解析（支柱3）
# ============================================================
def safe_parse_json(text: Any, fallback: Any) -> Any:
    """三级容错：直接 parse → 正则提取 → 兜底默认值"""
    if not text:
        return fallback
    if isinstance(text, (dict, list)):
        return text
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return fallback


def extract_json_from_r1(text: Any, fallback: Any) -> Any:
    """R1 响应可能含思考过程，从后往前找最后一个合法 JSON"""
    if isinstance(text, (dict, list)):
        return text
    if not text:
        return fallback
    matches = re.findall(r'\{[\s\S]*\}', text)
    for m in reversed(matches):
        try:
            return json.loads(m)
        except Exception:
            continue
    return fallback


# ============================================================
# 支柱2：上下文工程 工具函数
# ============================================================
def clean_input_text(text: str) -> tuple[str, int]:
    """输入清洗：去空白行/重复行/无有效文字的行（纯标点/纯数字噪声）"""
    lines = [l.strip() for l in re.split(r'\r?\n', text) if l.strip()]
    seen: set[str] = set()
    cleaned: list[str] = []
    for line in lines:
        key = re.sub(r'\s+', '', line)
        if key in seen:
            continue
        seen.add(key)
        # [^\W\d_] 表示中英文字母类字符（\w 匹配 Unicode 字母），纯数字行也过滤
        if len(key) >= 2 and re.search(r'[^\W\d_]', key) and not re.match(r'^\d+$', key):
            cleaned.append(line)
    return '\n'.join(cleaned), len(lines) - len(cleaned)


def chunk_text(text: str, max_chars_per_chunk: int = 1800, max_chunks: int = 3) -> list[str]:
    """长文本分块：按句切分，每块限制字符数；超长单句按字符硬切"""
    if len(text) <= max_chars_per_chunk:
        return [text]
    sentences = [s.strip() for s in re.split(r'[\n\r]+|[。！？!?；;]', text) if s.strip()]
    if not sentences:
        return []
    chunks: list[str] = []
    cur = ''
    for s in sentences:
        seg = s
        while len(seg) > max_chars_per_chunk:
            if cur:
                chunks.append(cur)
                cur = ''
            if len(chunks) >= max_chunks:
                return chunks
            chunks.append(seg[:max_chars_per_chunk])
            seg = seg[max_chars_per_chunk:]
        if cur and len(cur + seg) > max_chars_per_chunk:
            chunks.append(cur)
            cur = seg
            if len(chunks) >= max_chunks:
                break
        else:
            cur = (cur + '。' + seg) if cur else seg
    if cur and len(chunks) < max_chunks:
        chunks.append(cur)
    return chunks


def extract_pain_points(api_key: str, text: str) -> dict[str, Any]:
    """分块提取 + 合并去重：并行调用提取员，按 source 原文去重后重排 id"""
    cleaned = clean_input_text(text)[0]
    chunks = chunk_text(cleaned)

    def _call(i: int, chunk: str) -> Any:
        raw = call_v3(api_key, SYSTEM_PROMPTS['extractor'],
                      EXTRACT_PROMPT.format(i=i + 1, n=len(chunks), chunk=chunk))
        return safe_parse_json(raw, {'painPoints': [], 'totalCount': 0, 'summary': ''})

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(chunks))) as pool:
        chunk_results = list(pool.map(lambda x: _call(*x), enumerate(chunks)))

    raw_count = 0
    merged: list[dict] = []
    seen_source: set[str] = set()
    for d in chunk_results:
        for p in (d.get('painPoints') or []):
            raw_count += 1
            key = str(p.get('source') or p.get('text') or '').strip()
            if key and key not in seen_source:
                seen_source.add(key)
                merged.append(p)

    # 重新编号，保证后续节点 id 连续
    pain_points = [{**p, 'id': i + 1} for i, p in enumerate(merged)]
    return {
        'painPoints': pain_points,
        'totalCount': len(pain_points),
        'summary': (f'分块提取（{len(chunks)}块）合并去重后共 {len(pain_points)} 条痛点'
                    if len(chunks) > 1 else f'提取到 {len(pain_points)} 条痛点'),
        'chunkCount': len(chunks),
        'dedupCount': max(0, raw_count - len(pain_points)),
    }


def trim_pain_points_for_strategy(pain_points: list[dict], scores: list[dict],
                                  top_n: int = 5) -> dict[str, Any]:
    """上下文裁剪：策略员只消费 top-N 高分痛点，其余仅保留聚合统计"""
    score_by_id = {s['id']: s for s in (scores or [])}
    scored = [
        {**p, 'score': score_by_id.get(p['id'], {}).get('score', 0),
         'priority': score_by_id.get(p['id'], {}).get('priority', 'P2')}
        for p in (pain_points or [])
    ]
    scored.sort(key=lambda x: x.get('score', 0), reverse=True)
    top = scored[:top_n]
    rest = scored[top_n:]
    rest_priority = {'P0': 0, 'P1': 0, 'P2': 0}
    for p in rest:
        rest_priority[p.get('priority', 'P2')] += 1
    return {'topPainPoints': top, 'restCount': len(rest), 'restPrioritySummary': rest_priority}


def get_top_pain_examples(pain_points: list[dict], scores: list[dict], n: int = 2) -> str:
    """取得分最高的 n 条痛点原文片段（供报告员引用）"""
    sorted_scores = sorted((scores or []), key=lambda x: x.get('score', 0), reverse=True)
    by_id = {p['id']: p for p in (pain_points or [])}
    texts = [by_id.get(s['id'], {}).get('text', '')[:40] for s in sorted_scores[:n]]
    texts = [t for t in texts if t]
    return '；'.join(texts) or '暂无'


def get_top_category(distribution: Optional[dict]) -> str:
    if not distribution:
        return '未知'
    return max(distribution, key=distribution.get)


# ============================================================
# 主分析入口
# ============================================================
def analyze(text: str, api_key: str) -> dict[str, Any]:
    """输入校验 → 清洗 → 6 智能体流水线 → 返回与 Vercel 版一致的结果结构"""
    if not text or len(text.strip()) < 20:
        raise ValueError('输入内容太短，请提供更详细的调研数据（至少20字）')

    # 支柱2：输入清洗
    cleaned, removed_lines = clean_input_text(text)
    if len(cleaned.strip()) < 20:
        raise ValueError('清洗后有效内容不足，请提供更详细的调研数据（至少20字）')

    def _ctx_info(chunk_count=1, dedup_count=0, trimmed_count=0, note=''):
        return {
            'originalChars': len(text),
            'cleanedChars': len(cleaned),
            'removedLines': removed_lines,
            'chunkCount': chunk_count,
            'dedupCount': dedup_count,
            'trimmedCount': trimmed_count,
            'note': note,
        }

    # ========== 第一层防护：降级兜底 ==========
    if not api_key or not api_key.strip():
        result = rule_based_analysis(cleaned)
        return {
            'success': True, 'mode': 'rule',
            'fallbackReason': 'DEEPSEEK_API_KEY 未配置，已自动降级到基础规则模式',
            **result,
            'contextInfo': _ctx_info(note='规则模式'),
            'timestamp': _now(),
        }

    try:
        # ---------- 路由员：质量预检 ----------
        router_raw = call_v3(api_key, SYSTEM_PROMPTS['router'], (
            '你是一个输入质量检测员。判断以下文本是否是有效的学校调研反馈数据。\n'
            '有效数据应包含：学生/家长/老师的反馈意见、对产品的评价或问题描述。\n\n'
            f'文本内容（已清洗）：\n{cleaned}\n\n'
            '请只返回如下JSON，不要有其他内容：\n'
            '{"valid": true或false, "reason": "简短说明", "quality": "high或medium或low"}'
        ))
        router_data = safe_parse_json(router_raw, {'valid': True, 'quality': 'medium', 'reason': '默认通过'})
        if not router_data.get('valid', True):
            raise ValueError(f"输入内容不符合要求：{router_data.get('reason', '未知原因')}")

        # ---------- 提取员：抽取痛点（分块并行） ----------
        extract_data = extract_pain_points(api_key, cleaned)

        # ---------- 分类员：归类整理 ----------
        classify_raw = call_v3(api_key, SYSTEM_PROMPTS['classifier'], (
            '你是一个教育产品痛点分类专家。将以下痛点按照7大类别进行分类。\n\n'
            '分类体系：\n'
            f'{CATEGORY_SYSTEM}\n\n'
            '痛点列表：\n'
            f'{json.dumps(extract_data["painPoints"], ensure_ascii=False)}\n\n'
            '请只返回如下JSON，不要有其他内容：\n'
            '{\n'
            '  "categories": {\n'
            '    "硬件品质": [痛点id数组],\n'
            '    "软件体验": [痛点id数组],\n'
            '    "内容生态": [痛点id数组],\n'
            '    "家长端功能": [痛点id数组],\n'
            '    "教师支持": [痛点id数组],\n'
            '    "服务流程": [痛点id数组],\n'
            '    "隐私权限": [痛点id数组]\n'
            '  },\n'
            '  "distribution": {"类别名": 数量}\n'
            '}'
        ))
        classify_data = safe_parse_json(classify_raw, {'categories': {}, 'distribution': {}})

        # ---------- 评分员：优先级打分（CoT） ----------
        score_raw = call_v3(api_key, SYSTEM_PROMPTS['scorer'], (
            '你是一个资深产品优先级评估专家。请对每个痛点进行影响力×紧迫度打分。\n\n'
            '评分维度：\n'
            '- 影响力（1-3分）：1=影响少数用户, 2=影响较多用户, 3=影响大多数用户\n'
            '- 紧迫度（1-3分）：1=可延后处理, 2=近期需处理, 3=必须立即处理\n'
            '- 综合得分 = 影响力 × 紧迫度（范围1-9分）\n'
            '- 优先级：7-9分→P0紧急, 4-6分→P1重要, 1-3分→P2普通\n\n'
            '请逐条认真分析每个痛点的实际影响范围和处理紧迫程度，给出合理评分。\n\n'
            '痛点列表：\n'
            f'{json.dumps(extract_data["painPoints"], ensure_ascii=False)}\n\n'
            '请只返回如下JSON，不要有其他内容：\n'
            '{\n'
            '  "scores": [\n'
            '    {"id": 痛点id, "impact": 影响力分数, "urgency": 紧迫度分数, "score": 综合得分, "priority": "P0或P1或P2", "reasoning": "15字以内的评分理由"}\n'
            '  ],\n'
            '  "prioritySummary": {"P0": 数量, "P1": 数量, "P2": 数量}\n'
            '}'
        ))
        score_data = safe_parse_json(score_raw, {'scores': [], 'prioritySummary': {'P0': 0, 'P1': 0, 'P2': 0}})

        # ---------- 策略员：制定策略（上下文裁剪，R1 推理） ----------
        strategy_ctx = trim_pain_points_for_strategy(extract_data['painPoints'], score_data.get('scores', []), 5)
        strategy_raw = call_r1(api_key, SYSTEM_PROMPTS['strategist'], (
            '你是一个资深K12教育智能设备产品经理。请基于以下调研分析数据，制定3-5条核心产品优化策略。\n\n'
            f'调研痛点数据（已按综合得分降序，仅展示最高优先级的{len(strategy_ctx["topPainPoints"])}条）：\n'
            f'{json.dumps(strategy_ctx["topPainPoints"], ensure_ascii=False)}\n\n'
            f'其余 {strategy_ctx["restCount"]} 条痛点未逐一展开，优先级分布：'
            f'{json.dumps(strategy_ctx["restPrioritySummary"], ensure_ascii=False)}（策略应优先聚焦上方高分痛点）\n\n'
            '分类分布：\n'
            f'{json.dumps(classify_data.get("distribution", {}), ensure_ascii=False)}\n\n'
            '优先级分布：\n'
            f'{json.dumps(score_data.get("prioritySummary", {}), ensure_ascii=False)}\n\n'
            '请深度思考后，返回如下JSON，不要有其他内容：\n'
            '{\n'
            '  "strategies": [\n'
            '    {"title": "策略标题（10字以内）", "targetPainPoints": ["针对的痛点关键词"], '
            '"action": "具体执行方案（50字以内）", "expectedResult": "预期效果（30字以内）", '
            '"priority": "高或中或低", "timeframe": "1个月内或1-3个月或3-6个月"}\n'
            '  ],\n'
            '  "executiveSummary": "给管理层的总结（100字以内）"\n'
            '}'
        ))
        strategy_data = extract_json_from_r1(strategy_raw, {'strategies': [], 'executiveSummary': '策略生成完成'})

        # ---------- 报告员：生成报告 ----------
        report_raw = call_v3(api_key, SYSTEM_PROMPTS['reporter'], (
            '你是一个专业的教育调研报告撰写员。根据以下分析结果，生成一份简洁专业的调研报告摘要。\n\n'
            '数据摘要：\n'
            f'- 共提取痛点：{extract_data["totalCount"] or len(extract_data.get("painPoints", []))}条\n'
            f'- 分类分布：{json.dumps(classify_data.get("distribution", {}), ensure_ascii=False)}\n'
            f'- 优先级分布：{json.dumps(score_data.get("prioritySummary", {}), ensure_ascii=False)}\n'
            f'- 最大问题类别：{get_top_category(classify_data.get("distribution"))}\n'
            f'- 核心策略数量：{len(strategy_data.get("strategies", []))}条\n'
            f'- 主要痛点举例：{get_top_pain_examples(extract_data.get("painPoints", []), score_data.get("scores", []), 2)}\n\n'
            '请只返回如下JSON，不要有其他内容：\n'
            '{\n'
            '  "reportTitle": "报告标题",\n'
            '  "sections": {\n'
            '    "overview": "调研概述（60字以内）",\n'
            '    "mainIssues": "主要问题描述（80字以内）",\n'
            '    "recommendations": "优先处理建议（80字以内）",\n'
            '    "conclusion": "结语（40字以内）"\n'
            '  },\n'
            '  "keyMetrics": {"totalPainPoints": 数字, "p0Count": 数字, "topCategory": "最多问题的类别", "actionRequired": 数字}\n'
            '}'
        ))
        report_data = safe_parse_json(report_raw, {
            'reportTitle': '学校调研分析报告',
            'sections': {'overview': '分析完成', 'mainIssues': '', 'recommendations': '', 'conclusion': ''},
            'keyMetrics': {},
        })

        # 整合关键词（词云）
        all_keywords = []
        for p in extract_data.get('painPoints', []):
            all_keywords.extend(p.get('keywords') or [])

        return {
            'success': True,
            'mode': 'ai',
            'routerCheck': router_data,
            'extract': extract_data,
            'classify': classify_data,
            'score': score_data,
            'strategy': strategy_data,
            'report': report_data,
            'keywords': all_keywords,
            'contextInfo': _ctx_info(
                chunk_count=extract_data.get('chunkCount', 1),
                dedup_count=extract_data.get('dedupCount', 0),
                trimmed_count=max(0, len(extract_data.get('painPoints', [])) - len(strategy_ctx['topPainPoints'])),
            ),
            'timestamp': _now(),
        }

    except Exception as e:  # noqa: BLE001 —— AI 任一步失败自动降级
        # ========== 第一层防护：降级兜底 ==========
        try:
            fallback = rule_based_analysis(cleaned)
            return {
                'success': True,
                'mode': 'rule',
                'fallbackReason': f'AI服务暂不可用，已自动降级到基础规则模式：{e}',
                **fallback,
                'contextInfo': _ctx_info(note='规则模式'),
                'timestamp': _now(),
            }
        except Exception as fallback_error:  # noqa: BLE001
            raise RuntimeError(f'分析过程出错：{e}；规则模式也失败：{fallback_error}') from e


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime())
