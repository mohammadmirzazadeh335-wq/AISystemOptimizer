/**
 * Minimal, safe Markdown renderer for AIWC (no external deps).
 * Escapes HTML first, then applies markdown transforms.
 */
(function (global) {
  'use strict';

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function renderInline(text) {
    // Code spans first (protect content).
    var codes = [];
    text = text.replace(/`([^`]+)`/g, function (_, code) {
      codes.push(code);
      return '\u0000CODE' + (codes.length - 1) + '\u0000';
    });

    text = text.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img alt="$1" src="$2" style="max-width:100%;border-radius:8px">');
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, label, url) {
      if (!/^(https?:|\/|#|mailto:)/i.test(url)) {
        return label;
      }
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + label + '</a>';
    });
    text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    text = text.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
    text = text.replace(/_([^_\n]+)_/g, '<em>$1</em>');
    text = text.replace(/~~([^~]+)~~/g, '<del>$1</del>');

    // Restore code spans.
    text = text.replace(/\u0000CODE(\d+)\u0000/g, function (_, i) {
      return '<code>' + escapeHtml(codes[+i]) + '</code>';
    });
    return text;
  }

  function render(md) {
    if (!md) return '';
    var text = escapeHtml(String(md));

    // Extract fenced code blocks.
    var blocks = [];
    text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      blocks.push('<pre><code class="lang-' + lang + '">' + code.replace(/\n$/, '') + '</code></pre>');
      return '\u0000BLOCK' + (blocks.length - 1) + '\u0000';
    });

    var lines = text.split('\n');
    var out = [];
    var listType = null;
    var inTable = false;
    var tableRows = [];

    function closeList() {
      if (listType) {
        out.push(listType === 'ol' ? '</ol>' : '</ul>');
        listType = null;
      }
    }

    function flushTable() {
      if (!inTable) return;
      if (tableRows.length) {
        out.push('<table>');
        tableRows.forEach(function (row, idx) {
          out.push('<tr>');
          row.forEach(function (cell) {
            var tag = idx === 0 ? 'th' : 'td';
            out.push('<' + tag + '>' + renderInline(cell.trim()) + '</' + tag + '>');
          });
          out.push('</tr>');
        });
        out.push('</table>');
      }
      inTable = false;
      tableRows = [];
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // Table rows.
      if (/^\s*\|.*\|\s*$/.test(line)) {
        closeList();
        inTable = true;
        var cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|');
        // Skip separator rows like |---|---|.
        if (!cells.every(function (c) { return /^\s*:?-{2,}:?\s*$/.test(c); })) {
          tableRows.push(cells);
        }
        continue;
      } else if (inTable) {
        flushTable();
      }

      // Headings.
      var h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        closeList();
        var level = h[1].length;
        out.push('<h' + level + '>' + renderInline(h[2]) + '</h' + level + '>');
        continue;
      }

      // Blockquote.
      if (/^&gt;\s?/.test(line)) {
        closeList();
        out.push('<blockquote>' + renderInline(line.replace(/^&gt;\s?/, '')) + '</blockquote>');
        continue;
      }

      // Horizontal rule.
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        closeList();
        out.push('<hr>');
        continue;
      }

      // Unordered list.
      var ul = line.match(/^\s*[-*+]\s+(.*)$/);
      if (ul) {
        if (listType !== 'ul') {
          closeList();
          out.push('<ul>');
          listType = 'ul';
        }
        out.push('<li>' + renderInline(ul[1]) + '</li>');
        continue;
      }

      // Ordered list.
      var ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (ol) {
        if (listType !== 'ol') {
          closeList();
          out.push('<ol>');
          listType = 'ol';
        }
        out.push('<li>' + renderInline(ol[1]) + '</li>');
        continue;
      }

      // Blank line.
      if (/^\s*$/.test(line)) {
        closeList();
        continue;
      }

      // Paragraph.
      closeList();
      out.push('<p>' + renderInline(line) + '</p>');
    }
    closeList();
    flushTable();

    var html = out.join('\n');

    // Restore fenced blocks.
    html = html.replace(/\u0000BLOCK(\d+)\u0000/g, function (_, i) {
      return blocks[+i];
    });
    return html;
  }

  global.AIWCMarkdown = { render: render, escapeHtml: escapeHtml };
})(window);
