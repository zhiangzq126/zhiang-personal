"""离线校准：用文本样例验证解析规则与 Excel 写入去重。
运行：python tests/test_parse.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from invoice_bot import excel, parser

SAMPLE_DIGITAL = """电子发票（普通发票）
发票号码：25442000000123456789
开票日期：2025年08月12日
购 名称：北京星辰科技有限公司                    销 名称：上海云帆网络科技有限公司
买 统一社会信用代码/纳税人识别号：91110108MA01ABCDEF  售 统一社会信用代码/纳税人识别号：91310115MA1K2LMNPQ
方                                               方
项目名称 规格型号 单位 数量 单价 金额 税率/征收率 税额
*信息技术服务*软件开发服务                1 1000.00 1000.00 6% 60.00
合 计 ¥1000.00 ¥60.00
价税合计（大写）壹仟零陆拾圆整 （小写）¥1060.00
"""

SAMPLE_LEGACY = """增值税电子普通发票
发票代码：011002000311
发票号码：12345678
开票日期：2024年03月05日
校验码：01234 56789 01234 56789
购 名称：北京星辰科技有限公司
买 纳税人识别号：91110108MA01ABCDEF
方 地址、电话：
  开户行及账号：
货物或应税劳务、服务名称 规格型号 单位 数量 单价 金额 税率 税额
*住宿服务*住宿费 1 471.70 471.70 6% 28.30
合 计 ¥471.70 ¥28.30
价税合计（大写）伍佰圆整 （小写）¥500.00
销 名称：北京如家酒店管理有限公司
售 纳税人识别号：911101085555AAAA1
方
"""

SAMPLE_TRAIN = """电子发票（铁路电子客票）
发票号码：25442000000987654321
开票日期：2025年07月01日
购买方名称：北京星辰科技有限公司
统一社会信用代码/纳税人识别号：91110108MA01ABCDEF
票价 ¥553.00
合 计 ¥507.34 ¥45.66
价税合计（大写）伍佰伍拾叁圆整 （小写）¥553.00
"""

SAMPLE_SELLER_ONLY = """增值税电子普通发票
发票号码：07285613
开票日期：2026年07月15日
销 售 方 名称:杭州云栖科技有限公司
纳税人识别号:91330100MA2ABCDEF1
货物或应税劳务、服务名称:*信息服务*云服务器租赁费
合 计 ¥850.00 ¥51.00
价税合计（大写）捌佰玖拾壹圆整 （小写）¥901.00
"""

SAMPLE_TIGHT_COLUMNS = """电子发票（普通发票）
发票号码：26952000003336983986
开票日期：2026年08月05日
购 名称:杭州诚云科技有限公司 销 名称:深圳市宝道嘉膳餐饮服务有限公司
项目名称 规格型号 单 位 数 量 单 价 金 额 税率/征收率 税 额
合 计 ¥182.18 ¥1.82
价税合计（大写）壹佰捌拾肆圆整 （小写）¥184.00
"""

CASES = [
    (
        "数电普票",
        SAMPLE_DIGITAL,
        {
            "invoice_type": "电子发票(普通发票)",
            "number": "25442000000123456789",
            "date": "2025-08-12",
            "buyer_name": "北京星辰科技有限公司",
            "seller_name": "上海云帆网络科技有限公司",
            "buyer_tax_id": "91110108MA01ABCDEF",
            "seller_tax_id": "91310115MA1K2LMNPQ",
            "amount": 1000.00,
            "tax": 60.00,
            "total": 1060.00,
            "status": parser.STATUS_OK,
        },
    ),
    (
        "增值税电子普通发票",
        SAMPLE_LEGACY,
        {
            "invoice_type": "增值税电子普通发票",
            "code": "011002000311",
            "number": "12345678",
            "date": "2024-03-05",
            "buyer_name": "北京星辰科技有限公司",
            "seller_name": "北京如家酒店管理有限公司",
            "amount": 471.70,
            "tax": 28.30,
            "total": 500.00,
            "status": parser.STATUS_OK,
        },
    ),
    (
        "铁路电子客票",
        SAMPLE_TRAIN,
        {
            "invoice_type": "铁路电子客票",
            "number": "25442000000987654321",
            "date": "2025-07-01",
            "buyer_name": "北京星辰科技有限公司",
            "total": 553.00,
            "status": parser.STATUS_OK,
        },
    ),
    (
        "只有销方标签+货物行",
        SAMPLE_SELLER_ONLY,
        {
            "number": "07285613",
            "date": "2026-07-15",
            "seller_name": "杭州云栖科技有限公司",
            "buyer_name": "",
            "total": 901.00,
            "status": parser.STATUS_OK,
        },
    ),
    (
        "双栏单空格粘连",
        SAMPLE_TIGHT_COLUMNS,
        {
            "number": "26952000003336983986",
            "date": "2026-08-05",
            "buyer_name": "杭州诚云科技有限公司",
            "seller_name": "深圳市宝道嘉膳餐饮服务有限公司",
            "total": 184.00,
            "status": parser.STATUS_OK,
        },
    ),
]


def check_parsing() -> int:
    failures = 0
    for name, text, expected in CASES:
        invoice = parser.mark_missing(
            parser.fill_from_text(parser.Invoice(file_path=Path(f"{name}.pdf")), text)
        )
        print(f"\n[{name}]")
        for field, want in expected.items():
            got = getattr(invoice, field)
            ok = got == want
            failures += 0 if ok else 1
            print(f"  {'PASS' if ok else 'FAIL'} {field}: {got!r}" + ("" if ok else f" (期望 {want!r})"))
    return failures


def check_scanned() -> int:
    invoice = parser.mark_missing(parser.fill_from_text(parser.Invoice(file_path=Path("scan.pdf")), ""))
    ok = invoice.status == parser.STATUS_REVIEW and "文本层" in invoice.note
    print(f"\n[无文本层] {'PASS' if ok else 'FAIL'} status={invoice.status} note={invoice.note}")
    return 0 if ok else 1


def check_excel() -> int:
    out = ROOT / "data" / "_test_invoices.xlsx"
    out.unlink(missing_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)

    first = parser.fill_from_text(parser.Invoice(file_path=ROOT / "a.pdf"), SAMPLE_DIGITAL)
    first.mail_subject = "8月打车发票"
    second = parser.fill_from_text(parser.Invoice(file_path=ROOT / "b.pdf"), SAMPLE_LEGACY)
    no_number = parser.Invoice(file_path=ROOT / "c.pdf", file_sha1="a" * 40, status=parser.STATUS_REVIEW)

    written = excel.append_invoices(out, [first, second, no_number])
    keys = excel.existing_keys(out)
    dedupe_ok = first.dedupe_key in keys and no_number.dedupe_key in keys
    again = excel.append_invoices(out, [i for i in (first, second) if i.dedupe_key not in keys])

    ok = written == 3 and dedupe_ok and again == 0
    print(
        f"\n[Excel] {'PASS' if ok else 'FAIL'} 首轮写入={written} 去重键命中={dedupe_ok} 二次写入={again}"
    )
    out.unlink(missing_ok=True)
    return 0 if ok else 1


if __name__ == "__main__":
    total = check_parsing() + check_scanned() + check_excel()
    print(f"\n{'全部通过' if total == 0 else f'失败 {total} 项'}")
    raise SystemExit(1 if total else 0)
