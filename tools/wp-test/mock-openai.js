#!/usr/bin/env node
/**
 * Mock OpenAI-compatible API server for AIWC end-to-end tests.
 * Implements /v1/chat/completions (with tool calls) and /v1/models.
 *
 * Deterministic behavior:
 *  - "create page ..."      -> tool_call create_page, then final summary
 *  - "analyze seo <id>"     -> tool_call seo_analyze, then final summary
 *  - "delete page <id>"     -> tool_call delete_page, then final summary
 *  - "remember ..."         -> tool_call memory_save
 *  - anything else          -> plain text reply
 */
const http = require('http');

const PORT = process.env.MOCK_PORT ? parseInt(process.env.MOCK_PORT, 10) : 8899;

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

function firstNumber(text, fallback) {
  const m = String(text || '').match(/\b(\d+)\b/);
  return m ? parseInt(m[1], 10) : fallback;
}

function hasToolResult(messages) {
  return messages.some((m) => m.role === 'tool');
}

function lastUserText(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === 'user') return String(messages[i].content || '');
  }
  return '';
}

function completion(res, message, finishReason) {
  json(res, 200, {
    id: 'chatcmpl-mock-' + Date.now(),
    object: 'chat.completion',
    created: Math.floor(Date.now() / 1000),
    model: 'mock-gpt',
    choices: [
      {
        index: 0,
        message,
        finish_reason: finishReason || (message.tool_calls ? 'tool_calls' : 'stop'),
      },
    ],
    usage: { prompt_tokens: 120, completion_tokens: 60, total_tokens: 180 },
  });
}

function toolCall(id, name, args) {
  return {
    id,
    type: 'function',
    function: { name, arguments: JSON.stringify(args) },
  };
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url.startsWith('/v1/models')) {
    return json(res, 200, {
      object: 'list',
      data: [{ id: 'mock-gpt' }, { id: 'mock-gpt-mini' }, { id: 'mock-gpt-pro' }],
    });
  }

  if (req.method === 'POST' && req.url.startsWith('/v1/chat/completions')) {
    let raw = '';
    req.on('data', (chunk) => (raw += chunk));
    req.on('end', () => {
      let body = {};
      try {
        body = JSON.parse(raw || '{}');
      } catch (e) {
        return json(res, 400, { error: { message: 'invalid JSON' } });
      }
      const messages = Array.isArray(body.messages) ? body.messages : [];

      if (hasToolResult(messages)) {
        const lastTool = [...messages].reverse().find((m) => m.role === 'tool');
        let outcome = 'ok';
        try {
          const parsed = JSON.parse(lastTool.content || '{}');
          outcome = parsed.success ? 'ok' : 'failed';
        } catch (e) {}
        return completion(res, {
          role: 'assistant',
          content:
            '## گزارش تغییرات\n\nعملیات با موفقیت انجام شد (نتیجه: ' +
            outcome +
            ').\n\n- ابزار اجراشده ثبت شد\n- تغییرات در تاریخچه فعالیت‌ها قابل بازگردانی است\n\nAll done — the requested operation has been executed and logged.',
        });
      }

      const text = lastUserText(messages);

      if (/(create page|ایجاد صفحه|بساز|بسازید|create a page)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_create_1', 'create_page', {
              title: 'AIWC Test Page ' + Date.now(),
              content:
                '<h2>درباره ما</h2><p>این صفحه توسط دستیار هوشمند وردپرس ساخته شده است.</p><ul><li>طراحی مدرن</li><li>سئو محور</li></ul>',
              status: 'publish',
            }),
          ],
        });
      }

      if (/(analyze seo|تحلیل سئو|seo analyze)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_seo_1', 'seo_analyze', { post_id: firstNumber(text, 1) }),
          ],
        });
      }

      if (/(update page|ویرایش صفحه|update the page)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_upd_1', 'update_page', {
              post_id: firstNumber(text, 1),
              title: 'Updated Title ' + Date.now(),
              content: '<p>Updated content by AI agent.</p>',
              content_mode: 'replace',
            }),
          ],
        });
      }

      if (/(delete|حذف)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_del_1', 'delete_page', {
              post_id: firstNumber(text, 1),
              permanent: false,
            }),
          ],
        });
      }

      if (/(remember|یاد بگیر|به خاطر بسپار)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_mem_1', 'memory_save', {
              category: 'brand',
              key: 'primary_color',
              value: 'سرمه‌ای',
            }),
          ],
        });
      }

      if (/(site overview|نمای کلی)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [toolCall('call_ov_1', 'site_overview', {})],
        });
      }

      return completion(res, {
        role: 'assistant',
        content:
          'سلام! من دستیار هوشمند وردپرس هستم. می‌توانم صفحه بسازم، سئو را تحلیل کنم و سایت را مدیریت کنم.\n\nHello! I am your WordPress copilot. Try: "create page", "analyze seo <id>", "site overview".',
      });
    });
    return;
  }

  json(res, 404, { error: { message: 'not found: ' + req.url } });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('mock-openai listening on 0.0.0.0:' + PORT);
});
