#!/usr/bin/env python3
"""Fails when a bilingual string is missing one of its two languages."""
import glob, io, re, sys

# strings that are legitimately the same in both languages
ALLOWED = {"MTU", "DNS", "s", "ms", "%", "TLS", "UDP", "TCP", "WARP", "SOCKS5", "OpenVPN", "sing-box"}

pattern = re.compile(r'L\.T\(\s*"((?:[^"\\]|\\.)*)"\s*(,\s*"((?:[^"\\]|\\.)*)"\s*)?\)')
problems = []
for path in sorted(glob.glob('ServerHelp/src/ServerHelp/**/*.cs', recursive=True)):
    text = io.open(path, encoding='utf-8').read()
    for match in pattern.finditer(text):
        line = text[:match.start()].count('\n') + 1
        fa = match.group(1)
        en = match.group(3)
        if en is None:
            problems.append(f"{path}:{line}: L.T with only one language: {fa[:60]!r}")
            continue
        if fa.strip() == en.strip() and fa.strip() not in ALLOWED and re.search(r'[A-Za-z\u0600-\u06FF]{3}', fa):
            problems.append(f"{path}:{line}: identical Persian and English text: {fa[:60]!r}")

for p in problems:
    print(p)
print(f"{len(problems)} translation problem(s)")
sys.exit(1 if problems else 0)
