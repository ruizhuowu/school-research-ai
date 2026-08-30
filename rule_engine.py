# -*- coding: utf-8 -*-
"""
规则模式引擎（第一层防护：降级兜底）
------------------------------------------------------------
作用：当 DeepSeek API 不可用（无 Key/超时/报错）时，
      自动降级到纯规则分析，保证产品"永远可用"。
原理：关键词匹配 + 规则分类 + 规则评分 + 模板策略，
      不依赖任何外部 AI 接口。
输出：与 AI 模式完全相同的 JSON 结构，前端无需改动。
（由 api/ruleEngine.js 移植，保持结构与行为一致）
"""
import re
from typing import Any

# ---- 负面词表：用于提取痛点（覆盖硬件/软件/内容/服务等场景）----
NEGATIVE_WORDS = [
    '死机', '黑屏', '卡顿', '卡', '太慢', '慢', '坏', '摔', '碎', '断', '难',
    '太难', '烦', '复杂', '看不懂', '广告', '泄露', '不能', '无法', '不保修',
    '太贵', '收费', '不满意', '难用', '缺失', '落后', '不对', '差', '不稳定',
    '容易断', '不匹配', '不合理', '漏洞', '破解', '套路', '推卸', '麻烦',
    '耽误', '影响', '不兼容', '延迟', '滞后', '错误', '出错', '故障', '太旧',
    '不人性化', '不合理'
]

# ---- 影响范围词：提升"影响力"评分 ----
IMPACT_WORDS = [
    '多个', '多位', '大量', '全班', '全校', '很多', '纷纷', '都', '每个',
    '普遍', '大部分', '众多', '所有'
]

# ---- 紧迫词：提升"紧迫度"评分 ----
URGENCY_WORDS = [
    '严重影响', '立即', '紧急', '必须', '一直', '已经', '半年', '反复',
    '多次', '至今', '还没', '强烈', '非常', '根本', '完全', '直接', '无法',
    '不能', '非常不满'
]

# ---- 7大类别关键词规则（对应公司分类标准）----
CATEGORY_RULES = {
    '硬件品质': ['死机', '黑屏', '屏幕', '充电', '电池', '摔', '碎', '断', '质量', '硬件', '设备', '坏了', '配件', '线', '外壳'],
    '软件体验': ['APP', '界面', '操作', '卡顿', '卡', '复杂', '看不懂', '设置', '更新', '软件', '功能', '系统', '解锁', '锁屏', '版本', '广告'],
    '内容生态': ['内容', '课程', '题库', '视频', '教材', '听力', '发音', '题目', '资源', '太旧', '付费', '收费', '内容库', '难度', '游戏', '作业批改', '备课'],
    '家长端功能': ['家长', '监控', '通知', '控制', '作业', '隐私', '比较', '进度', '解锁'],
    '教师支持': ['教学', '教务', '后台', '班级', '老师', '管理', '备课', '批量'],
    '服务流程': ['售后', '维修', '客服', '保修', '服务', '响应', '网点', '电话', '两周', '往返', '运费', '等待'],
    '隐私权限': ['隐私', '泄露', '数据', '安全', '推销', '破解', '漏洞', '电话']
}

# ---- 类别 → 通用策略模板（对应策略员输出，保证降级模式也有策略）----
STRATEGY_TEMPLATES = {
    '硬件品质': {
        'title': '强化硬件品控与售后保障',
        'action': '建立快速维修通道，延长保修期，提升设备耐用性测试标准，增加备件供应。',
        'expectedResult': '降低硬件故障率，提升用户满意度',
        'priority': '高', 'timeframe': '1个月内'
    },
    '软件体验': {
        'title': '简化交互与降低使用门槛',
        'action': '重构主要操作流程，提供长辈模式与新手引导，减少操作层级与弹窗广告。',
        'expectedResult': '降低学习成本，减少操作抱怨',
        'priority': '高', 'timeframe': '1-3个月'
    },
    '内容生态': {
        'title': '更新内容库与优化难度梯度',
        'action': '引入新版教材内容，扩大难度调节范围，清理过时资源，明确收费说明。',
        'expectedResult': '内容贴合教学，学习兴趣提升',
        'priority': '中', 'timeframe': '1-3个月'
    },
    '家长端功能': {
        'title': '优化家长端体验与隐私保护',
        'action': '简化家长端操作，增加隐私开关与进度可见范围设置，简化解锁流程。',
        'expectedResult': '家长使用顺畅，隐私争议减少',
        'priority': '中', 'timeframe': '1-3个月'
    },
    '教师支持': {
        'title': '打通教学系统与备课能力',
        'action': '对接学校教务系统，开放自定义题型与批量设备管理，减少重复操作。',
        'expectedResult': '教师效率提升，管理成本下降',
        'priority': '中', 'timeframe': '3-6个月'
    },
    '服务流程': {
        'title': '建立响应迅速的售后体系',
        'action': '缩短维修周期，增设本地服务网点与24小时响应机制，明确保修政策。',
        'expectedResult': '售后体验改善，用户流失率下降',
        'priority': '高', 'timeframe': '1个月内'
    },
    '隐私权限': {
        'title': '强化数据安全与权限管理',
        'action': '加密存储用户数据，审计第三方合作，强化家长控制权限防破解能力。',
        'expectedResult': '数据安全提升，用户信任度增强',
        'priority': '高', 'timeframe': '1个月内'
    }
}

# ---- 通用兜底策略（任何情况下都会补充一条）----
FALLBACK_STRATEGY = {
    'title': '建立持续调研反馈机制',
    'targetPainPoints': [],
    'action': '定期收集用户反馈并跟踪问题解决进度，形成"发现问题-解决问题-验证效果"闭环。',
    'expectedResult': '问题响应速度提升，产品迭代方向清晰',
    'priority': '中', 'timeframe': '1-3个月'
}


def _get_top_category(distribution: dict) -> str:
    """返回数量最多的类别名"""
    if not distribution:
        return '未知'
    top, mx = '', 0
    for cat, count in distribution.items():
        if count > mx:
            mx, top = count, cat
    return top or '未知'


def rule_based_analysis(text: str) -> dict[str, Any]:
    """规则模式分析主入口，返回与 AI 模式一致的分析结果结构"""
    # ---------- 1) 文本切分：按换行/标点切句，过滤过短片段 ----------
    raw_lines = [s.strip() for s in re.split(r"[\n\r]+", text) if len(s.strip()) > 4]
    sentences: list[str] = []
    for line in raw_lines:
        parts = [s.strip() for s in re.split(r"[。；;！!？?\n]", line) if len(s.strip()) > 4]
        sentences.extend(parts)

    # ---------- 2) 提取痛点：命中负面词的句子 ----------
    pain_points: list[dict] = []
    seen: set[str] = set()
    pid = 1
    for sentence in sentences:
        hit_words = [w for w in NEGATIVE_WORDS if w in sentence]
        if hit_words and sentence not in seen:
            seen.add(sentence)
            pain_points.append({
                'id': pid,
                'text': sentence[:90] + '…' if len(sentence) > 90 else sentence,
                'keywords': hit_words[:4],
                'source': sentence
            })
            pid += 1

    # ---------- 3) 分类：按类别关键词加权匹配 ----------
    categories: dict[str, list[int]] = {c: [] for c in CATEGORY_RULES}
    for p in pain_points:
        best_cat, best_score = None, 0
        for cat, words in CATEGORY_RULES.items():
            score = sum(1 for w in words if w in p['text'])
            if score > best_score:
                best_score, best_cat = score, cat
        if best_cat:
            categories[best_cat].append(p['id'])
    distribution = {k: len(v) for k, v in categories.items()}

    # ---------- 4) 评分：影响力×紧迫度（与 AI 模式同一套矩阵）----------
    scores = []
    for p in pain_points:
        impact = 1
        if any(w in p['text'] for w in IMPACT_WORDS):
            impact += 1
        if len(p['keywords']) >= 2:
            impact += 1
        impact = min(impact, 3)

        urgency = 1
        if any(w in p['text'] for w in URGENCY_WORDS):
            urgency += 1
        if any(k in p['keywords'] for k in ['死机', '黑屏', '无法', '不能', '泄露', '破解', '严重影响']):
            urgency += 1
        urgency = min(urgency, 3)

        score = impact * urgency
        priority = 'P0' if score >= 7 else ('P1' if score >= 4 else 'P2')
        scores.append({
            'id': p['id'], 'impact': impact, 'urgency': urgency, 'score': score,
            'priority': priority, 'reasoning': '规则匹配：' + '/'.join(p['keywords'])
        })
    priority_summary = {
        'P0': sum(1 for s in scores if s['priority'] == 'P0'),
        'P1': sum(1 for s in scores if s['priority'] == 'P1'),
        'P2': sum(1 for s in scores if s['priority'] == 'P2'),
    }

    # ---------- 5) 策略：按最大问题类别生成模板策略 ----------
    top_cat = _get_top_category(distribution)
    strategies = []
    if top_cat and top_cat in STRATEGY_TEMPLATES:
        t = STRATEGY_TEMPLATES[top_cat]
        strategies.append({
            'title': t['title'],
            'targetPainPoints': CATEGORY_RULES[top_cat][:3],
            'action': t['action'],
            'expectedResult': t['expectedResult'],
            'priority': t['priority'],
            'timeframe': t['timeframe']
        })
    strategies.append(FALLBACK_STRATEGY)
    executive_summary = (
        f"共提取痛点{len(pain_points)}条，主要集中在「{top_cat}」（{distribution.get(top_cat, 0)}条）。"
        f"当前识别P0紧急问题{priority_summary['P0']}条，建议优先处理。"
    )

    # ---------- 6) 报告：模板化输出（与 AI 模式同结构）----------
    top_pain_texts = '；'.join(p['text'][:30] for p in pain_points[:3])
    report = {
        'reportTitle': '调研分析报告（规则模式）',
        'sections': {
            'overview': f"本次分析基于{len(sentences)}条反馈片段，共提取{len(pain_points)}条用户痛点。",
            'mainIssues': f"主要问题集中在「{top_cat}」，包括：{top_pain_texts}。",
            'recommendations': f"建议优先解决「{top_cat}」相关问题，P0级痛点共{priority_summary['P0']}条需立即处理。",
            'conclusion': 'AI服务暂不可用，以上为规则模式基础分析结果，建议AI服务恢复后重新分析以获取更精准建议。'
        },
        'keyMetrics': {
            'totalPainPoints': len(pain_points),
            'p0Count': priority_summary['P0'],
            'topCategory': top_cat,
            'actionRequired': priority_summary['P0']
        }
    }

    # ---------- 7) 关键词聚合（供词云使用）----------
    keywords = []
    for p in pain_points:
        keywords.extend(p['keywords'])

    return {
        'routerCheck': {'valid': len(pain_points) > 0, 'quality': 'medium', 'reason': '规则模式预检通过'},
        'extract': {'painPoints': pain_points, 'totalCount': len(pain_points),
                    'summary': f"规则模式提取{len(pain_points)}条痛点"},
        'classify': {'categories': categories, 'distribution': distribution},
        'score': {'scores': scores, 'prioritySummary': priority_summary},
        'strategy': {'strategies': strategies, 'executiveSummary': executive_summary},
        'report': report,
        'keywords': keywords
    }
