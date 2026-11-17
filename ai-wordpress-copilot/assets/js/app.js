/**
 * AIWC admin app — router and pages.
 */
(function (global) {
  'use strict';

  var A = global.AIWC;

  var routes = {
    dashboard: renderDashboard,
    chat: function (c) { global.AIWCChat.render(c); },
    tools: renderTools,
    design: renderDesign,
    seo: renderSeo,
    content: renderContent,
    logs: renderLogs,
    memory: renderMemory,
    settings: renderSettings,
    api: renderApi
  };

  var routeTitles = {
    dashboard: 'dashboard',
    chat: 'chat',
    tools: 'tools',
    design: 'design',
    seo: 'seo',
    content: 'content',
    logs: 'logs',
    memory: 'memory_title',
    settings: 'settings',
    api: 'api'
  };

  var navItems = [
    ['dashboard', 'dashicons-dashboard', 'dashboard'],
    ['chat', 'dashicons-format-chat', 'chat'],
    ['tools', 'dashicons-admin-tools', 'tools'],
    ['design', 'dashicons-art', 'design'],
    ['seo', 'dashicons-chart-area', 'seo'],
    ['content', 'dashicons-admin-post', 'content'],
    ['logs', 'dashicons-list-view', 'logs'],
    ['memory', 'dashicons-migrate', 'memory_title'],
    ['api', 'dashicons-plugins-checked', 'api'],
    ['settings', 'dashicons-admin-generic', 'settings']
  ];

  var currentRoute = 'dashboard';

  function go(route) {
    if (!routes[route]) route = 'dashboard';
    currentRoute = route;
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
    renderShell();
  }

  function renderShell() {
    var root = document.getElementById('aiwc-app');
    if (!root) return;

    root.setAttribute('data-theme', A.theme || 'dark');
    root.setAttribute('dir', A.language === 'fa' ? 'rtl' : 'ltr');

    var nav = '';
    navItems.forEach(function (item) {
      nav += '<a data-route="' + item[0] + '" class="' + (currentRoute === item[0] ? 'active' : '') + '">' +
        '<span class="dashicons ' + item[1] + '"></span>' + A.esc(A.t(item[2])) + '</a>';
    });

    root.innerHTML =
      '<div class="aiwc-layout">' +
      '  <aside class="aiwc-sidebar">' +
      '    <div class="aiwc-logo"><div class="aiwc-logo-badge">AI</div>' +
      '      <div class="aiwc-logo-text">' + A.esc(A.t('app_title')) + '<small>v' + A.esc(A.version) + '</small></div></div>' +
      '    <nav class="aiwc-nav">' + nav + '</nav>' +
      '  </aside>' +
      '  <main class="aiwc-main">' +
      '    <div class="aiwc-topbar">' +
      '      <h1>' + A.esc(A.t(routeTitles[currentRoute] || 'dashboard')) + '</h1>' +
      '      <div class="aiwc-topbar-actions">' +
      '        <button class="aiwc-btn sm" id="aiwc-lang">' + (A.language === 'fa' ? 'English' : 'فارسی') + '</button>' +
      '        <button class="aiwc-btn sm" id="aiwc-theme">' + A.esc(A.t('theme_toggle')) + '</button>' +
      '      </div>' +
      '    </div>' +
      '    <div id="aiwc-page"></div>' +
      '  </main>' +
      '</div>';

    root.querySelectorAll('.aiwc-nav a').forEach(function (a) {
      a.addEventListener('click', function () {
        go(a.dataset.route);
      });
    });

    document.getElementById('aiwc-lang').addEventListener('click', function () {
      var next = A.language === 'fa' ? 'en' : 'fa';
      A.api('settings', {
        method: 'POST',
        body: { ui_language: next }
      }).then(function () {
        window.location.reload();
      });
    });

    document.getElementById('aiwc-theme').addEventListener('click', function () {
      var next = A.theme === 'dark' ? 'light' : 'dark';
      A.theme = next;
      root.setAttribute('data-theme', next);
      A.api('settings', { method: 'POST', body: { ui_theme: next } }).catch(function () {});
    });

    var page = document.getElementById('aiwc-page');
    try {
      routes[currentRoute](page);
    } catch (e) {
      page.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(e.message) + '</div></div>';
    }
  }

  /* ================= Dashboard ================= */
  function renderDashboard(c) {
    c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
    A.api('stats').then(function (data) {
      var o = data.overview || {};
      var counts = o.counts || {};
      var html =
        '<div class="aiwc-grid cols-4">' +
        stat(counts.pages, A.t('pages')) +
        stat(counts.posts, A.t('posts')) +
        stat(counts.users, A.t('users')) +
        stat(data.total_logs, A.t('logs')) +
        '</div>' +
        '<div class="aiwc-grid cols-2" style="margin-top:16px">' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('system_status')) + '</h2>' +
        kv(A.t('model_label'), A.esc(data.model || '-')) +
        kv(A.t('api'), data.configured ? '<span class="aiwc-badge ok">' + A.esc(A.t('configured')) + '</span>' : '<span class="aiwc-badge err">' + A.esc(A.t('not_configured')) + '</span>') +
        kv(A.t('theme'), A.esc((o.theme && o.theme.name) || '-')) +
        kv(A.t('execution_mode_label'), A.esc(A.t('mode_' + (data.execution_mode || 2)))) +
        (data.pending_approvals ? kv(A.t('pending_approval'), '<span class="aiwc-badge warn">' + data.pending_approvals + '</span>') : '') +
        (o.woocommerce ? kv('WooCommerce', '<span class="aiwc-badge ok">active</span>') : '') +
        (o.elementor ? kv('Elementor', '<span class="aiwc-badge ok">active</span>') : '') +
        (o.yoast ? kv('Yoast SEO', '<span class="aiwc-badge ok">active</span>') : '') +
        (o.rank_math ? kv('Rank Math', '<span class="aiwc-badge ok">active</span>') : '') +
        '</div>' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('quick_actions')) + '</h2>' +
        '<div style="display:flex;flex-wrap:wrap;gap:10px">' +
        '<button class="aiwc-btn primary" data-go="chat">' + A.esc(A.t('chat')) + '</button>' +
        '<button class="aiwc-btn" data-go="seo">' + A.esc(A.t('run_analysis')) + '</button>' +
        '<button class="aiwc-btn" data-go="content">' + A.esc(A.t('content')) + '</button>' +
        '<button class="aiwc-btn" data-go="settings">' + A.esc(A.t('go_settings')) + '</button>' +
        '</div>' +
        (!data.configured ? '<p style="margin-top:12px;color:var(--aiwc-warn);font-size:12.5px">' + A.esc(A.t('api_not_ready')) + '</p>' : '') +
        '</div></div>' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('recent_activity')) + '</h2>' + logsTable(data.recent_logs || [], true) + '</div>';
      c.innerHTML = html;

      c.querySelectorAll('[data-go]').forEach(function (b) {
        b.addEventListener('click', function () { go(b.dataset.go); });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  function stat(num, label) {
    return '<div class="aiwc-stat"><div class="num">' + A.fmtNum(num || 0) + '</div><div class="lbl">' + A.esc(label) + '</div></div>';
  }

  function kv(k, v) {
    return '<div class="aiwc-kv"><span class="k">' + A.esc(k) + '</span><span class="v">' + v + '</span></div>';
  }

  function logsTable(items, compact) {
    if (!items.length) {
      return '<div class="aiwc-empty">' + A.esc(A.t('no_items')) + '</div>';
    }
    var html = '<table class="aiwc-table"><thead><tr>' +
      '<th>' + A.esc(A.t('time')) + '</th><th>' + A.esc(A.t('tool')) + '</th><th>' + A.esc(A.t('command')) + '</th><th>' + A.esc(A.t('status')) + '</th>' +
      (compact ? '' : '<th>' + A.esc(A.t('actions')) + '</th>') +
      '</tr></thead><tbody>';
    items.forEach(function (row) {
      html += '<tr>' +
        '<td style="white-space:nowrap">' + A.esc(A.fmtDate(row.created_at)) + '</td>' +
        '<td><span class="aiwc-badge info" style="direction:ltr">' + A.esc(row.tool_name || '-') + '</span></td>' +
        '<td style="max-width:280px;overflow:hidden;text-overflow:ellipsis">' + A.esc((row.summary || row.command || '').slice(0, 80)) + '</td>' +
        '<td>' + A.statusBadge(row.status) + '</td>' +
        (compact ? '' : '<td><button class="aiwc-btn sm" data-log="' + row.id + '">' + A.esc(A.t('details')) + '</button></td>') +
        '</tr>';
    });
    html += '</tbody></table>';
    return html;
  }

  /* ================= Tools ================= */
  function renderTools(c) {
    c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
    A.api('tools').then(function (data) {
      var groups = {};
      (data.items || []).forEach(function (tool) {
        var prefix = tool.name.split('_')[0];
        if (!groups[prefix]) groups[prefix] = [];
        groups[prefix].push(tool);
      });

      var html = '<div class="aiwc-card"><h2>' + A.esc(A.t('tools')) + '</h2>';
      Object.keys(groups).forEach(function (g) {
        html += '<h3 style="margin:18px 0 6px;text-transform:uppercase;font-size:11px;letter-spacing:1px;color:var(--aiwc-text-2)">' + A.esc(g) + '</h3>';
        groups[g].forEach(function (tool) {
          html += '<div class="aiwc-tool-row">' +
            '<div style="flex:1;min-width:0">' +
            '<div class="aiwc-tool-name">' + A.esc(tool.name) + ' ' + A.riskBadge(tool.risk) + '</div>' +
            '<div class="aiwc-tool-desc">' + A.esc(tool.description) + '</div>' +
            '</div>' +
            '<label class="aiwc-switch"><input type="checkbox" data-tool="' + A.esc(tool.name) + '"' + (tool.enabled ? ' checked' : '') + '><span class="slider"></span></label>' +
            '</div>';
        });
      });
      html += '</div>';
      c.innerHTML = html;

      c.querySelectorAll('[data-tool]').forEach(function (input) {
        input.addEventListener('change', function () {
          A.api('tools/' + input.dataset.tool, {
            method: 'POST',
            body: { enabled: input.checked }
          }).then(function () {
            A.toast(input.checked ? A.t('tool_enabled') : A.t('tool_disabled'));
          }).catch(function (err) {
            input.checked = !input.checked;
            A.toast(err.message, true);
          });
        });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  /* ================= Design ================= */
  function renderDesign(c) {
    c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
    Promise.all([
      A.api('design/css'),
      A.api('site/context')
    ]).then(function (results) {
      var css = results[0].css || '';
      var ctx = results[1] || {};
      var structure = ctx.structure || {};
      var overview = ctx.overview || {};

      var menusHtml = '';
      (structure.menus || []).forEach(function (menu) {
        var items = (menu.items || []).map(function (i) {
          return '<li>' + A.esc(i.title) + ' <span style="color:var(--aiwc-text-2);font-size:11px;direction:ltr;display:inline-block">' + A.esc(i.url) + '</span></li>';
        }).join('');
        menusHtml += '<div class="aiwc-issue low"><strong>' + A.esc(menu.name) + '</strong><ul style="margin:6px 0 0;padding-inline-start:20px;font-size:12px">' + items + '</ul></div>';
      });

      c.innerHTML =
        '<div class="aiwc-grid cols-2">' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('custom_css')) + '</h2>' +
        '<div class="aiwc-field"><textarea id="aiwc-css" style="min-height:260px">' + A.esc(css) + '</textarea>' +
        '<div class="hint">' + A.esc(A.t('site_design_desc')) + '</div></div>' +
        '<button class="aiwc-btn primary" id="aiwc-save-css">' + A.esc(A.t('save')) + '</button> ' +
        '<button class="aiwc-btn" id="aiwc-append-css">' + A.esc(A.t('copy')) + '</button>' +
        '</div>' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('site_overview')) + '</h2>' +
        kv(A.t('theme'), A.esc((overview.theme && overview.theme.name) || '-') + ((overview.theme && overview.theme.block_theme) ? ' <span class="aiwc-badge info">block</span>' : '')) +
        kv('Elementor', overview.elementor ? '<span class="aiwc-badge ok">active</span>' : '<span class="aiwc-badge muted">-</span>') +
        '<h3 style="margin-top:16px">' + A.esc(A.t('manage')) + ' — Menus</h3>' +
        (menusHtml || '<div class="aiwc-empty">' + A.esc(A.t('no_items')) + '</div>') +
        '</div></div>';

      document.getElementById('aiwc-save-css').addEventListener('click', function () {
        A.api('design/css', {
          method: 'POST',
          body: { css: document.getElementById('aiwc-css').value, mode: 'replace' }
        }).then(function (res) {
          A.toast(res.summary || A.t('saved'));
        }).catch(function (err) { A.toast(err.message, true); });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  /* ================= SEO ================= */
  function renderSeo(c) {
    c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
    A.api('seo/report').then(function (report) {
      var html =
        '<div class="aiwc-grid cols-2">' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('seo')) + ' — ' + A.esc(A.t('site_overview')) + '</h2>';

      if (!report.available) {
        html += '<div class="aiwc-empty">' + A.esc(report.message || A.t('no_items')) + '</div>';
      } else {
        var avg = report.average_score || 0;
        var cls = avg >= 75 ? 'good' : (avg >= 50 ? 'mid' : 'bad');
        html += '<div style="display:flex;gap:18px;align-items:center">' +
          '<div class="aiwc-score ' + cls + '">' + avg + '</div>' +
          '<div>' +
          '<div style="font-size:13px;color:var(--aiwc-text-2)">' + A.esc(A.t('seo_score')) + ' (' + A.esc(A.t('of')) + ' 100)</div>' +
          '<div style="margin-top:8px">' + A.esc(A.t('pages')) + ': ' + A.fmtNum(report.processed || 0) + ' / ' + A.fmtNum(report.total || 0) + '</div>' +
          '</div></div>';

        if (report.items && report.items.length) {
          html += '<table class="aiwc-table" style="margin-top:14px"><thead><tr><th>' + A.esc(A.t('title')) + '</th><th>' + A.esc(A.t('seo_score')) + '</th><th>' + A.esc(A.t('issues')) + '</th></tr></thead><tbody>';
          report.items.slice(0, 15).forEach(function (item) {
            html += '<tr><td>' + A.esc(item.title) + '</td>' +
              '<td><span class="aiwc-badge ' + (item.score >= 75 ? 'ok' : (item.score >= 50 ? 'warn' : 'err')) + '">' + item.score + '</span></td>' +
              '<td>' + A.esc((item.top_issues || []).join(', ') || '-') + '</td></tr>';
          });
          html += '</tbody></table>';
        }
      }
      html += '<button class="aiwc-btn primary" id="aiwc-seo-site" style="margin-top:14px">' + A.esc(A.t('run_analysis')) + '</button></div>';

      html += '<div class="aiwc-card"><h2>' + A.esc(A.t('seo')) + ' — ' + A.esc(A.t('page')) + '</h2>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('page')) + ' ID</label><input type="number" id="aiwc-seo-post" min="1"></div>' +
        '<button class="aiwc-btn primary" id="aiwc-seo-run">' + A.esc(A.t('run_analysis')) + '</button>' +
        '<div id="aiwc-seo-result" style="margin-top:14px"></div></div></div>';

      c.innerHTML = html;

      document.getElementById('aiwc-seo-site').addEventListener('click', function () {
        var btn = this;
        btn.disabled = true;
        A.api('seo/analyze-site', { method: 'POST' }).then(function (res) {
          A.toast(A.t('operation_queued') + ' #' + res.job_id);
          btn.disabled = false;
        }).catch(function (err) {
          btn.disabled = false;
          A.toast(err.message, true);
        });
      });

      document.getElementById('aiwc-seo-run').addEventListener('click', function () {
        var id = parseInt(document.getElementById('aiwc-seo-post').value, 10);
        if (!id) { A.toast(A.t('required_field'), true); return; }
        var box = document.getElementById('aiwc-seo-result');
        box.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div>';
        A.api('seo/analyze', { method: 'POST', body: { post_id: id } }).then(function (res) {
          var cls = res.score >= 75 ? 'good' : (res.score >= 50 ? 'mid' : 'bad');
          var issues = (res.issues || []).map(function (i) {
            return '<div class="aiwc-issue ' + i.severity + '"><strong>' + A.esc(i.message) + '</strong>' +
              '<div class="fix">' + A.esc(A.t('fix')) + ': ' + A.esc(i.fix) + '</div></div>';
          }).join('');
          box.innerHTML = '<div style="display:flex;gap:14px;align-items:center"><div class="aiwc-score ' + cls + '">' + res.score + '</div>' +
            '<div><strong>' + A.esc(res.title) + '</strong><div style="color:var(--aiwc-text-2);font-size:12px;direction:ltr">' + A.esc(res.url) + '</div></div></div>' + issues;
        }).catch(function (err) {
          box.innerHTML = '<div class="aiwc-empty">' + A.esc(err.message) + '</div>';
        });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  /* ================= Content ================= */
  function renderContent(c) {
    var state = { type: 'page', search: '', page: 1, pages: 1 };

    function load() {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
      A.api('content?type=' + state.type + '&search=' + encodeURIComponent(state.search) + '&page=' + state.page + '&per_page=10').then(function (data) {
        state.pages = data.pages || 1;
        var rows = (data.items || []).map(function (item) {
          return '<tr>' +
            '<td><strong>' + A.esc(item.title) + '</strong><div style="font-size:11px;color:var(--aiwc-text-2);direction:ltr">' + A.esc(item.url) + '</div></td>' +
            '<td><span class="aiwc-badge muted">' + A.esc(item.type) + '</span></td>' +
            '<td>' + A.statusBadge(item.status) + '</td>' +
            '<td>' + A.fmtNum(item.word_count || 0) + '</td>' +
            '<td style="white-space:nowrap">' +
            '<a class="aiwc-btn sm" href="' + A.esc(item.url) + '" target="_blank">' + A.esc(A.t('view')) + '</a> ' +
            '<button class="aiwc-btn sm" data-seo="' + item.id + '">' + A.esc(A.t('seo_score')) + '</button>' +
            '</td></tr>';
        }).join('');

        c.innerHTML = '<div class="aiwc-card">' +
          '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">' +
          '<select id="aiwc-ctype" style="padding:8px;border-radius:8px;background:var(--aiwc-bg);color:var(--aiwc-text);border:1px solid var(--aiwc-border)">' +
          '<option value="page"' + (state.type === 'page' ? ' selected' : '') + '>' + A.esc(A.t('pages')) + '</option>' +
          '<option value="post"' + (state.type === 'post' ? ' selected' : '') + '>' + A.esc(A.t('posts')) + '</option>' +
          '</select>' +
          '<input id="aiwc-csearch" type="text" placeholder="' + A.esc(A.t('search_placeholder')) + '" value="' + A.esc(state.search) + '" style="flex:1;min-width:180px;padding:8px 12px;border-radius:8px;background:var(--aiwc-bg);color:var(--aiwc-text);border:1px solid var(--aiwc-border)">' +
          '<button class="aiwc-btn primary" id="aiwc-cgo">' + A.esc(A.t('search')) + '</button>' +
          '</div>' +
          '<table class="aiwc-table"><thead><tr><th>' + A.esc(A.t('title')) + '</th><th>' + A.esc(A.t('category')) + '</th><th>' + A.esc(A.t('status')) + '</th><th>Words</th><th>' + A.esc(A.t('actions')) + '</th></tr></thead>' +
          '<tbody>' + (rows || '<tr><td colspan="5"><div class="aiwc-empty">' + A.esc(A.t('no_items')) + '</div></td></tr>') + '</tbody></table>' +
          '<div class="aiwc-pagination">' +
          '<button class="aiwc-btn sm" id="aiwc-cprev"' + (state.page <= 1 ? ' disabled' : '') + '>' + A.esc(A.t('prev')) + '</button>' +
          '<span>' + A.fmtNum(state.page) + ' ' + A.esc(A.t('of')) + ' ' + A.fmtNum(state.pages) + '</span>' +
          '<button class="aiwc-btn sm" id="aiwc-cnext"' + (state.page >= state.pages ? ' disabled' : '') + '>' + A.esc(A.t('next')) + '</button>' +
          '</div>' +
          '<div id="aiwc-cseo" style="margin-top:14px"></div>' +
          '</div>';

        document.getElementById('aiwc-cgo').addEventListener('click', function () {
          state.search = document.getElementById('aiwc-csearch').value;
          state.type = document.getElementById('aiwc-ctype').value;
          state.page = 1;
          load();
        });
        document.getElementById('aiwc-cprev').addEventListener('click', function () { state.page--; load(); });
        document.getElementById('aiwc-cnext').addEventListener('click', function () { state.page++; load(); });

        c.querySelectorAll('[data-seo]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var box = document.getElementById('aiwc-cseo');
            box.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div>';
            A.api('seo/analyze', { method: 'POST', body: { post_id: parseInt(btn.dataset.seo, 10) } }).then(function (res) {
              box.innerHTML = '<div class="aiwc-issue ' + (res.score >= 75 ? 'low' : 'medium') + '"><strong>' + A.esc(res.title) + ' — ' + A.esc(A.t('seo_score')) + ': ' + res.score + '</strong>' +
                '<div class="fix">' + A.esc((res.issues || []).map(function (i) { return i.message; }).join(' | ') || A.t('success')) + '</div></div>';
            }).catch(function (err) { box.innerHTML = '<div class="aiwc-empty">' + A.esc(err.message) + '</div>'; });
          });
        });
      }).catch(function (err) {
        c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
      });
    }
    load();
  }

  /* ================= Logs ================= */
  function renderLogs(c) {
    var state = { page: 1, status: '', tool: '', search: '' };

    function load() {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
      var qs = 'page=' + state.page + '&per_page=15' +
        (state.status ? '&status=' + state.status : '') +
        (state.tool ? '&tool_name=' + encodeURIComponent(state.tool) : '') +
        (state.search ? '&search=' + encodeURIComponent(state.search) : '');

      Promise.all([A.api('logs?' + qs), A.api('logs/filters')]).then(function (res) {
        var data = res[0];
        var tools = res[1].tools || [];
        var pages = data.pages || 1;

        var toolOpts = tools.map(function (t) {
          return '<option value="' + A.esc(t) + '"' + (state.tool === t ? ' selected' : '') + '>' + A.esc(t) + '</option>';
        }).join('');

        c.innerHTML = '<div class="aiwc-card">' +
          '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px">' +
          '<select id="aiwc-lstatus" style="padding:8px;border-radius:8px;background:var(--aiwc-bg);color:var(--aiwc-text);border:1px solid var(--aiwc-border)">' +
          '<option value="">' + A.esc(A.t('all')) + '</option>' +
          ['success', 'failed', 'pending', 'rejected'].map(function (s) {
            return '<option value="' + s + '"' + (state.status === s ? ' selected' : '') + '>' + s + '</option>';
          }).join('') + '</select>' +
          '<select id="aiwc-ltool" style="padding:8px;border-radius:8px;background:var(--aiwc-bg);color:var(--aiwc-text);border:1px solid var(--aiwc-border)">' +
          '<option value="">' + A.esc(A.t('all')) + '</option>' + toolOpts + '</select>' +
          '<input id="aiwc-lsearch" type="text" placeholder="' + A.esc(A.t('search_placeholder')) + '" value="' + A.esc(state.search) + '" style="flex:1;min-width:160px;padding:8px 12px;border-radius:8px;background:var(--aiwc-bg);color:var(--aiwc-text);border:1px solid var(--aiwc-border)">' +
          '<button class="aiwc-btn primary" id="aiwc-lgo">' + A.esc(A.t('filter')) + '</button>' +
          '</div>' +
          logsTable(data.items || [], false) +
          '<div class="aiwc-pagination">' +
          '<button class="aiwc-btn sm" id="aiwc-lprev"' + (state.page <= 1 ? ' disabled' : '') + '>' + A.esc(A.t('prev')) + '</button>' +
          '<span>' + A.fmtNum(state.page) + ' ' + A.esc(A.t('of')) + ' ' + A.fmtNum(pages) + '</span>' +
          '<button class="aiwc-btn sm" id="aiwc-lnext"' + (state.page >= pages ? ' disabled' : '') + '>' + A.esc(A.t('next')) + '</button>' +
          '</div>' +
          '<div id="aiwc-ldetail"></div></div>';

        document.getElementById('aiwc-lgo').addEventListener('click', function () {
          state.status = document.getElementById('aiwc-lstatus').value;
          state.tool = document.getElementById('aiwc-ltool').value;
          state.search = document.getElementById('aiwc-lsearch').value;
          state.page = 1;
          load();
        });
        document.getElementById('aiwc-lprev').addEventListener('click', function () { state.page--; load(); });
        document.getElementById('aiwc-lnext').addEventListener('click', function () { state.page++; load(); });

        c.querySelectorAll('[data-log]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            var box = document.getElementById('aiwc-ldetail');
            box.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div>';
            A.api('logs/' + btn.dataset.log).then(function (row) {
              box.innerHTML = '<div class="aiwc-card" style="margin-top:14px"><h2>' + A.esc(A.t('details')) + ' #' + row.id + '</h2>' +
                kv(A.t('time'), A.esc(A.fmtDate(row.created_at))) +
                kv(A.t('tool'), '<span style="direction:ltr;font-family:monospace">' + A.esc(row.tool_name) + '</span>') +
                kv(A.t('command'), A.esc(row.command || '-')) +
                kv(A.t('result'), A.esc(row.summary || '-')) +
                kv(A.t('status'), A.statusBadge(row.status) + ' ' + (row.approval ? A.statusBadge(row.approval) : '')) +
                (row.error ? kv(A.t('error'), A.esc(row.error)) : '') +
                '<h3 style="margin-top:14px">' + A.esc(A.t('before_change')) + '</h3><div class="aiwc-mono">' + A.esc(JSON.stringify(row.before_state, null, 2) || '-') + '</div>' +
                '<h3 style="margin-top:14px">' + A.esc(A.t('after_change')) + '</h3><div class="aiwc-mono">' + A.esc(JSON.stringify(row.after_state, null, 2) || '-') + '</div>' +
                '<div style="margin-top:14px;display:flex;gap:10px">' +
                (row.status === 'success' ? '<button class="aiwc-btn danger" id="aiwc-restore">' + A.esc(A.t('rollback')) + '</button>' : '') +
                '<button class="aiwc-btn" id="aiwc-ldetail-close">' + A.esc(A.t('cancel')) + '</button>' +
                '</div></div>';

              var closeBtn = document.getElementById('aiwc-ldetail-close');
              if (closeBtn) closeBtn.addEventListener('click', function () { box.innerHTML = ''; });
              var restoreBtn = document.getElementById('aiwc-restore');
              if (restoreBtn) {
                restoreBtn.addEventListener('click', function () {
                  if (!confirm(A.t('confirm_delete'))) return;
                  restoreBtn.disabled = true;
                  A.api('logs/' + row.id + '/restore', { method: 'POST' }).then(function () {
                    A.toast(A.t('rollback_done'));
                    box.innerHTML = '';
                  }).catch(function (err) {
                    restoreBtn.disabled = false;
                    A.toast(err.message, true);
                  });
                });
              }
            }).catch(function (err) { box.innerHTML = '<div class="aiwc-empty">' + A.esc(err.message) + '</div>'; });
          });
        });
      }).catch(function (err) {
        c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
      });
    }
    load();
  }

  /* ================= Memory ================= */
  function renderMemory(c) {
    function load() {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div></div>';
      A.api('memory').then(function (data) {
        var rows = (data.items || []).map(function (m) {
          return '<tr>' +
            '<td><span class="aiwc-badge info">' + A.esc(m.category) + '</span></td>' +
            '<td style="direction:ltr;font-family:monospace;font-size:12px">' + A.esc(m.memory_key) + '</td>' +
            '<td>' + A.esc(m.memory_value) + '</td>' +
            '<td>' + A.esc(A.fmtDate(m.updated_at)) + '</td>' +
            '<td><button class="aiwc-btn danger sm" data-forget="' + m.id + '">' + A.esc(A.t('delete')) + '</button></td>' +
            '</tr>';
        }).join('');

        c.innerHTML = '<div class="aiwc-card">' +
          '<h2>' + A.esc(A.t('memory_title')) + '</h2>' +
          '<p style="color:var(--aiwc-text-2);font-size:12.5px">' + A.esc(A.t('memory_desc')) + '</p>' +
          '<table class="aiwc-table"><thead><tr><th>' + A.esc(A.t('memory_category')) + '</th><th>' + A.esc(A.t('memory_key')) + '</th><th>' + A.esc(A.t('memory_value')) + '</th><th>' + A.esc(A.t('time')) + '</th><th></th></tr></thead>' +
          '<tbody>' + (rows || '<tr><td colspan="5"><div class="aiwc-empty">' + A.esc(A.t('no_items')) + '</div></td></tr>') + '</tbody></table>' +
          '<h3 style="margin-top:18px">' + A.esc(A.t('memory_add')) + '</h3>' +
          '<div class="aiwc-grid cols-3">' +
          '<div class="aiwc-field"><label>' + A.esc(A.t('memory_category')) + '</label><select id="aiwc-mcat">' +
          ['brand', 'design', 'instruction', 'structure', 'general'].map(function (x) {
            return '<option value="' + x + '">' + x + '</option>';
          }).join('') + '</select></div>' +
          '<div class="aiwc-field"><label>' + A.esc(A.t('memory_key')) + '</label><input type="text" id="aiwc-mkey"></div>' +
          '<div class="aiwc-field"><label>' + A.esc(A.t('memory_value')) + '</label><input type="text" id="aiwc-mval"></div>' +
          '</div>' +
          '<button class="aiwc-btn primary" id="aiwc-msave">' + A.esc(A.t('save')) + '</button></div>';

        document.getElementById('aiwc-msave').addEventListener('click', function () {
          var key = document.getElementById('aiwc-mkey').value.trim();
          var val = document.getElementById('aiwc-mval').value.trim();
          if (!key || !val) { A.toast(A.t('required_field'), true); return; }
          A.api('memory', {
            method: 'POST',
            body: {
              category: document.getElementById('aiwc-mcat').value,
              memory_key: key,
              memory_value: val
            }
          }).then(function () {
            A.toast(A.t('saved'));
            load();
          }).catch(function (err) { A.toast(err.message, true); });
        });

        c.querySelectorAll('[data-forget]').forEach(function (btn) {
          btn.addEventListener('click', function () {
            if (!confirm(A.t('confirm_delete'))) return;
            A.api('memory/' + btn.dataset.forget, { method: 'DELETE' }).then(function () {
              A.toast(A.t('deleted'));
              load();
            }).catch(function (err) { A.toast(err.message, true); });
          });
        });
      }).catch(function (err) {
        c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
      });
    }
    load();
  }

  /* ================= Settings ================= */
  function renderSettings(c) {
    A.api('settings').then(function (s) {
      var ranges = [
        ['analysis_strictness', A.t('strictness_label'), 1, 5],
        ['creativity', A.t('creativity_label'), 1, 5],
        ['autonomy_level', A.t('autonomy_label'), 1, 5],
        ['context_detail', A.t('context_label'), 1, 5]
      ];
      var rangeHtml = ranges.map(function (r) {
        return '<div class="aiwc-field"><label>' + A.esc(r[1]) + '</label><div class="aiwc-range-row">' +
          '<input type="range" min="' + r[2] + '" max="' + r[3] + '" value="' + (s[r[0]] || 3) + '" data-range="' + r[0] + '">' +
          '<span class="aiwc-range-val">' + (s[r[0]] || 3) + '</span></div></div>';
      }).join('');

      c.innerHTML = '<div class="aiwc-grid cols-2">' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('settings')) + '</h2>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('max_tokens_label')) + '</label><input type="number" id="s-max-tokens" value="' + (s.max_output_tokens || 2048) + '"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('timeout_label')) + '</label><input type="number" id="s-timeout" value="' + (s.timeout || 60) + '"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('temperature_label')) + ' (' + A.esc(A.t('creativity_label')) + ' — sampling)</label><div class="aiwc-range-row">' +
        '<input type="range" min="0" max="2" step="0.1" value="' + (s.temperature || 0.7) + '" data-range="temperature"><span class="aiwc-range-val">' + (s.temperature || 0.7) + '</span></div>' +
        '<div class="hint">' + A.esc(A.t('strictness_label')) + ' ≠ Temperature — این دو مستقل مدیریت می‌شوند.</div></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('top_p_label')) + '</label><div class="aiwc-range-row">' +
        '<input type="range" min="0" max="1" step="0.05" value="' + (s.top_p || 1) + '" data-range="top_p"><span class="aiwc-range-val">' + (s.top_p || 1) + '</span></div></div>' +
        rangeHtml +
        '<div class="aiwc-field"><label>' + A.esc(A.t('max_steps_label')) + '</label><input type="number" id="s-max-steps" value="' + (s.max_steps || 8) + '"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('max_tools_label')) + '</label><input type="number" id="s-max-tools" value="' + (s.max_tools_per_request || 8) + '"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('context_budget_label')) + '</label><input type="number" id="s-budget" value="' + (s.context_token_budget || 8000) + '"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('execution_mode_label')) + '</label><select id="s-mode">' +
        [1, 2, 3, 4].map(function (m) {
          return '<option value="' + m + '"' + ((s.execution_mode || 2) == m ? ' selected' : '') + '>' + A.esc(A.t('mode_' + m)) + '</option>';
        }).join('') + '</select></div>' +
        '<button class="aiwc-btn primary" id="s-save">' + A.esc(A.t('save')) + '</button>' +
        '</div>' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('execution_mode_label')) + '</h2>' +
        '<div class="aiwc-issue low"><strong>1. ' + A.esc(A.t('mode_1')) + '</strong><div class="fix">ابزارهای تغییردهنده در مدل نمایش داده نمی‌شوند.</div></div>' +
        '<div class="aiwc-issue low"><strong>2. ' + A.esc(A.t('mode_2')) + '</strong><div class="fix">هر تغییر در صف تأیید شما قرار می‌گیرد.</div></div>' +
        '<div class="aiwc-issue low"><strong>3. ' + A.esc(A.t('mode_3')) + '</strong><div class="fix">تغییرات کم‌خطر خودکار؛ عملیات حذفی نیازمند تأیید.</div></div>' +
        '<div class="aiwc-issue low"><strong>4. ' + A.esc(A.t('mode_4')) + '</strong><div class="fix">هر مرحله به‌صورت جداگانه تأیید می‌شود.</div></div>' +
        '</div></div>';

      c.querySelectorAll('[data-range]').forEach(function (input) {
        input.addEventListener('input', function () {
          input.parentElement.querySelector('.aiwc-range-val').textContent = input.value;
        });
      });

      document.getElementById('s-save').addEventListener('click', function () {
        var body = {
          max_output_tokens: parseInt(document.getElementById('s-max-tokens').value, 10),
          timeout: parseInt(document.getElementById('s-timeout').value, 10),
          max_steps: parseInt(document.getElementById('s-max-steps').value, 10),
          max_tools_per_request: parseInt(document.getElementById('s-max-tools').value, 10),
          context_token_budget: parseInt(document.getElementById('s-budget').value, 10),
          execution_mode: parseInt(document.getElementById('s-mode').value, 10)
        };
        c.querySelectorAll('[data-range]').forEach(function (input) {
          var key = input.dataset.range;
          body[key] = key === 'temperature' || key === 'top_p' ? parseFloat(input.value) : parseInt(input.value, 10);
        });
        A.api('settings', { method: 'POST', body: body }).then(function () {
          A.toast(A.t('saved'));
        }).catch(function (err) { A.toast(err.message, true); });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  /* ================= API connection ================= */
  function renderApi(c) {
    A.api('settings').then(function (s) {
      c.innerHTML = '<div class="aiwc-grid cols-2">' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('api')) + '</h2>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('api_key_label')) + '</label>' +
        '<input type="password" id="a-key" value="" placeholder="' + (s.api_key_set ? A.esc(s.api_key) : 'sk-...') + '">' +
        '<div class="hint">' + (s.api_key_set ? '✓ ' + A.esc(A.t('configured')) + ' — برای تغییر مقدار جدید وارد کنید' : '') + '</div></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('base_url_label')) + '</label><input type="text" id="a-base" value="' + A.esc(s.base_url || '') + '" dir="ltr" style="text-align:left">' +
        '<div class="hint">OpenAI-compatible: https://api.example.com/v1</div></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('model_label2')) + '</label><input type="text" id="a-model" value="' + A.esc(s.model || '') + '" dir="ltr" style="text-align:left"></div>' +
        '<div class="aiwc-field"><label>' + A.esc(A.t('retries_label')) + '</label><input type="number" id="a-retries" value="' + (s.max_retries || 2) + '"></div>' +
        '<div style="display:flex;gap:10px;flex-wrap:wrap">' +
        '<button class="aiwc-btn primary" id="a-save">' + A.esc(A.t('save')) + '</button>' +
        '<button class="aiwc-btn" id="a-test">' + A.esc(A.t('test_connection')) + '</button>' +
        '<button class="aiwc-btn" id="a-models">' + A.esc(A.t('model_label2')) + ' ←</button>' +
        '</div>' +
        '<div id="a-result" style="margin-top:14px"></div></div>' +
        '<div class="aiwc-card"><h2>' + A.esc(A.t('system_status')) + '</h2>' +
        kv(A.t('api'), s.api_key_set ? '<span class="aiwc-badge ok">' + A.esc(A.t('configured')) + '</span>' : '<span class="aiwc-badge err">' + A.esc(A.t('not_configured')) + '</span>') +
        kv(A.t('base_url_label'), '<span style="direction:ltr;display:inline-block">' + A.esc(s.base_url || '-') + '</span>') +
        kv(A.t('model_label2'), '<span style="direction:ltr;display:inline-block">' + A.esc(s.model || '-') + '</span>') +
        '<p class="hint" style="margin-top:14px">کلید API هرگز در فرانت‌اند یا گزارش‌ها نمایش داده نمی‌شود و فقط روی سرور ذخیره می‌گردد.</p>' +
        '</div></div>';

      function collect() {
        return {
          api_key: document.getElementById('a-key').value,
          base_url: document.getElementById('a-base').value,
          model: document.getElementById('a-model').value,
          max_retries: parseInt(document.getElementById('a-retries').value, 10)
        };
      }

      document.getElementById('a-save').addEventListener('click', function () {
        A.api('settings', { method: 'POST', body: collect() }).then(function () {
          A.toast(A.t('saved'));
          renderApi(c);
        }).catch(function (err) { A.toast(err.message, true); });
      });

      document.getElementById('a-test').addEventListener('click', function () {
        var btn = this;
        var box = document.getElementById('a-result');
        btn.disabled = true;
        box.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('testing')) + '</div>';
        A.api('settings', { method: 'POST', body: collect() }).then(function () {
          return A.api('settings/test', { method: 'POST' });
        }).then(function (res) {
          btn.disabled = false;
          box.innerHTML = '<div class="aiwc-issue ' + (res.ok ? 'low' : 'high') + '"><strong>' +
            (res.ok ? A.esc(A.t('connection_ok')) : A.esc(A.t('connection_fail'))) + '</strong>' +
            '<div class="fix">' + A.esc(res.message || '') + ' (' + A.fmtNum(res.latency_ms || 0) + 'ms)</div></div>';
        }).catch(function (err) {
          btn.disabled = false;
          box.innerHTML = '<div class="aiwc-issue high"><strong>' + A.esc(A.t('connection_fail')) + '</strong><div class="fix">' + A.esc(err.message) + '</div></div>';
        });
      });

      document.getElementById('a-models').addEventListener('click', function () {
        var box = document.getElementById('a-result');
        box.innerHTML = '<div class="aiwc-empty">' + A.esc(A.t('loading')) + '</div>';
        A.api('models').then(function (res) {
          var list = (res.models || []).slice(0, 40).map(function (m) {
            return '<button class="aiwc-btn sm" data-model="' + A.esc(m) + '" style="margin:3px" dir="ltr">' + A.esc(m) + '</button>';
          }).join('');
          box.innerHTML = '<div>' + (list || A.esc(A.t('no_items'))) + '</div>';
          box.querySelectorAll('[data-model]').forEach(function (b) {
            b.addEventListener('click', function () {
              document.getElementById('a-model').value = b.dataset.model;
            });
          });
        }).catch(function (err) {
          box.innerHTML = '<div class="aiwc-issue high">' + A.esc(err.message) + '</div>';
        });
      });
    }).catch(function (err) {
      c.innerHTML = '<div class="aiwc-card"><div class="aiwc-empty">' + A.esc(err.message) + '</div></div>';
    });
  }

  /* ================= Boot ================= */
  function boot() {
    var root = document.getElementById('aiwc-app');
    if (!root) return;
    var page = (A.route || 'aiwc-dashboard').replace(/^aiwc-/, '');
    // Map slugs to routes.
    var map = {
      dashboard: 'dashboard',
      chat: 'chat',
      tools: 'tools',
      design: 'design',
      seo: 'seo',
      content: 'content',
      logs: 'logs',
      memory: 'memory',
      api: 'api',
      settings: 'settings'
    };
    go(map[page] || 'dashboard');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})(window);
