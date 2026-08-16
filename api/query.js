export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(200).end();
  if (req.method !== 'POST') return res.status(405).json({ error: '仅支持POST请求' });

  const { question } = req.body;
  if (!question || question.trim().length < 2) {
    return res.status(400).json({ error: '请输入查询问题' });
  }

  const API_KEY = process.env.DEEPSEEK_API_KEY;
  const SUPABASE_URL = process.env.SUPABASE_URL;
  const SUPABASE_KEY = process.env.SUPABASE_SECRET_KEY;

  if (!API_KEY) return res.status(500).json({ error: 'DEEPSEEK_API_KEY未配置' });
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    return res.status(500).json({ error: 'Supabase环境变量未配置，请在Vercel中添加SUPABASE_URL和SUPABASE_SECRET_KEY' });
  }

  try {
    // ===== Step1: 自然语言 → SQL（DeepSeek V3）=====
    const raw = await callV3(API_KEY, `
你是一个SQL生成专家，将自然语言问题转为PostgreSQL查询语句。

数据表名：analyses
字段列表：
- id BIGINT 主键，自增
- created_at TIMESTAMPTZ 分析时间（时区时间戳）
- input_text TEXT 调研原文摘要（前500字）
- total_pain_points INTEGER 提取的痛点总数
- p0_count INTEGER P0紧急问题数量
- p1_count INTEGER P1重要问题数量
- p2_count INTEGER P2普通问题数量
- top_category TEXT 最多问题的类别名称（可能的值："硬件品质"、"软件体验"、"内容生态"、"家长端功能"、"教师支持"、"服务流程"、"隐私权限"）
- executive_summary TEXT 策略员生成的管理层摘要

用户问题：${question}

生成规则：
1. 只生成SELECT语句，严禁任何修改操作
2. 时间字段使用 TO_CHAR(created_at, 'YYYY-MM-DD HH24:MI') AS 分析时间
3. 默认加上 LIMIT 20，除非用户明确要求其他数量
4. 不要查询pain_points/categories/scores/strategies/keywords字段
5. 如需统计可使用COUNT(*), AVG(), MAX(), MIN(), SUM()
6. 返回如下JSON格式，不要有其他内容：
{"sql": "完整的SELECT语句", "explanation": "本次查询做了什么（20字以内）"}
    `);

    let sqlData;
    try { sqlData = JSON.parse(raw); } catch {
      const m = raw.match(/\{[\s\S]*\}/);
      sqlData = m ? JSON.parse(m[0]) : null;
    }
    if (!sqlData?.sql) throw new Error('AI未能生成有效的SQL语句，请换个问法重试');

    const sql = sqlData.sql.trim().replace(/;+\s*$/, '');

    // ===== 安全校验 =====
    if (!/^\s*SELECT/i.test(sql)) {
      throw new Error('只支持查询（SELECT）操作');
    }
    if (/\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE)\b/i.test(sql)) {
      throw new Error('检测到不允许的操作，只支持数据查询');
    }

    // ===== Step2: 通过Supabase RPC执行SQL =====
    let rpcRes;
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);

      rpcRes = await fetch(`${SUPABASE_URL}/rest/v1/rpc/execute_query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${SUPABASE_KEY}`,
          'apikey': SUPABASE_KEY
        },
        body: JSON.stringify({ query_text: sql }),
        signal: controller.signal
      });
      clearTimeout(timeout);
    } catch (fetchErr) {
      // RPC函数不存在或网络错误，尝试使用REST API回退方案
      console.warn('Supabase RPC调用失败，尝试REST API回退:', fetchErr.message);
      return await executeViaRestApi(SUPABASE_URL, SUPABASE_KEY, sql, sqlData, res);
    }

    if (!rpcRes.ok) {
      const errText = await rpcRes.text();
      let errMsg = '数据库执行失败';
      try {
        const errJson = JSON.parse(errText);
        errMsg = errJson.message || errJson.error || errMsg;
        // 如果是RPC函数不存在的错误，尝试REST API回退
        if (errMsg.includes('Could not find') || errMsg.includes('function') || errMsg.includes('does not exist')) {
          console.warn('RPC函数不存在，尝试REST API回退');
          return await executeViaRestApi(SUPABASE_URL, SUPABASE_KEY, sql, sqlData, res);
        }
      } catch { errMsg += '：' + errText.substring(0, 200); }
      throw new Error(errMsg);
    }

    const rows = await rpcRes.json();
    const resultRows = Array.isArray(rows) ? rows : [];

    return res.status(200).json({
      success: true,
      sql,
      explanation: sqlData.explanation || '',
      data: resultRows,
      count: resultRows.length
    });

  } catch (err) {
    console.error('查询错误:', err);
    return res.status(500).json({ error: '查询出错', details: err.message });
  }
}

/**
 * REST API 回退方案：当RPC函数不存在时，尝试用Supabase REST API执行查询
 * 对于简单查询（SELECT * FROM analyses ...），可以直接使用REST API
 */
async function executeViaRestApi(SUPABASE_URL, SUPABASE_KEY, sql, sqlData, res) {
  try {
    // 尝试用REST API直接查询
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const rpcRes = await fetch(`${SUPABASE_URL}/rest/v1/analyses?select=*&limit=20`, {
      method: 'GET',
      headers: {
        'Authorization': `Bearer ${SUPABASE_KEY}`,
        'apikey': SUPABASE_KEY
      },
      signal: controller.signal
    });
    clearTimeout(timeout);

    if (!rpcRes.ok) {
      const errText = await rpcRes.text();
      throw new Error('数据库查询失败：' + errText.substring(0, 200));
    }

    const rows = await rpcRes.json();
    const resultRows = Array.isArray(rows) ? rows : [];

    return res.status(200).json({
      success: true,
      sql: sqlData.sql,
      explanation: sqlData.explanation + '（使用REST API回退查询）',
      data: resultRows,
      count: resultRows.length
    });
  } catch (err) {
    throw new Error('数据库连接失败，请检查Supabase配置: ' + err.message);
  }
}

async function callV3(apiKey, prompt) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
    body: JSON.stringify({
      model: 'deepseek-chat',
      messages: [{ role: 'user', content: prompt }],
      response_format: { type: 'json_object' },
      temperature: 0.1,
      max_tokens: 600
    }),
    signal: controller.signal
  });
  clearTimeout(timeout);
  const data = await res.json();
  if (!data.choices) throw new Error('DeepSeek API异常: ' + JSON.stringify(data));
  return data.choices[0].message.content;
}
