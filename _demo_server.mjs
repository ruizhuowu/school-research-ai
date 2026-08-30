import http from 'http';
import { readFileSync } from 'fs';
import { join, extname } from 'path';
import { ruleBasedAnalysis } from './api/ruleEngine.js';
import { cleanInputText } from './api/analyze.js';

const root = process.cwd();
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json'
};

http.createServer(async (req, res) => {
  const url = req.url.split('?')[0];

  // 模拟 /api/analyze：故意走规则模式，演示"无 API Key 自动降级"
  if (url === '/api/analyze' && req.method === 'POST') {
    let body = '';
    for await (const chunk of req) body += chunk;
    let text;
    try {
      text = JSON.parse(body).text;
    } catch {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: '请求体不是合法 JSON' }));
      return;
    }
    // 支柱2：上下文工程 · 输入清洗（与 AI 模式同一套逻辑，演示清洗效果）
    const { cleaned, removedLines } = cleanInputText(text);
    const result = ruleBasedAnalysis(cleaned);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      success: true,
      mode: 'rule',
      fallbackReason: '本地演示：模拟 DeepSeek API 不可用，已自动降级到基础规则模式',
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
    }));
    return;
  }

  if (url === '/api/query' && req.method === 'POST') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ success: true, sql: '-- 本地演示模式\nSELECT * FROM analyses LIMIT 0', explanation: '本地演示，暂无历史数据', data: [], count: 0 }));
    return;
  }

  const file = url === '/' ? 'index.html' : url.replace(/^\/+/, '');
  try {
    const content = readFileSync(join(root, file));
    res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'application/octet-stream' });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end('Not Found');
  }
}).listen(3000, () => console.log('demo server running: http://localhost:3000'));
