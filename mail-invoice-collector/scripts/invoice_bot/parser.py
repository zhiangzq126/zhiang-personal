import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pdfplumber

log = logging.getLogger(__name__)

STATUS_OK = "OK"
STATUS_REVIEW = "NEEDS_REVIEW"

TYPE_KEYWORDS = [
    ("铁路电子客票", "铁路电子客票"),
    ("航空运输电子客票行程单", "机票行程单"),
    ("电子客票行程单", "机票行程单"),
    ("增值税专用发票", "增值税专用发票"),
    ("专用发票", "增值税专用发票"),
    ("增值税电子普通发票", "增值税电子普通发票"),
    ("电子发票（普通发票）", "电子发票(普通发票)"),
    ("电子发票(普通发票)", "电子发票(普通发票)"),
    ("增值税普通发票", "增值税普通发票"),
    ("定额发票", "定额发票"),
    ("通用机打发票", "通用机打发票"),
]

NAME_STOP = re.compile(r"(统一社会信用代码|纳税人识别号|地址|电话|开户|账号|销售方|购买方|项目名称|货物或应税)")
NUMBER_RE = re.compile(r"发票号码[:：]?\s*([0-9A-Z]{8,25})")
CODE_RE = re.compile(r"发票代码[:：]?\s*([0-9]{10,14})")
DATE_CN_RE = re.compile(r"开票日期[:：]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DATE_ISO_RE = re.compile(r"开票日期[:：]?\s*(\d{4})-(\d{1,2})-(\d{1,2})")
TAX_ID_RE = re.compile(r"(?:统一社会信用代码/纳税人识别号|统一社会信用代码|纳税人识别号)[:：]?\s*([0-9A-Z]{15,20})")
LOWERCASE_TOTAL_RE = re.compile(r"小写[)）]?\s*[¥￥]?\s*([\d,]+\.\d{2})")
TOTAL_FALLBACK_RE = re.compile(r"价税合计[^\d]{0,24}([\d,]+\.\d{2})")
SUBTOTAL_RE = re.compile(r"合\s*计\s*[¥￥]\s*([\d,]+\.\d{2})\s*[¥￥]\s*([\d,]+\.\d{2})")
TAX_ONLY_RE = re.compile(r"税\s*额\s*[:：]?\s*[¥￥]?\s*([\d,]+\.\d{2})")
ANY_MONEY_RE = re.compile(r"[¥￥]\s*([\d,]+\.\d{2})")


@dataclass
class Invoice:
    file_path: Path
    invoice_type: str = ""
    code: str = ""
    number: str = ""
    date: str = ""
    buyer_name: str = ""
    buyer_tax_id: str = ""
    seller_name: str = ""
    seller_tax_id: str = ""
    amount: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    source: str = ""
    mail_subject: str = ""
    mail_sender: str = ""
    mail_date: str = ""
    status: str = STATUS_OK
    note: str = ""
    file_sha1: str = ""

    @property
    def dedupe_key(self) -> str:
        return f"NO:{self.number}" if self.number else f"SHA1:{self.file_sha1}"


def _money(raw: str) -> Optional[float]:
    try:
        return float(raw.replace(",", ""))
    except (ValueError, AttributeError):
        return None


RADICAL_FIXES = str.maketrans({"⻔": "门", "⻝": "食", "⻆": "角"})


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(RADICAL_FIXES)


def _compact(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", "", text)


def _detect_type(compact: str) -> str:
    for needle, label in TYPE_KEYWORDS:
        if needle in compact:
            return label
    return "未识别"


NAME_SPLIT = re.compile(r"名\s*称\s*[:：]")
GOODS_LABEL = re.compile(r"(货物|应税劳务|项目|规格|服务)$")
COLUMN_TAIL = re.compile(r"(?:\s+[购买方销售])+\s*$")


def _clean_name(segment: str) -> str:
    chunk = re.split(r"\s{2,}", segment.strip())[0]
    chunk = NAME_STOP.split(chunk)[0]
    chunk = COLUMN_TAIL.sub("", chunk)
    return chunk.strip(" :：|")


def _extract_names(text: str) -> tuple:
    """按「名称：」前面的标签判断购销归属，避免把货物名称当成公司名。"""
    buyer = seller = ""
    unlabeled = []
    for line in text.splitlines():
        parts = NAME_SPLIT.split(line)
        for index, segment in enumerate(parts[1:]):
            name = _clean_name(segment)
            if len(name) < 2:
                continue
            prefix = parts[index].replace(" ", "").rstrip("、")
            if GOODS_LABEL.search(prefix[-6:]):
                continue
            tail = prefix[-8:]
            if "销" in tail or "售" in tail:
                seller = seller or name
            elif "购" in tail or "买" in tail:
                buyer = buyer or name
            else:
                unlabeled.append(name)
    if not buyer and unlabeled:
        buyer = unlabeled.pop(0)
    if not seller and unlabeled:
        seller = unlabeled.pop(0)
    return buyer, seller


def _read_qr(pdf_path: Path) -> Optional[List[str]]:
    try:
        import fitz
        import zxingcpp
    except ImportError:
        return None
    try:
        with fitz.open(pdf_path) as doc:
            page = doc[0]
            pix = page.get_pixmap(dpi=200, clip=fitz.Rect(0, 0, page.rect.width * 0.45, page.rect.height * 0.3))
            from PIL import Image

            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for result in zxingcpp.read_barcodes(image):
                parts = result.text.split(",")
                if len(parts) >= 6 and parts[0] == "01":
                    return parts
    except Exception as exc:
        log.debug("二维码解析失败 %s: %s", pdf_path.name, exc)
    return None


def fill_from_text(invoice: Invoice, text: str) -> Invoice:
    """从 PDF 文本层提取字段。独立成函数以便用文本样例校准正则。"""
    text = _normalize(text)
    compact = _compact(text)
    if len(compact.strip()) < 20:
        invoice.status = STATUS_REVIEW
        invoice.note = "PDF 没有文本层（可能是扫描件），需 OCR 或手工录入"
    elif compact.count("(cid:") >= 5:
        # 字体未嵌入 Unicode 映射，抽出的是字形码而非文字，只能靠 OCR
        invoice.status = STATUS_REVIEW
        invoice.note = "PDF 文本层为字形码(cid)不可读，需 OCR"

    invoice.invoice_type = _detect_type(compact)

    if match := NUMBER_RE.search(compact):
        invoice.number = match.group(1)
    if match := CODE_RE.search(compact):
        invoice.code = match.group(1)
    if match := DATE_CN_RE.search(compact) or DATE_ISO_RE.search(compact):
        y, m, d = match.groups()
        invoice.date = f"{y}-{int(m):02d}-{int(d):02d}"

    invoice.buyer_name, invoice.seller_name = _extract_names(text)

    tax_ids = TAX_ID_RE.findall(compact)
    if tax_ids:
        invoice.buyer_tax_id = tax_ids[0]
    if len(tax_ids) > 1:
        invoice.seller_tax_id = tax_ids[1]

    if match := SUBTOTAL_RE.search(compact):
        invoice.amount = _money(match.group(1))
        invoice.tax = _money(match.group(2))
    if match := LOWERCASE_TOTAL_RE.search(compact) or TOTAL_FALLBACK_RE.search(compact):
        invoice.total = _money(match.group(1))
    if invoice.tax is None and (match := TAX_ONLY_RE.search(compact)):
        invoice.tax = _money(match.group(1))
    if invoice.total is None and invoice.amount is not None and invoice.tax is not None:
        invoice.total = round(invoice.amount + invoice.tax, 2)
    if invoice.amount is None and invoice.total is not None and invoice.tax is not None:
        invoice.amount = round(invoice.total - invoice.tax, 2)
    if invoice.total is None and (match := ANY_MONEY_RE.search(compact)):
        invoice.total = _money(match.group(1))
    _fallback_scan(invoice, text, compact)
    return invoice


BARE_NUMBER_RE = re.compile(r"(?<!\d)(\d{20})(?!\d)")
BARE_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
BARE_TAX_ID_RE = re.compile(r"(?<![0-9A-Z])(\d{2}[0-9A-Z]{16})(?![0-9A-Z])")
COMPANY_RE = re.compile(
    r"[\u4e00-\u9fa5()（）]{3,30}?(?:分公司|有限公司|公司|门店|酒店|餐厅|饭店|超市|商行|中心|厂|店)"
)


def _fallback_scan(invoice: Invoice, text: str, compact: str) -> None:
    """标签与取值分离的版式（值画在别处）走无标签兜底。"""
    if not invoice.number and (match := BARE_NUMBER_RE.search(compact)):
        invoice.number = match.group(1)
    if not invoice.date and (match := BARE_DATE_RE.search(compact)):
        y, m, d = match.groups()
        invoice.date = f"{y}-{int(m):02d}-{int(d):02d}"
    if not invoice.buyer_tax_id or not invoice.seller_tax_id:
        ids = BARE_TAX_ID_RE.findall(compact)
        invoice.buyer_tax_id = invoice.buyer_tax_id or (ids[0] if ids else "")
        invoice.seller_tax_id = invoice.seller_tax_id or (ids[1] if len(ids) > 1 else "")
    if not invoice.buyer_name or not invoice.seller_name:
        for line in text.splitlines():
            names = COMPANY_RE.findall(line)
            if len(names) == 2:
                invoice.buyer_name = invoice.buyer_name or names[0]
                invoice.seller_name = invoice.seller_name or names[1]
                break


def _render_first_page(pdf_path: Path, dpi: int = 160) -> bytes:
    """自行渲染并显式关闭文档：外部模块不关句柄会锁住文件，导致后续改名失败。"""
    import io

    import pypdfium2 as pdfium
    from PIL import Image

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        image = doc[0].render(scale=dpi / 72.0).to_pil().convert("RGB")
    finally:
        doc.close()
    width, height = image.size
    if max(width, height) > 2600:
        ratio = 2600.0 / max(width, height)
        image = image.resize((int(width * ratio), int(height * ratio)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def _ocr_fill(invoice: Invoice, pdf_path: Path, ocr_dir) -> bool:
    """无文本层或字段残缺时调用外部 OCR 模块兜底，失败不影响主流程。"""
    if not ocr_dir:
        return False
    import sys

    ocr_dir = str(ocr_dir)
    if ocr_dir not in sys.path:
        sys.path.insert(0, ocr_dir)
    try:
        import baidu_ocr

        if pdf_path.suffix.lower() == ".pdf":
            image = _render_first_page(pdf_path)
        else:
            image = pdf_path.read_bytes()
        fields = baidu_ocr.parse_fields(baidu_ocr.ocr_image_bytes(image))
    except Exception as exc:
        log.warning("OCR 兜底失败 %s：%s", pdf_path.name, exc)
        return False

    invoice.number = invoice.number or fields.get("invoice_number", "")
    invoice.date = invoice.date or fields.get("invoice_date", "")
    invoice.buyer_name = invoice.buyer_name or fields.get("buyer_name", "")
    invoice.seller_name = invoice.seller_name or fields.get("seller_name", "")
    if invoice.amount is None:
        invoice.amount = fields.get("amount")
    if invoice.tax is None:
        invoice.tax = fields.get("tax")
    if invoice.total is None:
        invoice.total = fields.get("total")
    invoice.note = (invoice.note + "；" if invoice.note else "") + "OCR 识别"
    return True


def mark_missing(invoice: Invoice) -> Invoice:
    missing = [
        label
        for label, value in (("发票号码", invoice.number), ("价税合计", invoice.total), ("开票日期", invoice.date))
        if not value
    ]
    if missing:
        invoice.status = STATUS_REVIEW
        invoice.note = (invoice.note + "；" if invoice.note else "") + f"未提取到：{'、'.join(missing)}"
    return invoice


def parse_pdf(pdf_path: Path, ocr_dir=None) -> Invoice:
    pdf_path = Path(pdf_path)
    invoice = Invoice(file_path=pdf_path)
    invoice.file_sha1 = hashlib.sha1(pdf_path.read_bytes()).hexdigest()

    ext = pdf_path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg"):
        invoice.invoice_type = "图片版发票"
        _ocr_fill(invoice, pdf_path, ocr_dir)
        return mark_missing(invoice)

    if ext != ".pdf":
        invoice.invoice_type = ext.lstrip(".").upper()
        invoice.status = STATUS_REVIEW
        invoice.note = "非 PDF 格式，暂不解析，请手工核对"
        return invoice

    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        invoice.status = STATUS_REVIEW
        invoice.note = f"PDF 打不开：{exc}"
        return invoice

    fill_from_text(invoice, text)

    if not invoice.number or invoice.total is None:
        if parts := _read_qr(pdf_path):
            # 二维码里的金额是不含税金额，只用来补号码/代码/日期，避免污染价税合计
            invoice.code = invoice.code or parts[2]
            invoice.number = invoice.number or parts[3]
            if not invoice.date and len(parts[5]) == 8:
                invoice.date = f"{parts[5][:4]}-{parts[5][4:6]}-{parts[5][6:]}"

    if not (invoice.number and invoice.date and invoice.total is not None):
        _ocr_fill(invoice, pdf_path, ocr_dir)

    return mark_missing(invoice)
