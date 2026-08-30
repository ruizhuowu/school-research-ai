import { ruleBasedAnalysis } from './ruleEngine.js';

// ============================================================
// 防幻觉 Prompt 体系（支柱1：Prompt 工程）
// 每个智能体都有独立 SYSTEM_PROMPT：角色定义 + 铁律约束
// 核心目标：让 AI 只基于输入说话，禁止脑补、禁止改写原文
// ============================================================
const SYSTEM_PROMPTS = {
  // 路由员：质量预检
  router: `你是学校调研数据的"质量检测员"。
铁律：
1. 只依据给定文本判断，不得揣测文本之外的意图。
2. 文本是乱码/重复字符/与学校调研完全无关 → valid=false。
3. 输出必须是合法JSON，不要任何多余文字。`,

  // 提取员：抽取痛点
  extractor: `你是教育调研数据的"痛点提取员"。
铁律：
1. 只提取文本中明确表达的问题或不满，正面反馈一律忽略。
2. keywords 必须逐字来自原文，禁止自行概括或补充原文没有的词。
3. source 必须逐字复制原文片段，禁止改写润色。
4. 原文中未出现的问题，绝不脑补添加。
5. 输出必须是合法JSON，不要任何多余文字。`,

  // 分类员：归类整理
  classifier: `你是教育产品痛点的"分类专家"。
铁律：
1. 只能使用给定的7大分类体系，禁止新增、合并或改名类别。
2. 分类必须依据痛点描述内容，无法明确归类的痛点归入最接近的类别。
3. 每个痛点只能归入一个类别。
4. 输出必须是合法JSON，不要任何多余文字。`,

  // 评分员：优先级打分
  scorer: `你是产品优先级的"评分专家"。
铁律：
1. 评分必须基于痛点文本的实际描述。
2. 文本未提到影响人数时，影响力按保守评分（1-2分）处理，禁止臆测"大量用户"。
3. 综合得分=影响力×紧迫度，优先级必须与得分区间严格对应。
4. 输出必须是合法JSON，不要任何多余文字。`,

  // 策略员：制定策略
  strategist: `你是K12教育智能设备的资深产品经理。
铁律：
1. 策略必须严格针对给定的痛点/分类/优先级数据，禁止套用与数据无关的通用话术。
2. 每条策略都要能对应到具体的痛点关键词。
3. 输出必须是合法JSON，不要任何多余文字。`,

  // 报告员：生成报告
  reporter: `你是教育调研报告的"撰写员"。
铁律：
1. 报告中所有数字必须与给定的数据摘要完全一致，禁止改写。
2. 不得引入摘要中不存在的结论。
3. 输出必须是合法JSON，不要任何多余文字。`
};

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

  // ========== 支柱2：上下文工程 · 输入清洗 ==========
  // 去空白行/重复行/纯标点等噪声片段，降低 prompt 噪声与 token 消耗。
  const { cleaned, removedLines } = cleanInputText(text);
  if (!cleaned || cleaned.trim().length < 20) {
    return res.status(400).json({ error: '清洗后有效内容不足，请提供更详细的调研数据（至少20字）' });
  }

  const API_KEY = process.env.DEEPSEEK_API_KEY;

  // ========== 第一层防护：降级兜底 ==========
  // 没有 API Key 时，产品不能"瘫痪"，直接降级到规则模式（基础模式）。
  if (!API_KEY) {
    const result = ruleBasedAnalysis(cleaned);
    return res.status(200).json({
      success: true,
      mode: 'rule',
      fallbackReason: 'DEEPSEEK_API_KEY 未配置，已自动降级到基础规则模式',
      ...result,
      contextInfo: {
        originalChars: text.length,
        cleanedChars: cleaned.length,
        removedLines,
        chunkCount: 1,
        dedupCount: 0,
        trimmedCount: 0,
        note: '规则模式'
      },
      timestamp: new Date().toISOString()
    });
  }

  try {
    // ========== 路由员：质量预检 (DeepSeek V3) ==========
    const routerRaw = await callV3(API_KEY, SYSTEM_PROMPTS.router, `
你是一个输入质量检测员。判断以下文本是否是有效的学校调研反馈数据。
有效数据应包含：学生/家长/老师的反馈意见、对产品的评价或问题描述。

文本内容（已清洗）：
${cleaned}

请只返回如下JSON，不要有其他内容：
{"valid": true或false, "reason": "简短说明", "quality": "high或medium或low"}
    `);
    let routerData = safeParseJSON(routerRaw, { valid: true, quality: 'medium', reason: '默认通过' });
    if (!routerData.valid) {
      return res.status(400).json({ error: '输入内容不符合要求', reason: routerData.reason });
    }

    // ========== 提取员：抽取痛点 (DeepSeek V3，分块并行) ==========
    // 支柱2：上下文工程 · 长文本分块 —— 超长文本按句切块并行提取后合并去重，
    // 既避免单次调用超 token 截断，又通过多路提取提升痛点召回率。
    const extractData = await extractPainPoints(API_KEY, cleaned);

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
    const scoreRaw = await callV3(API_KEY, SYSTEM_PROMPTS.scorer, `
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
    // 支柱2：上下文工程 · 上下文裁剪 —— 策略员只消费 top-N 高分痛点，
    // 其余痛点仅保留聚合统计，避免低价值上下文稀释 R1 的推理注意力。
    const strategyCtx = trimPainPointsForStrategy(extractData.painPoints, scoreData.scores, 5);
    const strategyRaw = await callR1(API_KEY, SYSTEM_PROMPTS.strategist, `
你是一个资深K12教育智能设备产品经理。请基于以下调研分析数据，制定3-5条核心产品优化策略。

调研痛点数据（已按综合得分降序，仅展示最高优先级的${strategyCtx.topPainPoints.length}条）：
${JSON.stringify(strategyCtx.topPainPoints)}

其余 ${strategyCtx.restCount} 条痛点未逐一展开，优先级分布：${JSON.stringify(strategyCtx.restPrioritySummary)}（策略应优先聚焦上方高分痛点）

分类分布：
${JSON.stringify(classifyData.distribution)}

优先级分布：
${JSON.stringify(scoreData.prioritySummary)}

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
    const reportRaw = await callV3(API_KEY, SYSTEM_PROMPTS.reporter, `
你是一个专业的教育调研报告撰写员。根据以下分析结果，生成一份简洁专业的调研报告摘要。

数据摘要：
- 共提取痛点：${extractData.totalCount || extractData.painPoints?.length || 0}条
- 分类分布：${JSON.stringify(classifyData.distribution)}
- 优先级分布：${JSON.stringify(scoreData.prioritySummary)}
- 最大问题类别：${getTopCategory(classifyData.distribution)}
- 核心策略数量：${strategyData.strategies?.length || 0}条
- 主要痛点举例：${getTopPainExamples(extractData.painPoints, scoreData.scores, 2)}

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

    // ========== 保存到Supabase数据库 ==========
    const SUPABASE_URL = process.env.SUPABASE_URL;
    const SUPABASE_KEY = process.env.SUPABASE_SECRET_KEY;
    if (SUPABASE_URL && SUPABASE_KEY) {
      await saveToSupabase(SUPABASE_URL, SUPABASE_KEY, {
        input_text: text.substring(0, 500),
        total_pain_points: extractData.painPoints?.length || 0,
        p0_count: scoreData.prioritySummary?.P0 || 0,
        p1_count: scoreData.prioritySummary?.P1 || 0,
        p2_count: scoreData.prioritySummary?.P2 || 0,
        top_category: getTopCategory(classifyData.distribution),
        pain_points: extractData.painPoints,
        categories: classifyData.categories,
        scores: scoreData.scores,
        strategies: strategyData.strategies,
        executive_summary: strategyData.executiveSummary,
        keywords: allKeywords
      });
    }

    return res.status(200).json({
      success: true,
      mode: 'ai',
      routerCheck: routerData,
      extract: extractData,
      classify: classifyData,
      score: scoreData,
      strategy: strategyData,
      report: reportData,
      keywords: allKeywords,
      // 支柱2：上下文工程 · 处理信息回传（前端日志区展示）
      contextInfo: {
        originalChars: text.length,
        cleanedChars: cleaned.length,
        removedLines,
        chunkCount: extractData.chunkCount || 1,
        dedupCount: extractData.dedupCount || 0,
        trimmedCount: Math.max(0, (extractData.painPoints?.length || 0) - (strategyCtx.topPainPoints?.length || 0))
      },
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('AI分析出错，触发降级:', error);
    // ========== 第一层防护：降级兜底 ==========
    // AI 模式任一步失败（超时/限流/返回异常），自动降级到规则模式，
    // 而不是让用户看到"分析失败"。
    try {
      const fallback = ruleBasedAnalysis(cleaned);
      return res.status(200).json({
        success: true,
        mode: 'rule',
        fallbackReason: 'AI服务暂不可用，已自动降级到基础规则模式：' + error.message,
        ...fallback,
        contextInfo: {
          originalChars: text.length,
          cleanedChars: cleaned.length,
          removedLines,
          chunkCount: 1,
          dedupCount: 0,
          trimmedCount: 0,
          note: '规则模式'
        },
        timestamp: new Date().toISOString()
      });
    } catch (fallbackError) {
      console.error('规则模式也失败:', fallbackError);
      return res.status(500).json({ error: '分析过程出错', details: error.message });
    }
  }
}

// ===== 工具函数 =====

// systemPrompt 参数：注入防幻觉 SYSTEM_PROMPT（角色+铁律）
async function callV3(apiKey, systemPrompt, prompt) {
  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        { role: 'user', content: prompt }
      ],
      response_format: { type: 'json_object' },
      temperature: 0.3,
      max_tokens: 2000
    })
  });
  const data = await res.json();
  if (!data.choices) throw new Error('DeepSeek V3 API返回异常: ' + JSON.stringify(data));
  return data.choices[0].message.content;
}

async function callR1(apiKey, systemPrompt, prompt) {
  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: 'deepseek-reasoner',
      messages: [
        ...(systemPrompt ? [{ role: 'system', content: systemPrompt }] : []),
        { role: 'user', content: prompt }
      ],
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

// ============================================================
// 支柱2：上下文工程 工具函数
// ============================================================

// 1) 输入清洗：去空白行/重复行/纯标点等噪声，降低 prompt 噪声与 token 消耗
function cleanInputText(text) {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const seen = new Set();
  const cleanedLines = [];
  lines.forEach(l => {
    const key = l.replace(/\s+/g, '');
    if (!seen.has(key)) {
      seen.add(key);
      // 过滤无有效文字的行：无中英文字母（\p{L}）或纯数字噪声
      if (key.length >= 2 && /[\p{L}]/u.test(key) && !/^\d+$/.test(key)) cleanedLines.push(l);
    }
  });
  return { cleaned: cleanedLines.join('\n'), removedLines: lines.length - cleanedLines.length };
}

// 2) 长文本分块：按句切分，每块限制字符数，最多 maxChunks 块；超长单句按字符硬切
function chunkText(text, maxCharsPerChunk = 1800, maxChunks = 3) {
  if (text.length <= maxCharsPerChunk) return [text];
  const sentences = text.split(/[\n\r]+|[。！？!?；;]/).map(s => s.trim()).filter(s => s.length > 0);
  if (sentences.length === 0) return [];
  const chunks = [];
  let cur = '';
  for (const s of sentences) {
    let seg = s;
    // 单句超长时按字符硬切，保证任意输入都能分块
    while (seg.length > maxCharsPerChunk) {
      if (cur) { chunks.push(cur); cur = ''; }
      if (chunks.length >= maxChunks) return chunks;
      chunks.push(seg.slice(0, maxCharsPerChunk));
      seg = seg.slice(maxCharsPerChunk);
    }
    if (cur && (cur + seg).length > maxCharsPerChunk) {
      chunks.push(cur);
      cur = seg;
      if (chunks.length >= maxChunks) break;
    } else {
      cur = cur ? cur + '。' + seg : seg;
    }
  }
  if (cur && chunks.length < maxChunks) chunks.push(cur);
  return chunks;
}

// 3) 分块提取 + 合并去重：多路并行提取提升召回率，按 source 原文去重后重排 id
async function extractPainPoints(apiKey, text) {
  const cleaned = cleanInputText(text).cleaned;
  const chunks = chunkText(cleaned);

  const chunkResults = await Promise.all(chunks.map((chunk, i) =>
    callV3(apiKey, SYSTEM_PROMPTS.extractor, `
你是一个专业的教育调研数据提取员。以下是学校调研文本的第 ${i + 1}/${chunks.length} 块，请提取其中所有用户反馈的痛点和问题。

提取规则：
1. 只提取明确表达的问题或不满，正面反馈一律忽略
2. keywords 必须逐字来自原文，禁止自行概括
3. source 必须逐字复制原文片段，禁止改写润色
4. 原文中未出现的问题，绝不脑补添加
5. 每条痛点单独列出，最多提取10条

文本内容：
${chunk}

请只返回如下JSON，不要有其他内容：
{
  "painPoints": [
    {"id": 1, "text": "痛点描述", "keywords": ["关键词1", "关键词2"], "source": "原文片段"}
  ],
  "totalCount": 数字,
  "summary": "一句话总结"
}
    `)
  ));

  let rawCount = 0;
  const merged = [];
  const seenSource = new Set();
  chunkResults.forEach(r => {
    const d = safeParseJSON(r, { painPoints: [], totalCount: 0, summary: '' });
    const list = d.painPoints || [];
    rawCount += list.length;
    list.forEach(p => {
      const key = (p.source || p.text || '').trim();
      if (key && !seenSource.has(key)) {
        seenSource.add(key);
        merged.push(p);
      }
    });
  });

  // 重新编号，保证后续节点 id 连续
  const painPoints = merged.map((p, i) => ({ ...p, id: i + 1 }));
  return {
    painPoints,
    totalCount: painPoints.length,
    summary: chunks.length > 1
      ? `分块提取（${chunks.length}块）合并去重后共 ${painPoints.length} 条痛点`
      : `提取到 ${painPoints.length} 条痛点`,
    chunkCount: chunks.length,
    dedupCount: Math.max(0, rawCount - painPoints.length)
  };
}

// 4) 上下文裁剪：策略员只消费 top-N 高分痛点，其余痛点仅保留聚合统计
function trimPainPointsForStrategy(painPoints, scores, topN = 5) {
  const scored = (painPoints || []).map(p => {
    const s = (scores || []).find(x => x.id === p.id);
    return { ...p, score: s?.score || 0, priority: s?.priority || 'P2' };
  });
  scored.sort((a, b) => (b.score || 0) - (a.score || 0));
  const topPainPoints = scored.slice(0, topN);
  const rest = scored.slice(topN);
  const restPrioritySummary = { P0: 0, P1: 0, P2: 0 };
  rest.forEach(p => { restPrioritySummary[p.priority]++; });
  return { topPainPoints, restCount: rest.length, restPrioritySummary };
}

// 5) 取得分最高的 n 条痛点原文片段（供报告员引用，保证报告内容与数据一致）
function getTopPainExamples(painPoints, scores, n = 2) {
  const sorted = (scores || []).slice().sort((a, b) => (b.score || 0) - (a.score || 0));
  const texts = sorted.slice(0, n).map(s => {
    const p = (painPoints || []).find(x => x.id === s.id);
    return p ? (p.text || '').slice(0, 40) : '';
  }).filter(Boolean);
  return texts.join('；') || '暂无';
}

// 导出纯函数供单元测试复用（不导出内部状态，仅导出无副作用工具）
export { cleanInputText, chunkText, trimPainPointsForStrategy, getTopPainExamples };

async function saveToSupabase(url, key, record) {
  try {
    const res = await fetch(`${url}/rest/v1/analyses`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${key}`,
        'apikey': key,
        'Prefer': 'return=minimal'
      },
      body: JSON.stringify(record)
    });
    if (!res.ok) {
      const err = await res.text();
      console.error('Supabase保存失败:', err);
    }
  } catch (e) {
    console.error('Supabase连接错误:', e.message);
  }
}
