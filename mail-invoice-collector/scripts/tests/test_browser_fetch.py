"""验证链接取票链路：直连下载、浏览器点按钮下载、PDF 内联响应截获、彻底失败的兜底提示。
运行：python tests/test_browser_fetch.py
"""

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from invoice_bot import fetcher

FAKE_PDF = b"%PDF-1.4\n% fake invoice payload for tests\n"

PAGE_DOWNLOAD = """<html><body>
<p>您的发票已开好</p>
<a id="dl" download="invoice.pdf" href="/attach.pdf">下载发票</a>
</body></html>"""

PAGE_INLINE = """<html><body>
<p>发票预览</p>
<a href="/inline.pdf">查看发票</a>
</body></html>"""

PAGE_PLAIN = """<html><body><p>这个页面没有任何发票入口</p></body></html>"""

PAGE_DLJ = """<html><body>
<input type="hidden" id="dlj" value="ABC123">
<input type="hidden" id="signatureString" value="sig+with/special=chars">
</body></html>"""

PAGE_META_REFRESH = """<html><head>
<meta http-equiv="refresh" content="0;url=/direct.pdf">
</head><body>正在跳转</body></html>"""

PAGE_SPA = """<html><body>
<div id="btn" onclick="window.open('/signed.pdf?token=xyz')">下载PDF文件</div>
</body></html>"""

SIGNATURE_VALUE = "sig+with/special=chars"
MOJIBAKE_NAME = "发票_测试.pdf"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path
        routes = {
            "/direct.pdf": (FAKE_PDF, "application/pdf", 'attachment; filename="direct-invoice.pdf"'),
            "/attach.pdf": (FAKE_PDF, "application/pdf", 'attachment; filename="invoice.pdf"'),
            "/inline.pdf": (FAKE_PDF, "application/pdf", "inline"),
            "/signed.pdf": (FAKE_PDF, "application/pdf", 'attachment; filename="signed.pdf"'),
            "/page-download.html": (PAGE_DOWNLOAD.encode(), "text/html; charset=utf-8", None),
            "/page-inline.html": (PAGE_INLINE.encode(), "text/html; charset=utf-8", None),
            "/page-plain.html": (PAGE_PLAIN.encode(), "text/html; charset=utf-8", None),
            "/dlj/v7/share": (PAGE_DLJ.encode(), "text/html; charset=utf-8", None),
            "/page-meta.html": (PAGE_META_REFRESH.encode(), "text/html; charset=utf-8", None),
            "/spa/invoice": (PAGE_SPA.encode(), "text/html; charset=utf-8", None),
        }
        if path.startswith("/signed.pdf"):
            path = "/signed.pdf"
        if path.startswith("/dlj/v7/downloadFile/ABC123"):
            query = parse_qs(urlsplit(self.path).query)
            if query.get("signatureString", [""])[0] != SIGNATURE_VALUE:
                self.send_error(403)
                return
            body, content_type = FAKE_PDF, "application/pdf"
            disposition = "attachment; filename=\"%s\"" % MOJIBAKE_NAME.encode("utf-8").decode("latin1")
        elif path in routes:
            body, content_type, disposition = routes[path]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(body)


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def check_direct(base: str) -> int:
    failures = 0

    result = fetcher.fetch_direct(f"{base}/direct.pdf", 10)
    ok = bool(result) and result.payload == FAKE_PDF and result.filename == "direct-invoice.pdf"
    failures += 0 if ok else 1
    print(f"[直连 PDF] {'PASS' if ok else 'FAIL'} filename={result.filename!r} bytes={len(result.payload or b'')}")

    result = fetcher.fetch_direct(f"{base}/page-download.html", 10)
    ok = not result and "浏览器" in result.note
    failures += 0 if ok else 1
    print(f"[直连遇网页] {'PASS' if ok else 'FAIL'} note={result.note}")

    result = fetcher.fetch_direct(f"{base}/nope.pdf", 10)
    ok = not result and "直连失败" in result.note
    failures += 0 if ok else 1
    print(f"[直连 404] {'PASS' if ok else 'FAIL'} note={result.note}")
    return failures


def check_browser(base: str) -> int:
    profile = ROOT / "data" / "_test_browser_profile"
    urls = [f"{base}/page-download.html", f"{base}/page-inline.html", f"{base}/page-plain.html"]
    results = dict(fetcher.fetch_with_browser(urls, profile, timeout=15, headless=True))

    failures = 0
    expectations = [
        ("点按钮下载", f"{base}/page-download.html", True),
        ("内联 PDF 截获", f"{base}/page-inline.html", True),
        ("无入口页面", f"{base}/page-plain.html", False),
    ]
    for label, url, should_succeed in expectations:
        result = results[url]
        ok = bool(result) == should_succeed and (not should_succeed or result.payload == FAKE_PDF)
        failures += 0 if ok else 1
        detail = f"bytes={len(result.payload or b'')} filename={result.filename!r}" if result else f"note={result.note}"
        print(f"[{label}] {'PASS' if ok else 'FAIL'} {detail}")
    return failures


def check_interstitial(base: str) -> int:
    failures = 0

    result = fetcher.fetch_direct(f"{base}/dlj/v7/share", 10)
    ok = bool(result) and result.payload == FAKE_PDF and result.filename == MOJIBAKE_NAME
    failures += 0 if ok else 1
    print(f"[中间页签名解析] {'PASS' if ok else 'FAIL'} filename={result.filename!r} note={result.note}")

    result = fetcher.fetch_direct(f"{base}/page-meta.html", 10)
    ok = bool(result) and result.payload == FAKE_PDF
    failures += 0 if ok else 1
    print(f"[meta refresh 跳转] {'PASS' if ok else 'FAIL'} filename={result.filename!r}")
    return failures


def check_spa(base: str) -> int:
    import re

    original = fetcher.SPA_HOST_RE
    fetcher.SPA_HOST_RE = re.compile(r"/spa/")
    try:
        profile = ROOT / "data" / "_test_browser_profile"
        results = dict(
            fetcher.fetch_with_browser([f"{base}/spa/invoice"], profile, timeout=20, headless=True)
        )
    finally:
        fetcher.SPA_HOST_RE = original

    result = results[f"{base}/spa/invoice"]
    ok = bool(result) and result.payload == FAKE_PDF
    detail = f"filename={result.filename!r}" if result else f"note={result.note}"
    print(f"[SPA window.open 捕获] {'PASS' if ok else 'FAIL'} {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    server, base = start_server()
    try:
        total = check_direct(base) + check_interstitial(base) + check_browser(base) + check_spa(base)
    finally:
        server.shutdown()
    print(f"\n{'全部通过' if total == 0 else f'失败 {total} 项'}")
    raise SystemExit(1 if total else 0)
