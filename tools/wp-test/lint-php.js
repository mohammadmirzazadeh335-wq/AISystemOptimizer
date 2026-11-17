#!/usr/bin/env node
/**
 * Syntax-lint all PHP files of the AIWC plugin using php-parser (pure JS).
 * Usage: node lint-php.js [path...]
 */
const fs = require('fs');
const path = require('path');
const Engine = require('php-parser');

const parser = new Engine({
  parser: { extractDoc: true, suppressErrors: false },
  ast: { withPositions: true },
});

const roots = process.argv.slice(2);
if (!roots.length) {
  roots.push(path.join(__dirname, '..', '..', 'ai-wordpress-copilot'));
}

let checked = 0;
let failed = 0;

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules') continue;
      walk(full);
    } else if (entry.name.endsWith('.php')) {
      lint(full);
    }
  }
}

function lint(file) {
  checked++;
  const src = fs.readFileSync(file, 'utf8');
  try {
    parser.parseCode(src, file);
    console.log('OK   ' + path.relative(process.cwd(), file));
  } catch (e) {
    failed++;
    console.log('FAIL ' + path.relative(process.cwd(), file) + ' -> ' + e.message);
  }
}

for (const root of roots) {
  const stat = fs.statSync(root);
  if (stat.isDirectory()) walk(root);
  else lint(root);
}

console.log(`\n${checked} files checked, ${failed} failed`);
process.exit(failed ? 1 : 0);
