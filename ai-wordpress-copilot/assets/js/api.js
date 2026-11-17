/**
 * AIWC REST API client + shared UI helpers.
 */
(function (global) {
  'use strict';

  var cfg = global.AIWC || {};

  function t(key) {
    return (cfg.i18n && cfg.i18n[key]) || key;
  }

  function api(path, options) {
    options = options || {};
    var method = options.method || 'GET';
    var url = cfg.root.replace(/\/$/, '') + '/' + path.replace(/^\//, '');
    var fetchOpts = {
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'X-WP-Nonce': cfg.nonce
      },
      credentials: 'same-origin'
    };
    if (options.body !== undefined) {
      fetchOpts.body = JSON.stringify(options.body);
    }
    return fetch(url, fetchOpts).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (data) {
        if (!resp.ok) {
          var message = (data && (data.message || data.error)) || ('HTTP ' + resp.status);
          var err = new Error(message);
          err.status = resp.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function esc(value) {
    return global.AIWCMarkdown.escapeHtml(value === null || value === undefined ? '' : String(value));
  }

  function toast(message, isError) {
    var old = document.querySelector('.aiwc-toast');
    if (old) old.remove();
    var el = document.createElement('div');
    el.className = 'aiwc-toast' + (isError ? ' err' : '');
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () {
      if (el.parentNode) el.remove();
    }, 3500);
  }

  function fmtDate(mysqlDate) {
    if (!mysqlDate) return '';
    var d = new Date(mysqlDate.replace(' ', 'T') + 'Z');
    if (isNaN(d.getTime())) return mysqlDate;
    return d.toLocaleString(cfg.language === 'fa' ? 'fa-IR' : 'en-GB');
  }

  function fmtNum(n) {
    try {
      return new Intl.NumberFormat(cfg.language === 'fa' ? 'fa-IR' : 'en-GB').format(n);
    } catch (e) {
      return String(n);
    }
  }

  function riskBadge(risk) {
    var map = {
      read: ['muted', t('read_only')],
      write: ['info', t('risk_medium')],
      destructive: ['warn', t('risk_high')],
      critical: ['err', t('risk_critical')]
    };
    var m = map[risk] || ['muted', risk];
    return '<span class="aiwc-badge ' + m[0] + '">' + esc(m[1]) + '</span>';
  }

  function statusBadge(status) {
    var map = {
      success: ['ok', t('success')],
      failed: ['err', t('failed')],
      pending: ['warn', t('pending')],
      rejected: ['err', t('rejected')],
      complete: ['ok', t('complete')],
      running: ['info', t('running')]
    };
    var m = map[status] || ['muted', status];
    return '<span class="aiwc-badge ' + m[0] + '">' + esc(m[1]) + '</span>';
  }

  cfg.t = t;
  cfg.api = api;
  cfg.esc = esc;
  cfg.toast = toast;
  cfg.fmtDate = fmtDate;
  cfg.fmtNum = fmtNum;
  cfg.riskBadge = riskBadge;
  cfg.statusBadge = statusBadge;
  global.AIWC = cfg;
})(window);
