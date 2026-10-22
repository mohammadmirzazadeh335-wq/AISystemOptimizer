#!/usr/bin/env python3
import http.server, socketserver, os, urllib.parse

OUT = "/home/user/AISystemOptimizer/SmartLocker_ReadyToOpen"
PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Force download for STEP files
        path = self.path.split('?')[0]
        full = OUT + path
        # also handle root
        if path == "/" or path == "":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"""
<html><head><meta charset="utf-8"><title>SmartLocker STEP Download</title></head>
<body style="font-family:Tahoma; text-align:center; padding:40px;">
<h2>📦 SmartLocker STEP فایل کامپایل‌شده - دانلود مستقیم</h2>
<p>روی لینک زیر بزن - بلافاصله دانلود میشه:</p>
<p><a href="/STEP/SmartLocker_10Cell_SolidWorks2025.STEP" download style="font-size:18px; background:#0078d4; color:white; padding:12px 24px; text-decoration:none; border-radius:8px;">⬇ دانلود SmartLocker_10Cell_Compiled.STEP (227 KB)</a></p>
<p><a href="/STEP/SmartLocker_SINGLE_CELL_400x500x400.STEP" download style="font-size:16px; background:#107c10; color:white; padding:10px 20px; text-decoration:none; border-radius:8px;">⬇ دانلود SINGLE_CELL_400x500x400.STEP (6 KB)</a></p>
<p><a href="/STL/SmartLocker_10Cell_Complete.stl" download>⬇ STL Complete (111 KB)</a> | <a href="/DXF/SmartLocker_TopView.DXF" download>⬇ DXF TopView</a></p>
<hr>
<p>آموزش: SolidWorks > File > Open > Files of type: STEP (*.step) > انتخاب فایل > Open > Import as Solid Body</p>
</body></html>
            """.encode('utf-8'))
            return
        if os.path.isfile(full):
            self.send_response(200)
            if full.endswith(".STEP") or full.endswith(".STP"):
                self.send_header("Content-Type", "application/step")
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
            elif full.endswith(".stl"):
                self.send_header("Content-Type", "application/sla")
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
            elif full.endswith(".DXF"):
                self.send_header("Content-Type", "application/dxf")
                self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(full)}"')
            else:
                self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(os.path.getsize(full)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with open(full, 'rb') as f:
                self.wfile.write(f.read())
            return
        # fallback to super
        os.chdir(OUT)
        return super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Frame-Options", "ALLOWALL")
        super().end_headers()

with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
    print(f"Serving at 0.0.0.0:{PORT} -> OUT={OUT}")
    httpd.serve_forever()
