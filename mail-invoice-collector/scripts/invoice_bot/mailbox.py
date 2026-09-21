import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple

from bs4 import BeautifulSoup
from imap_tools import AND, MailBox
from imap_tools.errors import MailboxFolderSelectError

log = logging.getLogger(__name__)

DOC_SUFFIXES = (".pdf", ".ofd")
IMG_SUFFIXES = (".png", ".jpg", ".jpeg")
URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]，。；]+")
MAX_LINKS_PER_MAIL = 12


@dataclass
class Attachment:
    filename: str
    payload: bytes


@dataclass
class MailItem:
    uid: str
    subject: str
    sender: str
    date: str
    attachments: List[Attachment] = field(default_factory=list)
    links: List[Tuple[str, str]] = field(default_factory=list)


def _send_imap_id(client) -> None:
    """网易系服务器要求登录后上报客户端标识，否则 SELECT 会被拒绝。"""
    args = '("name" "invoice-bot" "version" "1.0.0" "vendor" "qoder" "support-email" "none")'
    try:
        typ, data = client._simple_command("ID", args)
        client._untagged_response(typ, data, "ID")
    except Exception as exc:  # 服务器不支持 ID 时忽略即可
        log.debug("发送 IMAP ID 失败：%s", exc)


def expand(filename: str, payload: bytes) -> List[Attachment]:
    lower = filename.lower()
    if lower.endswith(DOC_SUFFIXES) or lower.endswith(IMG_SUFFIXES):
        return [Attachment(filename, payload)]
    if lower.endswith(".zip"):
        found = []
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                for info in zf.infolist():
                    inner_low = info.filename.lower()
                    if info.is_dir() or not (inner_low.endswith(DOC_SUFFIXES) or inner_low.endswith(IMG_SUFFIXES)):
                        continue
                    inner = info.filename.rsplit("/", 1)[-1]
                    found.append(Attachment(inner, zf.read(info)))
        except zipfile.BadZipFile:
            log.warning("压缩包无法解开：%s", filename)
        return found
    return []


WJGS_RE = re.compile(r"([?&]Wjgs=)(OFD|XML)", re.I)


JUNK_LINK_RE = re.compile(
    r"(tydl-login|aboutone/index|ebill\.spdbccc\.com\.cn"
    r"|(?:www|web|fp|pay|ntf|bmjc|baoxiao|nst)\.(?:nuonuo|baiwang|51fapiao)\.com"
    r"|nuonuo\.com/nuonuo/web/about"
    r"|inv-veri\.chinatax\.gov\.cn/download"       # 税局 OFD 阅读器软件包，非发票
    r"|ad\.efapiao\.com"                           # 广告位
    r"|阅读器|reader[^/]*\.zip)",             # 各类阅读器安装包（仅当路径含 reader 时才排除 .zip）
    re.I,
)
TRACKING_RE = re.compile(
    r"(linktrace|sendcloud|/opens?\b|click\.|/open\.do|getEwmImg"
    r"|tracedm|/trace/|es\.xiaojukeji\.com|countmkt|mail\.163\.com"  # 邮件追踪/营销像素
    r"|/pixel/|/tracking/|/beacon|/impression|spacer\.gif|blank\.gif|1x1\.(gif|png)"  # 追踪像素常见路径
    r"|weixin\.qq\.com/cgi-bin|mail\.qq\.com)",
    re.I,
)
DOWNLOAD_PATH_RE = re.compile(r"/(dlj|download|dzfp|fp)/", re.I)
PLATFORM_RE = re.compile(
    r"(fapiao|invoice|nnfp|baiwang|wosaimg|chinatax|jcsk100|ekaikai|pdd-fapiao)", re.I
)
SHORTLINK_RE = re.compile(r"^https?://(?:[us]|wxmpurl)\.[a-z0-9-]+\.[a-z]+/", re.I)
MAX_CANDIDATES = 3


def score_url(url: str) -> int:
    score = 0
    if re.search(r"\.pdf(\?|$)", url, re.I):
        score += 10
    if DOWNLOAD_PATH_RE.search(url):
        score += 4
    if PLATFORM_RE.search(url):
        score += 3
    if SHORTLINK_RE.match(url):
        score += 1
    return score


def _prefer_pdf_url(url: str) -> str:
    """全国电子发票服务平台同一张票有 PDF/OFD/XML 三个链接，归一到 PDF 后可直接去重。"""
    return WJGS_RE.sub(r"\1PDF", url)


def _extract_links(msg, keywords, excludes) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    if msg.html:
        soup = BeautifulSoup(msg.html, "html.parser")
        for anchor in soup.find_all("a", href=True):
            candidates.append((anchor.get_text(" ", strip=True), anchor["href"]))
    for url in URL_RE.findall(msg.text or ""):
        candidates.append(("", url))

    picked: List[Tuple[str, str]] = []
    seen = set()
    for text, url in candidates:
        if not url.lower().startswith("http"):
            continue
        if url.split("://", 1)[-1].split("?")[0].split("#")[0].rstrip("/").count("/") == 0:
            continue
        url = _prefer_pdf_url(url)
        if JUNK_LINK_RE.search(url) or TRACKING_RE.search(url):
            continue
        haystack = f"{text} {url}".lower()
        if any(bad in haystack for bad in excludes):
            continue
        if keywords and not any(good in haystack for good in keywords):
            continue
        if url in seen:
            continue
        seen.add(url)
        picked.append((text, url))
        if len(picked) >= MAX_LINKS_PER_MAIL:
            break
    picked = prefer_pdf_links(picked)
    picked.sort(key=lambda item: score_url(item[1]), reverse=True)
    return picked[:MAX_CANDIDATES]


PDF_LINK_RE = re.compile(r"(\.pdf|/pdf/|wjgs=pdf)", re.I)
NON_PDF_LINK_RE = re.compile(r"(\.ofd|/ofd/|\.xml|/xml/|\.zip|wjgs=(ofd|xml))", re.I)


def prefer_pdf_links(links: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    if not any(PDF_LINK_RE.search(url) for _text, url in links):
        return links
    return [(text, url) for text, url in links if not NON_PDF_LINK_RE.search(url)]


def prefer_pdf(attachments: List[Attachment]) -> List[Attachment]:
    pdfs = [a for a in attachments if a.filename.lower().endswith(".pdf")]
    return pdfs or attachments


def list_folders(mailbox_cfg) -> List[str]:
    with MailBox(mailbox_cfg.host, mailbox_cfg.port) as mb:
        mb.login(mailbox_cfg.email, mailbox_cfg.password, initial_folder=None)
        if mailbox_cfg.needs_imap_id:
            _send_imap_id(mb.client)
        return [folder.name for folder in mb.folder.list()]


def fetch_mails(mailbox_cfg, cfg, seen_uids: set, limit: Optional[int] = None, since=None,
                mail_since=None, mail_until=None) -> Iterator[MailItem]:
    log.info("连接 %s (%s:%s)", mailbox_cfg.email, mailbox_cfg.host, mailbox_cfg.port)
    with MailBox(mailbox_cfg.host, mailbox_cfg.port) as mb:
        mb.login(mailbox_cfg.email, mailbox_cfg.password, initial_folder=None)
        if mailbox_cfg.needs_imap_id:
            _send_imap_id(mb.client)
        try:
            mb.folder.set(mailbox_cfg.folder)
        except MailboxFolderSelectError:
            names = [f.name for f in mb.folder.list()]
            raise RuntimeError(
                f"打不开文件夹「{mailbox_cfg.folder}」。该邮箱现有文件夹：{names}"
            ) from None

        criteria = AND(date_gte=since) if since else "ALL"
        for msg in mb.fetch(criteria, mark_seen=False, bulk=True, limit=limit, reverse=bool(limit) and not since):
            if msg.uid in seen_uids:
                continue
            if mail_since or mail_until:
                mday = msg.date.date() if msg.date else None
                if mday is None or (mail_since and mday < mail_since) or (mail_until and mday > mail_until):
                    continue
            item = MailItem(
                uid=msg.uid,
                subject=msg.subject or "(无主题)",
                sender=msg.from_ or "",
                date=msg.date.strftime("%Y-%m-%d %H:%M") if msg.date else "",
            )
            for att in msg.attachments:
                item.attachments.extend(expand(att.filename or "", att.payload))
            item.attachments = prefer_pdf(item.attachments)
            item.links = _extract_links(msg, cfg.link_keywords, cfg.link_exclude)
            log.info(
                "邮件 uid=%s《%s》附件%d 候选链接%d",
                item.uid, item.subject, len(item.attachments), len(item.links),
            )
            yield item
