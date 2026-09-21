# -*- coding: utf-8 -*-
"""百度云增值税发票识别 OCR 模块 + CLI。

用法:
    python baidu_ocr.py <发票PDF或图片> [页码,从0开始]
    输出识别到的结构化字段 JSON。

作为模块:
    from baidu_ocr import ocr_invoice_file, parse_fields
    raw = ocr_invoice_file("xx.pdf")      # 返回百度 words_result
    fields = parse_fields(raw)            # 归一化成标准字段

凭据读取顺序: 环境变量 INVOICE_OCR_CONFIG -> 本技能根目录 ocr-config.json
              -> ~/.qoderwork/skills/invoice-summary/ocr-config.json（兼容旧位置）
access_token 缓存在本脚本同目录 .ocr-token-cache.json（有效期内复用，不重复请求）。
"""
import base64
import io
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CONFIG_CANDIDATES = [
    os.path.join(SKILL_ROOT, "ocr-config.json"),
    os.path.join(os.path.expanduser("~"), ".qoderwork", "skills", "invoice-summary", "ocr-config.json"),
]
TOKEN_CACHE = os.path.join(HERE, ".ocr-token-cache.json")
TIMEOUT = 60


class OcrError(RuntimeError):
    pass


def load_config():
    path = os.environ.get("INVOICE_OCR_CONFIG")
    if not path:
        path = next((p for p in CONFIG_CANDIDATES if os.path.exists(p)), None)
    if not path or not os.path.exists(path):
        raise OcrError("未找到 OCR 配置（ocr-config.json）；请复制 ocr-config.example.json 并填入百度凭据")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("api_key") or not cfg.get("secret_key"):
        raise OcrError("OCR 配置缺少 api_key / secret_key")
    return cfg


def get_access_token(cfg):
    # 缓存命中且未过期（提前 1 天失效）
    if os.path.exists(TOKEN_CACHE):
        try:
            with open(TOKEN_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("access_token") and cache.get("expires_at", 0) > time.time() + 86400:
                return cache["access_token"]
        except Exception:
            pass
    resp = requests.post(
        cfg["token_url"],
        params={
            "grant_type": "client_credentials",
            "client_id": cfg["api_key"],
            "client_secret": cfg["secret_key"],
        },
        timeout=TIMEOUT,
    )
    data = json.loads(resp.content.decode("utf-8"))
    if "access_token" not in data:
        raise OcrError("获取 access_token 失败: %s" % json.dumps(data, ensure_ascii=False))
    try:
        with open(TOKEN_CACHE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "access_token": data["access_token"],
                    "expires_at": time.time() + int(data.get("expires_in", 2592000)),
                },
                f,
            )
    except Exception:
        pass
    return data["access_token"]


def _call_vat_invoice(cfg, token, image_bytes):
    resp = requests.post(
        cfg["vat_invoice_url"],
        params={"access_token": token},
        data={"image": base64.b64encode(image_bytes).decode("ascii"), "location": "false"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=TIMEOUT,
    )
    # 响应体是 UTF-8，但响应头常不带 charset，须显式按 UTF-8 解码，否则中文乱码
    data = json.loads(resp.content.decode("utf-8"))
    if "error_code" in data:
        raise OcrError(
            "OCR 接口报错 error_code=%s: %s" % (data.get("error_code"), data.get("error_msg"))
        )
    return data.get("words_result", {}) or {}


def ocr_image_bytes(image_bytes):
    cfg = load_config()
    token = get_access_token(cfg)
    return _call_vat_invoice(cfg, token, image_bytes)


def pdf_page_to_image(pdf_path, page_index=0, dpi=160):
    """渲染 PDF 单页为 JPEG 字节。

    百度接口要求图片 base64 后 < 4MB，故不用 PNG：
    160dpi + JPEG(90) 通常仅几百 KB，且 OCR 精度足够。
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_path)
    if page_index >= len(doc):
        raise OcrError("页码超出范围: %s 共 %d 页" % (pdf_path, len(doc)))
    pil = doc[page_index].render(scale=dpi / 72.0).to_pil().convert("RGB")
    # 长边限制，防止超大图
    w, h = pil.size
    if max(w, h) > 2600:
        ratio = 2600.0 / max(w, h)
        pil = pil.resize((int(w * ratio), int(h * ratio)))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def ocr_invoice_file(path, page_index=0):
    """PDF 渲染成图片后识别；图片文件直接识别。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        img = pdf_page_to_image(path, page_index)
    else:
        with open(path, "rb") as f:
            img = f.read()
    return ocr_image_bytes(img)


# ---------- 字段归一化 ----------

def _first(words, keys):
    for k in keys:
        v = words.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _to_number(s):
    s = re.sub(r"[¥￥,，\s元]", "", s or "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_fields(words):
    """把百度 words_result 归一化成汇总表所需标准字段。

    百度增值税发票识别返回英文键名，中文键名仅作兜底。
    """
    date_raw = _first(words, ["InvoiceDate", "开票日期", "机打开票日期"])
    m = re.search(r"(\d{4})\D*(\d{1,2})\D*(\d{1,2})", date_raw)
    if m:
        date_iso = "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    elif re.fullmatch(r"\d{8}", date_raw):
        date_iso = "%s-%s-%s" % (date_raw[0:4], date_raw[4:6], date_raw[6:8])
    else:
        date_iso = date_raw

    amount = _to_number(_first(words, ["TotalAmount", "合计金额", "金额合计", "不含税金额"]))
    tax = _to_number(_first(words, ["TotalTax", "合计税额", "税额合计"]))
    total = _to_number(
        _first(words, ["AmountInFiguers", "AmountInFigures", "价税合计", "价税合计(小写)", "小写"])
    )

    # 货物名称来自 CommodityName 数组（[{row, word}]）
    item_parts = []
    for it in words.get("CommodityName") or []:
        w = (it or {}).get("word", "").strip()
        if w:
            item_parts.append(w)
    item_desc = "；".join(item_parts)

    return {
        "invoice_number": _first(words, ["InvoiceNum", "InvoiceNumDigit", "发票号码", "机打发票号码"]),
        "invoice_date": date_iso,
        "seller_name": _first(words, ["SellerName", "销售方名称", "销售方", "销方名称"]),
        "buyer_name": _first(words, ["PurchaserName", "购买方名称", "购方名称", "购买方"]),
        "amount": amount,
        "tax": tax,
        "total": total,
        "invoice_type": _first(words, ["InvoiceType", "发票类型", "类型"]),
        "item_description": item_desc,
        "ocr": True,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    target = sys.argv[1]
    pg = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    try:
        raw = ocr_invoice_file(target, pg)
    except OcrError as e:
        print("OCR_FAIL: %s" % e, file=sys.stderr)
        sys.exit(2)
    fields = parse_fields(raw)
    print(json.dumps(fields, ensure_ascii=False, indent=2))
