"""报销发票收集器：扫邮箱 → 下载发票 → 解析字段 → 追加汇总 Excel。

用法：
    python run.py run                 # 全流程
    python run.py run --dry-run       # 只看邮件命中情况，不下载不写表
    python run.py parse-dir data/pdf  # 只解析本地已有 PDF，用于校准解析规则
"""

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from invoice_bot import excel, fetcher, mailbox, parser
from invoice_bot.config import ConfigError, load_config

log = logging.getLogger("invoice_bot")

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    logfile = log_dir / f"run-{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(logfile, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def load_state(path: Path) -> Dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("state.json 损坏，按首次运行处理")
    return {}


def save_state(path: Path, state: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_name(value: str, limit: int = 40) -> str:
    return ILLEGAL_CHARS.sub("_", value).strip(" ._")[:limit] or "unknown"


def final_path(pdf_dir: Path, invoice) -> Path:
    month = (invoice.date or invoice.mail_date or "0000-00")[:7]
    stem = "_".join(
        filter(
            None,
            [
                invoice.date or "无日期",
                safe_name(invoice.seller_name, 20),
                f"{invoice.total:.2f}" if invoice.total is not None else "",
                invoice.number or invoice.file_sha1[:8],
            ],
        )
    )
    target_dir = pdf_dir / month
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{safe_name(stem, 90)}{invoice.file_path.suffix.lower()}"


def stage_and_parse(pdf_dir: Path, filename: str, payload: bytes, meta: Dict, source: str, ocr_dir=None):
    tmp_dir = pdf_dir / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix.lower() or ".pdf"
    tmp_path = tmp_dir / f"{datetime.now():%H%M%S%f}{suffix}"
    tmp_path.write_bytes(payload)

    invoice = parser.parse_pdf(tmp_path, ocr_dir)
    invoice.source = source
    invoice.mail_subject = meta.get("subject", "")
    invoice.mail_sender = meta.get("sender", "")
    invoice.mail_date = meta.get("date", "")
    return invoice


def commit(invoice, pdf_dir: Path, seen_keys: set) -> bool:
    if invoice.dedupe_key in seen_keys:
        log.info("跳过重复发票 %s", invoice.dedupe_key)
        invoice.file_path.unlink(missing_ok=True)
        return False
    seen_keys.add(invoice.dedupe_key)
    target = final_path(pdf_dir, invoice)
    try:
        invoice.file_path.replace(target)
    except OSError:
        shutil.copy2(invoice.file_path, target)
        try:
            invoice.file_path.unlink()
        except OSError:
            log.debug("临时文件暂时删不掉：%s", invoice.file_path)
    invoice.file_path = target
    log.info("入库 %s | %s | %s", invoice.number or "无号", invoice.total, target.name)
    return True


def process_payload(cfg, filename, payload, meta, source, seen_keys, collected,
                    invoice_since=None, invoice_until=None) -> None:
    docs = mailbox.expand(filename, payload)
    if not docs:
        log.info("跳过非发票文件：%s", filename)
        return
    for doc in docs:
        try:
            invoice = stage_and_parse(cfg.pdf_dir, doc.filename, doc.payload, meta, source, cfg.ocr_dir)
            if (invoice_since or invoice_until) and not _in_scope(invoice, invoice_since, invoice_until):
                invoice.file_path.unlink(missing_ok=True)
                continue
            if commit(invoice, cfg.pdf_dir, seen_keys):
                collected.append(invoice)
        except Exception as exc:
            log.error("处理失败 %s：%s", doc.filename, exc)


def _in_scope(invoice, since=None, until=None) -> bool:
    """按开票日期过滤：无日期、早于 since、晚于 until 都算超范围。"""
    if not invoice.date:
        log.info("超范围(无开票日期，跳过)：%s", invoice.file_path.name)
        return False
    try:
        d = datetime.strptime(invoice.date, "%Y-%m-%d").date()
    except ValueError:
        log.info("超范围(日期无法解析)：%s", invoice.date)
        return False
    if since and d < since:
        log.info("超范围(%s 早于 %s)：%s", invoice.date, since, invoice.number or invoice.file_path.name)
        return False
    if until and d > until:
        log.info("超范围(%s 晚于 %s)：%s", invoice.date, until, invoice.number or invoice.file_path.name)
        return False
    return True


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    setup_logging(cfg.log_dir)

    state = load_state(cfg.state_path)
    seen_keys = excel.existing_keys(cfg.excel_path)
    collected: List = []
    pending_browser: List[Tuple[str, Dict]] = []
    unresolved: List[Tuple[str, str]] = []

    for mb_cfg in cfg.mailboxes:
        account_key = f"{mb_cfg.email}|{mb_cfg.folder}"
        account_state = state.setdefault(account_key, {"seen_uids": []})
        seen_uids = set(account_state["seen_uids"])

        try:
            mails = list(mailbox.fetch_mails(mb_cfg, cfg, seen_uids, limit=args.limit, since=args.since,
                                             mail_since=args.mail_since, mail_until=args.mail_until))
        except Exception as exc:
            log.error("[%s] 收件失败：%s", mb_cfg.name, exc)
            continue

        for item in mails:
            meta = {"subject": item.subject, "sender": item.sender, "date": item.date, "uid": item.uid,
                    "account": account_key}
            if args.dry_run:
                continue

            for att in item.attachments:
                try:
                    process_payload(cfg, att.filename, att.payload, meta, "附件", seen_keys, collected, args.invoice_since, args.invoice_until)
                except Exception as exc:
                    log.error("附件处理失败 %s：%s", att.filename, exc)

            fetched_from_link = False
            for _text, url in item.links:
                result = fetcher.fetch_direct(url, cfg.http_timeout)
                if result:
                    process_payload(cfg, result.filename, result.payload, meta, "链接", seen_keys, collected, args.invoice_since, args.invoice_until)
                    fetched_from_link = True
                    break
                if cfg.use_browser:
                    pending_browser.append((url, meta))
                else:
                    log.info("链接需人工处理：%s（%s）", url, result.note)
            if fetched_from_link:
                pending_browser = [e for e in pending_browser if e[1]["uid"] != item.uid]

            seen_uids.add(item.uid)

        account_state["seen_uids"] = sorted(seen_uids)

    if args.dry_run:
        log.info("dry-run 结束，未下载任何文件、未写 Excel")
        return 0

    if pending_browser:
        deferred = pending_browser[args.max_browser :]
        pending_browser = pending_browser[: args.max_browser]
        for url, meta in deferred:
            unresolved.append((meta["subject"], url))
            account_state = state.get(meta["account"])
            if account_state and meta["uid"] in account_state["seen_uids"]:
                account_state["seen_uids"].remove(meta["uid"])
        if deferred:
            log.info("本轮浏览器上限 %d，推迟 %d 个链接到下次运行", args.max_browser, len(deferred))

        if pending_browser:
            log.info("有 %d 个链接需要浏览器，正在启动", len(pending_browser))
            urls = [url for url, _ in pending_browser]
            metas = {url: meta for url, meta in pending_browser}
            try:
                browser_results = fetcher.fetch_with_browser(
                    urls, cfg.browser_profile, cfg.browser_timeout, channel=cfg.browser_channel
                )
            except Exception as exc:
                log.error("浏览器取票整体失败，本轮跳过链接：%s", exc)
                browser_results = []
            for url, result in browser_results:
                meta = metas[url]
                if result:
                    process_payload(cfg, result.filename, result.payload, meta, "链接", seen_keys, collected, args.invoice_since, args.invoice_until)
                else:
                    log.warning("取票失败，下次运行会重试：%s（%s）", url, result.note)
                    unresolved.append((meta["subject"], url))
                    account_state = state.get(meta["account"])
                    if account_state and meta["uid"] in account_state["seen_uids"]:
                        account_state["seen_uids"].remove(meta["uid"])

    excel.append_invoices(cfg.excel_path, collected)
    save_state(cfg.state_path, state)

    if unresolved:
        pending_path = cfg.excel_path.parent / "pending-links.txt"
        pending_path.write_text(
            "\n".join(f"{subject} → {url}" for subject, url in unresolved), encoding="utf-8"
        )
        log.info("另有 %d 个链接需手工处理，清单：%s", len(unresolved), pending_path)

    review = [i for i in collected if i.status == parser.STATUS_REVIEW]
    log.info("完成：新增 %d 张发票，其中 %d 张需人工复核", len(collected), len(review))
    for invoice in review:
        log.info("  待复核 %s：%s", invoice.file_path.name, invoice.note)
    return 0


def cmd_parse_dir(args) -> int:
    cfg = load_config(args.config)
    setup_logging(cfg.log_dir)

    target = Path(args.directory)
    if not target.exists():
        log.error("目录不存在：%s", target)
        return 1

    seen_keys = excel.existing_keys(cfg.excel_path)
    collected = []
    for path in sorted(list(target.rglob("*.pdf")) + list(target.rglob("*.ofd"))):
        if "_tmp" in path.parts:
            continue
        invoice = parser.parse_pdf(path, cfg.ocr_dir)
        invoice.source = "本地"
        if invoice.dedupe_key in seen_keys:
            log.info("跳过已入表 %s", path.name)
            continue
        seen_keys.add(invoice.dedupe_key)
        collected.append(invoice)
        log.info(
            "%s → 号码=%s 日期=%s 销方=%s 合计=%s 状态=%s",
            path.name, invoice.number or "-", invoice.date or "-",
            invoice.seller_name or "-", invoice.total, invoice.status,
        )

    excel.append_invoices(cfg.excel_path, collected)
    log.info("解析完成：新增 %d 条", len(collected))
    return 0


def cmd_folders(args) -> int:
    cfg = load_config(args.config)
    setup_logging(cfg.log_dir)

    for mb_cfg in cfg.mailboxes:
        try:
            names = mailbox.list_folders(mb_cfg)
        except Exception as exc:
            log.error("[%s] 连接失败：%s", mb_cfg.name, exc)
            continue
        log.info("[%s] 共 %d 个文件夹：", mb_cfg.name, len(names))
        for name in names:
            mark = "  <-- 当前配置" if name == mb_cfg.folder else ""
            log.info("    %s%s", name, mark)
    return 0


def main() -> int:
    root = Path(__file__).parent
    ap = argparse.ArgumentParser(description="报销发票收集器")
    ap.add_argument("--config", default=str(root / "config.yaml"))
    sub = ap.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="扫邮箱并写入汇总表")
    run_cmd.add_argument("--dry-run", action="store_true", help="只看命中情况")
    run_cmd.add_argument(
        "--since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="只处理该日期(含)之后收到的邮件，格式 YYYY-MM-DD",
    )
    run_cmd.add_argument(
        "--invoice-since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="只保留开票日期(含)不早于该日的发票，无日期一律跳过，格式 YYYY-MM-DD",
    )
    run_cmd.add_argument(
        "--invoice-until",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="只保留开票日期(含)不晚于该日的发票，格式 YYYY-MM-DD",
    )
    run_cmd.add_argument(
        "--mail-since",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="只处理邮件 Date 头(含)不早于该日的邮件，格式 YYYY-MM-DD",
    )
    run_cmd.add_argument(
        "--mail-until",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="只处理邮件 Date 头(含)不晚于该日的邮件，格式 YYYY-MM-DD",
    )
    run_cmd.add_argument("--limit", type=int, default=None, help="只处理最新 N 封邮件")
    run_cmd.add_argument("--max-browser", type=int, default=20, help="本轮最多用浏览器取几个链接")
    run_cmd.set_defaults(func=cmd_run)

    parse_cmd = sub.add_parser("parse-dir", help="解析本地目录里的发票")
    parse_cmd.add_argument("directory")
    parse_cmd.set_defaults(func=cmd_parse_dir)

    folders_cmd = sub.add_parser("folders", help="列出邮箱里的文件夹名")
    folders_cmd.set_defaults(func=cmd_folders)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"配置有问题：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
