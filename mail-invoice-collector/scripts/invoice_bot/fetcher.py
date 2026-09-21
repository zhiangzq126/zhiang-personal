import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF"
OFD_MAGIC = b"PK"
PNG_MAGIC = b"\x89PNG"
JPEG_MAGIC = b"\xff\xd8\xff"
TLS_RELAX_HOST_RE = re.compile(r"\.chinatax\.gov\.cn$", re.I)
BROWSER_DEAD_RE = re.compile(
    r"(has been closed|Target page, context or browser|browser has (been )?disconnected|crash)", re.I
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DOWNLOAD_SELECTORS = [
    "text=下载发票",
    "text=发票下载",
    "text=下载电子发票",
    "text=下载PDF",
    "text=下载 PDF",
    "text=立即下载",
    "text=下载全部",
    "text=获取发票",
    "text=查看发票",
    "text=Download",
    "button:has-text('下载')",
    "a:has-text('下载')",
    "a[download]",
    "a[href$='.pdf']",
]


class FetchResult:
    def __init__(self, payload: Optional[bytes], filename: str = "", note: str = ""):
        self.payload = payload
        self.filename = filename
        self.note = note

    def __bool__(self) -> bool:
        return bool(self.payload)


def _looks_like_doc(payload: bytes, content_type: str) -> bool:
    if not payload:
        return False
    if payload.startswith(PDF_MAGIC):
        return True
    if payload.startswith((PNG_MAGIC, JPEG_MAGIC)):
        return True
    if not payload.startswith(OFD_MAGIC):
        return False
    ct = content_type.lower()
    return "ofd" in ct or "zip" in ct


def _fix_mojibake(name: str) -> str:
    if not re.search(r"[\u0080-\u00ff]", name):
        return name
    try:
        fixed = name.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    return name if "\ufffd" in fixed else fixed


def _filename_from(response, url: str) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    if match := re.search(r"filename\*\s*=\s*(?:UTF-8'')?([^;]+)", disposition, re.I):
        return _fix_mojibake(unquote(match.group(1).strip().strip('"')))
    if match := re.search(r'filename\s*=\s*"?([^";]+)', disposition, re.I):
        name = _fix_mojibake(match.group(1).strip())
        if "%" in name:
            name = _fix_mojibake(unquote(name))
        return name
    tail = url.split("?")[0].rsplit("/", 1)[-1]
    return tail if tail.lower().endswith((".pdf", ".ofd", ".png", ".jpg", ".jpeg", ".zip")) else "invoice.pdf"


DLJ_PATH_RE = re.compile(r"/dlj/v\d+/")
SIGNATURE_RE = re.compile(r'id="signatureString"\s+value="([^"]+)"', re.I)
DLJ_ID_RE = re.compile(r'id="dlj"\s+value="([^"]+)"', re.I)
META_REFRESH_RE = re.compile(
    r"<meta[^>]+http-equiv\s*=\s*[\"']?refresh[\"']?[^>]+url=([^\"'>\s]+)", re.I
)


def _resolve_interstitial(html: str, page_url: str) -> Optional[str]:
    """分享页是中间页：真实文件要靠页面里的隐藏签名二次请求。"""
    if DLJ_PATH_RE.search(page_url):
        signature = SIGNATURE_RE.search(html)
        dlj = DLJ_ID_RE.search(html)
        if signature and dlj:
            origin = urlsplit(page_url)
            return (
                f"{origin.scheme}://{origin.netloc}/dlj/v7/downloadFile/{dlj.group(1)}"
                f"?signatureString={quote(signature.group(1), safe='')}"
            )
    if match := META_REFRESH_RE.search(html):
        return urljoin(page_url, match.group(1))
    return None


def fetch_direct(url: str, timeout: int, depth: int = 0) -> FetchResult:
    if depth > 3:
        return FetchResult(None, note="中间页跳转层数过深")

    note = ""
    try:
        response = requests.get(
            url, timeout=timeout, allow_redirects=True, headers={"User-Agent": USER_AGENT}
        )
    except requests.exceptions.SSLError as exc:
        host = urlsplit(url).hostname or ""
        if not TLS_RELAX_HOST_RE.search(host):
            return FetchResult(None, note=f"证书校验失败：{exc}")
        # 税务总局电子发票平台证书链不规范，仅对该白名单主机降级并留痕
        note = f"（{host} 证书校验已降级）"
        log.warning("证书校验失败，对白名单主机降级重试：%s", host)
        try:
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                verify=False,
            )
        except requests.RequestException as exc:
            return FetchResult(None, note=f"直连失败：{exc}")
    except requests.RequestException as exc:
        return FetchResult(None, note=f"直连失败：{exc}")

    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        return FetchResult(None, note=f"直连失败：{exc}")

    content_type = response.headers.get("Content-Type", "")
    if _looks_like_doc(response.content, content_type):
        return FetchResult(response.content, _filename_from(response, response.url), note)

    if "html" in content_type.lower():
        next_url = _resolve_interstitial(response.text[: 512 * 1024], response.url)
        if next_url:
            log.info("中间页跳转：%s → %s", response.url, next_url)
            return fetch_direct(next_url, timeout, depth + 1)

    return FetchResult(None, note="链接返回的是网页，需要浏览器")


def _launch(pw, profile_dir: Path, headless: bool, channel: str):
    """auto 时优先用系统已装浏览器，避免依赖内置 Chromium 的下载。"""
    candidates = [channel] if channel != "auto" else ["chrome", "msedge", "chromium"]
    errors = []
    for name in candidates:
        options = {
            "user_data_dir": str(profile_dir / name),
            "headless": headless,
            "accept_downloads": True,
        }
        if name != "chromium":
            options["channel"] = name
        try:
            context = pw.chromium.launch_persistent_context(**options)
            log.info("使用浏览器：%s", name)
            return context, name
        except Exception as exc:
            errors.append(f"{name}: {str(exc).splitlines()[0]}")
    raise RuntimeError("；".join(errors))


def fetch_with_browser(
    urls: List[str],
    profile_dir: Path,
    timeout: int,
    headless: bool = False,
    channel: str = "auto",
) -> List[Tuple[str, FetchResult]]:
    """持久化浏览器：自动点下载按钮，遇验证码/登录由用户手动完成。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return [(url, FetchResult(None, note="未安装 Playwright")) for url in urls]

    results: List[Tuple[str, FetchResult]] = []
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        try:
            context, _name = _launch(pw, profile_dir, headless, channel)
        except RuntimeError as exc:
            return [(url, FetchResult(None, note=f"浏览器启动失败：{exc}")) for url in urls]

        page = context.new_page()
        relaunch_budget = 1
        index = 0
        while index < len(urls):
            url = urls[index]
            try:
                result = _fetch_one(page, url, timeout)
            except Exception as exc:
                result = FetchResult(None, note=f"浏览器异常：{str(exc).splitlines()[0]}")

            if result or not BROWSER_DEAD_RE.search(result.note or ""):
                results.append((url, result))
                index += 1
                continue

            # 浏览器/上下文已关闭：尝试重建一次，失败则整批中止、剩余留待下次
            if relaunch_budget > 0:
                relaunch_budget -= 1
                log.warning("浏览器已关闭，尝试重启后重试：%s", url)
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    context, _name = _launch(pw, profile_dir, headless, channel)
                    page = context.new_page()
                    continue  # 不推进 index，重试当前链接
                except Exception as exc:
                    log.error("浏览器重启失败：%s", str(exc).splitlines()[0])
            log.warning("浏览器不可用，剩余 %d 个链接本轮跳过", len(urls) - index)
            results.extend(
                (rest, FetchResult(None, note="浏览器已关闭，下次重试")) for rest in urls[index:]
            )
            break

        try:
            context.close()
        except Exception:
            pass
    return results


SPA_HOST_RE = re.compile(
    r"((nnfp|fp)\.jss\.com\.cn|(bwfp|u|pis|web)\.baiwang\.com|yun\.ekaikai\.cn)", re.I
)
SPA_HIJACK_SCRIPT = """
window.__opens = [];
window.open = (u) => { window.__opens.push(String(u)); return { closed: false, close() {}, focus() {} }; };
"""
SPA_CLICK_STRATEGIES = [
    """() => { const el = [...document.querySelectorAll('a,button,div,span')]
        .find(x => (x.innerText || '').trim() === '下载PDF文件');
        if (el) { el.click(); return (el.innerText || '').trim(); } return null; }""",
    """() => { const el = [...document.querySelectorAll('a,button,div,span')]
        .find(x => /下载PDF/.test(x.innerText || '') && (x.innerText || '').length < 12);
        if (el) { el.click(); return (el.innerText || '').trim(); } return null; }""",
    """() => { const el = [...document.querySelectorAll('a,button')]
        .find(x => /PDF/.test(x.innerText || '') && /下载|download/i.test(x.innerText || ''));
        if (el) { el.click(); return (el.innerText || '').trim(); } return null; }""",
]


def _capture_spa_url(page, url: str, timeout: int) -> Optional[str]:
    """SPA 的下载是点击时 window.open(签名URL)，钩住它才能拿到真实地址。"""
    page.add_init_script(SPA_HIJACK_SCRIPT)
    page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
    page.wait_for_timeout(2000)
    for strategy in SPA_CLICK_STRATEGIES:
        clicked = page.evaluate(strategy)
        if not clicked:
            continue
        page.wait_for_timeout(2500)
        opens = page.evaluate("() => window.__opens || []")
        if opens:
            log.info("SPA 点击「%s」捕获到下载地址", clicked)
            return urljoin(page.url, opens[0])
    return None


def _fetch_one(page, url: str, timeout: int) -> FetchResult:
    if SPA_HOST_RE.search(url):
        try:
            signed = _capture_spa_url(page, url, timeout)
        except Exception as exc:
            return FetchResult(None, note=f"SPA 页面处理失败：{str(exc).splitlines()[0]}")
        if not signed:
            return FetchResult(None, note="SPA 页面上没点到下载按钮，请手工下载")
        result = fetch_direct(signed, timeout)
        if result:
            return result
        return FetchResult(None, note=f"SPA 捕获的地址未返回文件：{result.note}")

    captured: List[bytes] = []
    downloads = []

    def on_response(response):
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or response.url.split("?")[0].lower().endswith(".pdf"):
            try:
                captured.append(response.body())
            except Exception:
                pass

    def on_download(download):
        downloads.append(download)

    page.on("response", on_response)
    page.on("download", on_download)
    try:
        try:
            page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        except Exception as exc:
            # 直下型链接会让导航本身变成下载，这不是失败
            if "Download is starting" not in str(exc):
                return FetchResult(None, note=f"页面打不开：{str(exc).splitlines()[0]}")

        if downloads:
            return _from_download(downloads[-1])

        try:
            with page.expect_download(timeout=timeout * 1000) as download_info:
                _try_clicks(page)
                log.info("等待下载中（如需登录或验证码，请在浏览器里手动完成）：%s", url)
            return _from_download(download_info.value)
        except Exception:
            if captured:
                return FetchResult(captured[-1], "invoice.pdf", note="从页面响应中截获 PDF")
            return FetchResult(None, note="浏览器未取到文件，请手工下载")
    finally:
        page.remove_listener("response", on_response)
        page.remove_listener("download", on_download)


def _from_download(download) -> FetchResult:
    try:
        payload = Path(download.path()).read_bytes()
    except Exception as exc:
        return FetchResult(None, note=f"下载文件读取失败：{str(exc).splitlines()[0]}")
    return FetchResult(payload, download.suggested_filename or "invoice.pdf")


def _try_clicks(page) -> None:
    for selector in DOWNLOAD_SELECTORS:
        try:
            element = page.locator(selector).first
            if element.count() and element.is_visible():
                element.click(timeout=3000)
                return
        except Exception:
            continue
