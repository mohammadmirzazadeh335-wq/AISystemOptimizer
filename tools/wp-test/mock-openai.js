#!/usr/bin/env node
/**
 * Mock OpenAI-compatible API server for AIWC end-to-end tests.
 * Implements /v1/chat/completions (with tool calls) and /v1/models.
 *
 * Deterministic behavior:
 *  - "create page ..."      -> tool_call create_page, then final summary
 *  - "update page <id>"     -> tool_call update_page, then final summary
 *  - "analyze seo <id>"     -> tool_call seo_analyze, then final summary
 *  - "delete page <id>"     -> tool_call delete_page, then final summary
 *  - "remember ..."         -> tool_call memory_save
 *  - "performance ..."      -> tool_call performance_analyze
 *  - "make user <id> ..."   -> tool_call users_manage_role (critical risk)
 *  - "slow ..."             -> same as create page but each reply takes 8s
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

function chunk(res, obj) {
  res.write('data: ' + JSON.stringify(obj) + '\n\n');
}

function streamCompletion(res, body) {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    Connection: 'keep-alive',
    'Access-Control-Allow-Origin': '*',
  });
  if (!body) {
    res.write('data: [ERROR]\n\n');
    return res.end();
  }
  const msg = (body.choices && body.choices[0] && body.choices[0].message) || {};
  const base = { id: body.id || 'chatcmpl-mock-stream', object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: body.model || 'mock-gpt' };

  chunk(res, { ...base, choices: [{ index: 0, delta: { role: 'assistant' }, finish_reason: null }] });

  if (Array.isArray(msg.tool_calls) && msg.tool_calls.length) {
    msg.tool_calls.forEach((tc, i) => {
      const argsStr = tc.function.arguments || '{}';
      const half = Math.ceil(argsStr.length / 2);
      chunk(res, {
        ...base,
        choices: [{ index: 0, delta: { tool_calls: [{ index: i, id: tc.id, type: 'function', function: { name: tc.function.name, arguments: '' } }] }, finish_reason: null }],
      });
      chunk(res, {
        ...base,
        choices: [{ index: 0, delta: { tool_calls: [{ index: i, function: { arguments: argsStr.slice(0, half) } }] }, finish_reason: null }],
      });
      chunk(res, {
        ...base,
        choices: [{ index: 0, delta: { tool_calls: [{ index: i, function: { arguments: argsStr.slice(half) } }] }, finish_reason: null }],
      });
    });
    chunk(res, { ...base, choices: [{ index: 0, delta: {}, finish_reason: 'tool_calls' }] });
  } else {
    const content = msg.content || '';
    const third = Math.ceil(content.length / 3) || 1;
    for (let i = 0; i < content.length; i += third) {
      chunk(res, { ...base, choices: [{ index: 0, delta: { content: content.slice(i, i + third) }, finish_reason: null }] });
    }
    chunk(res, { ...base, choices: [{ index: 0, delta: {}, finish_reason: 'stop' }] });
  }

  chunk(res, { ...base, choices: [], usage: body.usage || { prompt_tokens: 10, completion_tokens: 10, total_tokens: 20 } });
  res.write('data: [DONE]\n\n');
  res.end();
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
  if (mockLegacy && Array.isArray(message.tool_calls) && message.tool_calls.length) {
    const tc = message.tool_calls[0];
    message = {
      role: 'assistant',
      content: '```aiwc-tool\n' + JSON.stringify({ tool: tc.function.name, args: JSON.parse(tc.function.arguments || '{}') }) + '\n```',
    };
    finishReason = 'stop';
  }
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

let mockLegacy = false; // when true, tool calls are returned as ```aiwc-tool fenced content
let mockTools = [];     // tools offered in the current request (for probes)

function respondTo(res, messages) {
  const probeText = lastUserText(messages);

  // Capability-probe prompts (used by detect_capabilities).
  if (/(Call the ping tool|Reply with exactly OK)/.test(probeText) && mockTools.length) {
    return completion(res, {
      role: 'assistant',
      content: null,
      tool_calls: [toolCall('call_probe', mockTools[0].function.name, { ok: true })],
    });
  }
  if (/Say STREAM-OK/.test(probeText)) {
    return completion(res, { role: 'assistant', content: 'STREAM-OK' });
  }
  if (/Return ONLY a JSON object/.test(probeText)) {
    return completion(res, { role: 'assistant', content: '{"status":"ok"}' });
  }

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

  if (/(create page|ایجاد صفحه|بساز|بسازید|create a page|slow)/i.test(text)) {
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

  if (/(analyze seo|تحلیل سئو|seo analyze)/i.test(text)) {
    return completion(res, {
      role: 'assistant',
      content: null,
      tool_calls: [
        toolCall('call_seo_1', 'seo_analyze', { post_id: firstNumber(text, 1) }),
      ],
    });
  }

      if (/(create product|ایجاد محصول|محصول بساز)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_wooc_1', 'woo_product_create', {
              title: 'AIWC Test Product ' + Date.now(),
              price: '9.99',
              status: 'publish',
            }),
          ],
        });
      }

      if (/(edit product|update product|ویرایش محصول)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_woou_1', 'woo_product_update', {
              product_id: firstNumber(text, 1),
              price: '14.50',
            }),
          ],
        });
      }

      if (/(woo report|sales report|گزارش فروش)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [toolCall('call_woorpt_1', 'woo_report', {})],
        });
      }

      if (/(list products|product list|لیست محصولات)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [toolCall('call_woolist_1', 'woo_product_list', { per_page: 10 })],
        });
      }

      if (/(elementor|المنتور)/i.test(text)) {
        return completion(res, {
          role: 'assistant',
          content: null,
          tool_calls: [
            toolCall('call_elem_1', 'create_elementor_section', {
              title: 'AIWC Elementor Page ' + Date.now(),
              status: 'publish',
              sections: [
                {
                  columns: [
                    {
                      width: 100,
                      widgets: [
                        { type: 'heading', settings: { title: 'AIWC Elementor Section' } },
                        { type: 'text', settings: { text: 'طراحی شده با دستیار هوشمند' } },
                        { type: 'button', settings: { text: 'بیشتر بدانید' } },
                      ],
                    },
                  ],
                },
              ],
            }),
          ],
        });
      }

      if (/(performance|speed|سرعت|کارایی)/i.test(text)) {
    return completion(res, {
      role: 'assistant',
      content: null,
      tool_calls: [toolCall('call_perf_1', 'performance_analyze', {})],
    });
  }

  if (/(make user|change role|تغییر نقش|نقش کاربر)/i.test(text)) {
    return completion(res, {
      role: 'assistant',
      content: null,
      tool_calls: [
        toolCall('call_role_1', 'users_manage_role', {
          user_id: firstNumber(text, 1),
          role: 'editor',
          action: 'add',
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
}

const server = http.createServer((req, res) => {
  // Link-checker test endpoints.
  if (req.url.startsWith('/status/200')) return json(res, 200, { ok: true });
  if (req.url.startsWith('/status/404')) return json(res, 404, { error: { message: 'not found' } });
  if (req.url.startsWith('/status/500')) return json(res, 500, { error: { message: 'server error' } });
  if (req.url.startsWith('/status/301')) {
    res.writeHead(301, { Location: '/status/200' });
    return res.end();
  }
  if (req.url.startsWith('/status/302-evil')) {
    res.writeHead(302, { Location: 'http://169.254.169.254/latest/meta-data/' });
    return res.end();
  }
  if (req.url.startsWith('/status/302-relative')) {
    res.writeHead(302, { Location: '/status/200' });
    return res.end();
  }
  if (req.url.startsWith('/status/timeout')) {
    return setTimeout(() => json(res, 200, { ok: true }), 20000);
  }

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
      // Error-injection via model name (for testing the provider error layer).
      if (body.model === 'mock-401') return json(res, 401, { error: { message: 'Incorrect API key provided', type: 'invalid_request_error' } });
      if (body.model === 'mock-404') return json(res, 404, { error: { message: 'The model `x` does not exist', code: 'model_not_found' } });
      if (body.model === 'mock-429') return json(res, 429, { error: { message: 'Rate limit exceeded', type: 'rate_limit_exceeded' } });
      if (body.model === 'mock-500') return json(res, 500, { error: { message: 'The server had an error' } });
      const messages = Array.isArray(body.messages) ? body.messages : [];
      mockLegacy = !Array.isArray(body.tools) || body.tools.length === 0;
      mockTools = Array.isArray(body.tools) ? body.tools : [];
      const allText = messages.filter((m) => m.role === 'user').map((m) => m.content).join(' ');
      const delay = /slow/i.test(allText) ? 8000 : 0;

      if (body.stream) {
        // Capture the non-stream decision, then replay it as SSE chunks
        // (tool-call arguments are deliberately split into fragments to
        // exercise the client-side assembler).
        let captured = null;
        const stub = {
          writeHead() {},
          end(s) {
            try {
              captured = JSON.parse(s);
            } catch (e) {
              captured = null;
            }
          },
        };
        return setTimeout(() => {
          respondTo(stub, messages);
          streamCompletion(res, captured);
        }, delay);
      }

      setTimeout(() => respondTo(res, messages), delay);
    });
    return;
  }

  json(res, 404, { error: { message: 'not found: ' + req.url } });
});

server.listen(PORT, '0.0.0.0', () => {
  console.log('mock-openai listening on 0.0.0.0:' + PORT);
});
