export default async function handler(req, res) {
  // 允许跨域
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: '仅支持POST请求' });

  const { text } = req.body;
  if (!text || text.trim().length < 20) {
    return res.status(400).json({ error: '输入内容太短，请提供更详细的调研数据（至少20字）' });
  }

  const API_KEY = process.env.DEEPSEEK_API_KEY;
  if (!API_KEY) {
    return res.status(500).json({ error: 'API Key未配置，请在Vercel环境变量中设置DEEPSEEK_API_KEY' });
  }

  try {
    // ========== 路由员：质量预检 (DeepSeek V3) ==========
    const routerRaw = await callV3(API_KEY, `
你是一个输入质量检测员。判断以下文本是否是有效的学校调研反馈数据。
有效数据应包含：学生/家长/老师的反馈意见、对产品的评价或问题描述。

文本内容：
${text}

请只返回如下JSON，不要有其他内容：
{"valid": true或false, "reason": "简短说明", "quality": "high或medium或low"}
    `);
    let routerData = safeParseJSON(routerRaw, { valid: true, quality: 'medium', reason: '默认通过' });
    if (!routerData.valid) {
      return res.status(400).json({ error: '输入内容不符合要求', reason: routerData.reason });
    }

    // ========== 提取员：抽取痛点 (DeepSeek V3) ==========
    const extractRaw = await callV3(API_KEY, `
你是一个专业的教育调研数据提取员。从以下学校调研文本中提取所有用户反馈的痛点和问题。

提取规则：
1. 只提取明确表达的问题或不满
2. 保留原话中的关键词
3. 忽略正面反馈和无关内容
4. 每条痛点单独列出，最多提取15条

文本内容：
${text}

请只返回如下JSON，不要有其他内容：
{
  "painPoints": [
    {"id": 1, "text": "痛点描述", "keywords": ["关键词1", "关键词2"], "source": "原文片段"}
  ],
  "totalCount": 数字,
  "summary": "一句话总结"
}
    `);
    let extractData = safeParseJSON(extractRaw, { painPoints: [], totalCount: 0, summary: '提取完成' });

    // ========== 分类员：归类整理 (DeepSeek V3) ==========
    const classifyRaw = await callV3(API_KEY, `
你是一个教育产品痛点分类专家。将以下痛点按照7大类别进行分类。

分类体系：
- 硬件品质：设备质量、耐用性、外观、充电等
- 软件体验：APP操作、界面设计、卡顿、功能使用等
- 内容生态：课程内容、题库质量、学科覆盖、内容更新等
- 家长端功能：家长监控、通知推送、互动功能等
- 教师支持：备课工具、教学辅助、教师培训等
- 服务流程：售后服务、维修响应、客服质量等
- 隐私权限：数据安全、权限设置、广告等

痛点列表：
${JSON.stringify(extractData.painPoints)}

请只返回如下JSON，不要有其他内容：
{
  "categories": {
    "硬件品质": [痛点id数组],
    "软件体验": [痛点id数组],
    "内容生态": [痛点id数组],
    "家长端功能": [痛点id数组],
    "教师支持": [痛点id数组],
    "服务流程": [痛点id数组],
    "隐私权限": [痛点id数组]
  },
  "distribution": {"类别名": 数量}
}
    `);
    let classifyData = safeParseJSON(classifyRaw, { categories: {}, distribution: {} });

    // ========== 评分员：优先级打分 (DeepSeek V3 with CoT prompt) ==========
    const scoreRaw = await callV3(API_KEY, `
你是一个资深产品优先级评估专家。请对每个痛点进行影响力×紧迫度打分。

评分维度：
- 影响力（1-3分）：1=影响少数用户, 2=影响较多用户, 3=影响大多数用户
- 紧迫度（1-3分）：1=可延后处理, 2=近期需处理, 3=必须立即处理
- 综合得分 = 影响力 × 紧迫度（范围1-9分）
- 优先级：7-9分→P0紧急, 4-6分→P1重要, 1-3分→P2普通

请逐条认真分析每个痛点的实际影响范围和处理紧迫程度，给出合理评分。

痛点列表：
${JSON.stringify(extractData.painPoints)}

请只返回如下JSON，不要有其他内容：
{
  "scores": [
    {
      "id": 痛点id,
      "impact": 影响力分数,
      "urgency": 紧迫度分数,
      "score": 综合得分,
      "priority": "P0或P1或P2",
      "reasoning": "15字以内的评分理由"
    }
  ],
  "prioritySummary": {"P0": 数量, "P1": 数量, "P2": 数量}
}
    `);
    let scoreData = safeParseJSON(scoreRaw, { scores: [], prioritySummary: { P0: 0, P1: 0, P2: 0 } });

    // ========== 策略员：制定策略 (DeepSeek R1 推理模型) ==========
    const strategyRaw = await callR1(API_KEY, `
你是一个资深K12教育智能设备产品经理。请基于以下调研分析数据，制定3-5条核心产品优化策略。

调研痛点数据：
${JSON.stringify(extractData.painPoints)}

分类分布：
${JSON.stringify(classifyData.distribution)}

优先级分布：
${JSON.stringify(scoreData.prioritySummary)}

P0级别痛点（最紧急）：
${JSON.stringify(scoreData.scores?.filter(s => s.priority === 'P0'))}

请深度思考后，返回如下JSON，不要有其他内容：
{
  "strategies": [
    {
      "title": "策略标题（10字以内）",
      "targetPainPoints": ["针对的痛点关键词"],
      "action": "具体执行方案（50字以内）",
      "expectedResult": "预期效果（30字以内）",
      "priority": "高或中或低",
      "timeframe": "1个月内或1-3个月或3-6个月"
    }
  ],
  "executiveSummary": "给管理层的总结（100字以内）"
}
    `);
    // R1模型响应中提取JSON
    let strategyData = extractJSONFromR1(strategyRaw, { strategies: [], executiveSummary: '策略生成完成' });

    // ========== 报告员：生成报告 (DeepSeek V3) ==========
    const reportRaw = await callV3(API_KEY, `
你是一个专业的教育调研报告撰写员。根据以下分析结果，生成一份简洁专业的调研报告摘要。

数据摘要：
- 共提取痛点：${extractData.totalCount || extractData.painPoints?.length || 0}条
- 分类分布：${JSON.stringify(classifyData.distribution)}
- 优先级分布：${JSON.stringify(scoreData.prioritySummary)}
- 最大问题类别：${getTopCategory(classifyData.distribution)}
- 核心策略数量：${strategyData.strategies?.length || 0}条

请只返回如下JSON，不要有其他内容：
{
  "reportTitle": "报告标题",
  "sections": {
    "overview": "调研概述（60字以内）",
    "mainIssues": "主要问题描述（80字以内）",
    "recommendations": "优先处理建议（80字以内）",
    "conclusion": "结语（40字以内）"
  },
  "keyMetrics": {
    "totalPainPoints": 数字,
    "p0Count": 数字,
    "topCategory": "最多问题的类别",
    "actionRequired": 数字
  }
}
    `);
    let reportData = safeParseJSON(reportRaw, {
      reportTitle: '学校调研分析报告',
      sections: { overview: '分析完成', mainIssues: '', recommendations: '', conclusion: '' },
      keyMetrics: {}
    });

    // 整合所有关键词用于词云
    const allKeywords = [];
    extractData.painPoints?.forEach(p => {
      if (p.keywords) allKeywords.push(...p.keywords);
    });

    return res.status(200).json({
      success: true,
      routerCheck: routerData,
      extract: extractData,
      classify: classifyData,
      score: scoreData,
      strategy: strategyData,
      report: reportData,
      keywords: allKeywords,
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('分析错误:', error);
    return res.status(500).json({ error: '分析过程出错', details: error.message });
  }
}

// ===== 工具函数 =====

async function callV3(apiKey, prompt) {
  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [{ role: 'user', content: prompt }],
      response_format: { type: 'json_object' },
      temperature: 0.3,
      max_tokens: 2000
    })
  });
  const data = await res.json();
  if (!data.choices) throw new Error('DeepSeek V3 API返回异常: ' + JSON.stringify(data));
  return data.choices[0].message.content;
}

async function callR1(apiKey, prompt) {
  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: 'deepseek-reasoner',
      messages: [{ role: 'user', content: prompt }],
      temperature: 1,
      max_tokens: 4000
    })
  });
  const data = await res.json();
  if (!data.choices) throw new Error('DeepSeek R1 API返回异常: ' + JSON.stringify(data));
  return data.choices[0].message.content;
}

function safeParseJSON(str, fallback) {
  try {
    return JSON.parse(str);
  } catch {
    const match = str.match(/\{[\s\S]*\}/);
    if (match) {
      try { return JSON.parse(match[0]); } catch {}
    }
    return fallback;
  }
}

function extractJSONFromR1(str, fallback) {
  // R1 模型可能包含思考过程，提取最后的JSON
  const matches = str.match(/\{[\s\S]*\}/g);
  if (matches && matches.length > 0) {
    for (let i = matches.length - 1; i >= 0; i--) {
      try { return JSON.parse(matches[i]); } catch {}
    }
  }
  return fallback;
}

function getTopCategory(distribution) {
  if (!distribution) return '未知';
  let top = '', max = 0;
  for (const [cat, count] of Object.entries(distribution)) {
    if (count > max) { max = count; top = cat; }
  }
  return top || '未知';
}
