/**
 * AIWC chat UI — conversations, tool steps, approvals.
 */
(function (global) {
  'use strict';

  var A = global.AIWC;

  var state = {
    conversations: [],
    activeId: 0,
    messages: [],
    busy: false
  };

  function renderList() {
    var el = document.getElementById('aiwc-chat-list');
    if (!el) return;
    if (!state.conversations.length) {
      el.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('no_conversations')) + '</div>';
      return;
    }
    var html = '';
    state.conversations.forEach(function (c) {
      html += '<div class="aiwc-chat-item' + (c.id === state.activeId ? ' active' : '') + '" data-id="' + c.id + '">' +
        '<span class="title">' + A.esc(c.title || '...') + '</span>' +
        '<span class="del" data-del="' + c.id + '" title="' + A.esc(A.t('delete')) + '">&times;</span>' +
        '</div>';
    });
    el.innerHTML = html;

    el.querySelectorAll('.aiwc-chat-item').forEach(function (item) {
      item.addEventListener('click', function (e) {
        if (e.target.dataset.del) return;
        selectConversation(parseInt(item.dataset.id, 10));
      });
    });
    el.querySelectorAll('.del').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = parseInt(btn.dataset.del, 10);
        if (!confirm(A.t('confirm_delete'))) return;
        A.api('conversations/' + id, { method: 'DELETE' }).then(function () {
          state.conversations = state.conversations.filter(function (c) { return c.id !== id; });
          if (state.activeId === id) {
            state.activeId = 0;
            state.messages = [];
            renderMessages();
          }
          renderList();
        }).catch(function (err) { A.toast(err.message, true); });
      });
    });
  }

  function renderMessages() {
    var el = document.getElementById('aiwc-chat-body');
    if (!el) return;
    if (!state.messages.length) {
      el.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('no_conversations')) + '</div>';
      return;
    }
    var html = '';
    state.messages.forEach(function (m) {
      if (m.role === 'user') {
        html += '<div class="aiwc-msg user">' + global.AIWCMarkdown.render(m.content || '') + '</div>';
      } else if (m.role === 'assistant') {
        html += '<div class="aiwc-msg assistant">' + global.AIWCMarkdown.render(m.content || '') + '</div>';
      } else if (m.role === 'tool') {
        html += renderToolStep(m);
      }
    });
    el.innerHTML = html;

    // Approve / reject buttons.
    el.querySelectorAll('[data-approve]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        resolveApproval(parseInt(btn.dataset.approve, 10), true, btn);
      });
    });
    el.querySelectorAll('[data-reject]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        resolveApproval(parseInt(btn.dataset.reject, 10), false, btn);
      });
    });
    // Direct rollback buttons on tool steps.
    el.querySelectorAll('[data-rollback]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!confirm(A.t('confirm_delete'))) return;
        btn.disabled = true;
        A.api('snapshots/' + btn.dataset.rollback + '/restore', { method: 'POST' })
          .then(function (res) {
            A.toast(A.t('rollback_done'));
            if (state.activeId) loadMessages(state.activeId);
          })
          .catch(function (err) {
            btn.disabled = false;
            A.toast(err.message, true);
          });
      });
    });

    el.scrollTop = el.scrollHeight;
  }

  function renderToolStep(m) {
    var payload = {};
    try {
      payload = JSON.parse(m.content || '{}') || {};
    } catch (e) {
      payload = { summary: m.content };
    }

    var icon = m.status === 'ok' ? '&#10003;' : (m.status === 'pending' ? '&#9203;' : '&#10007;');
    var cls = m.status === 'ok' ? 'ok' : (m.status === 'pending' ? 'warn' : 'err');
    var title = m.tool_name || 'tool';
    var summary = payload.summary || payload.message || '';
    if (payload.pending && payload.approval_id) {
      summary = A.t('pending_approval') + ' — ' + title;
    }

    var html = '<div class="aiwc-step">' +
      '<div class="aiwc-step-head"><span class="icon aiwc-badge ' + cls + '">' + icon + '</span>' +
      '<span style="direction:ltr;font-family:monospace">' + A.esc(title) + '</span>' +
      '<span class="aiwc-badge ' + cls + '">' + A.esc(m.status) + '</span></div>' +
      (summary ? '<div style="margin-top:6px;color:var(--aiwc-text-2)">' + A.esc(summary) + '</div>' : '');

    if (payload.data !== undefined && payload.data !== null) {
      html += '<div class="aiwc-step-detail">' + A.esc(JSON.stringify(payload.data, null, 2).slice(0, 1200)) + '</div>';
    }
    if (payload.data && payload.data.url) {
      html += '<div style="margin-top:6px"><a class="aiwc-btn sm" href="' + A.esc(payload.data.url) + '" target="_blank" rel="noopener">' + A.esc(A.t('preview')) + '</a></div>';
    }
    if (payload.snapshot_id) {
      html += '<div style="margin-top:6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
        '<span class="aiwc-badge info">snapshot #' + payload.snapshot_id + '</span>' +
        '<button class="aiwc-btn danger sm" data-rollback="' + payload.snapshot_id + '">' + A.esc(A.t('rollback')) + '</button>' +
        '</div>';
    }
    if (payload.pending && payload.approval_id) {
      html += '<div class="actions">' +
        '<button class="aiwc-btn success sm" data-approve="' + payload.approval_id + '">' + A.esc(A.t('approve')) + '</button>' +
        '<button class="aiwc-btn danger sm" data-reject="' + payload.approval_id + '">' + A.esc(A.t('reject')) + '</button>' +
        '</div>';
    }
    html += '</div>';
    return '<div class="aiwc-steps">' + html + '</div>';
  }

  function resolveApproval(id, approve, btn) {
    btn.disabled = true;
    A.api('approvals/' + id + '/' + (approve ? 'approve' : 'reject'), { method: 'POST' })
      .then(function (res) {
        A.toast(approve ? A.t('approved') : A.t('rejected'));
        if (state.activeId) {
          loadMessages(state.activeId);
        }
      })
      .catch(function (err) {
        btn.disabled = false;
        A.toast(err.message, true);
      });
  }

  function selectConversation(id) {
    state.activeId = id;
    renderList();
    loadMessages(id);
  }

  function loadMessages(id) {
    return A.api('conversations/' + id + '/messages').then(function (data) {
      state.messages = data.messages || [];
      renderMessages();
    }).catch(function (err) { A.toast(err.message, true); });
  }

  function setBusyUI(busy) {
    var send = document.getElementById('aiwc-send');
    var stop = document.getElementById('aiwc-stop');
    if (send) send.style.display = busy ? 'none' : '';
    if (stop) stop.style.display = busy ? '' : 'none';
  }

  function sendMessage() {
    var input = document.getElementById('aiwc-chat-input');
    var text = (input.value || '').trim();
    if (!text || state.busy) return;

    state.busy = true;
    input.value = '';
    setBusyUI(true);
    state.messages.push({ role: 'user', content: text, status: 'ok' });
    renderMessages();

    var body = document.getElementById('aiwc-chat-body');
    var thinking = document.createElement('div');
    thinking.className = 'aiwc-thinking';
    thinking.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span><span>' + A.esc(A.t('thinking')) + '</span>';
    body.appendChild(thinking);
    body.scrollTop = body.scrollHeight;

    A.api('chat', {
      method: 'POST',
      body: {
        message: text,
        conversation_id: state.activeId || 0
      }
    }).then(function (res) {
      thinking.remove();
      state.busy = false;
      setBusyUI(false);
      if (res.conversation_id) {
        state.activeId = res.conversation_id;
      }
      return loadConversations().then(function () {
        return loadMessages(state.activeId);
      }).then(function () {
        if (res.usage && res.usage.total_tokens) {
          updateUsage(res.usage, res.conversation_id ? res.conversation_id : state.activeId);
        }
      });
    }).catch(function (err) {
      thinking.remove();
      state.busy = false;
      setBusyUI(false);
      state.messages.push({
        role: 'assistant',
        content: '**' + A.t('error') + ':** ' + err.message,
        status: 'error'
      });
      renderMessages();
    });
  }

  function updateUsage(usage, convId) {
    var el = document.getElementById('aiwc-chat-usage');
    if (el) {
      el.innerHTML = '<span class="aiwc-badge info">' + A.esc(A.t('tokens_used')) + ': ' + A.fmtNum(usage.total_tokens || 0) + '</span>';
    }
  }

  function loadConversations() {
    return A.api('conversations').then(function (data) {
      state.conversations = data.items || [];
      if (!state.activeId && state.conversations.length) {
        state.activeId = state.conversations[0].id;
      }
      renderList();
    });
  }

  function renderChat(container) {
    container.innerHTML =
      '<div class="aiwc-chat">' +
      '  <div class="aiwc-chat-list" id="aiwc-chat-list"></div>' +
      '  <div class="aiwc-chat-main">' +
      '    <div class="aiwc-chat-head">' +
      '      <div><strong>' + A.esc(A.t('chat')) + '</strong> ' +
      '        <span class="aiwc-badge info">' + A.esc(A.model || '') + '</span> ' +
      '        <span id="aiwc-chat-usage"></span>' +
      '      </div>' +
      '      <button class="aiwc-btn sm" id="aiwc-new-chat">' + A.esc(A.t('new_chat')) + '</button>' +
      '    </div>' +
      '    <div class="aiwc-chat-body" id="aiwc-chat-body"></div>' +
      '    <div class="aiwc-chat-foot">' +
      '      <textarea id="aiwc-chat-input" placeholder="' + A.esc(A.t('chat_placeholder')) + '" rows="2"></textarea>' +
      '      <button class="aiwc-btn primary" id="aiwc-send">' + A.esc(A.t('send')) + '</button>' +
      '      <button class="aiwc-btn danger" id="aiwc-stop" style="display:none">&#9632; ' + A.esc(A.t('cancel')) + '</button>' +
      '    </div>' +
      '  </div>' +
      '</div>';

    document.getElementById('aiwc-new-chat').addEventListener('click', function () {
      state.activeId = 0;
      state.messages = [];
      renderMessages();
      document.getElementById('aiwc-chat-input').focus();
    });
    document.getElementById('aiwc-send').addEventListener('click', sendMessage);
    document.getElementById('aiwc-stop').addEventListener('click', function () {
      A.api('chat/cancel', { method: 'POST' })
        .then(function () { A.toast(A.t('cancel')); })
        .catch(function (err) { A.toast(err.message, true); });
    });
    document.getElementById('aiwc-chat-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    renderMessages();
    loadConversations().then(function () {
      if (state.activeId) {
        loadMessages(state.activeId);
      }
    }).catch(function (err) {
      A.toast(err.message, true);
    });
  }

  global.AIWCChat = {
    render: renderChat
  };
})(window);
