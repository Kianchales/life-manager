#!/usr/bin/env python3
"""monthly_review.py — 工作日志月度回顾生成器：把一个月的日志节压成一份速览。

数据源（`--log-dir` 指向库内 `04 AI Work/工作日志`）：
    <月>-待办.md  活跃文件（承载未完成 + 近 7 天节）
    <月>-办结.md  归档区（7 天前的节）
两文件**同月节合并**统计——节按「节日期」归月，两文件都必读
（满 7 天的节已迁入办结文件，少读一个就漏统计）。

语法（v3，见日志文件头）：
    节标题 `## YYYY-MM-DD（可选·主题）`，节内分 `### ✅ 已完成` / `### ⏳ 待办`
    完成行 `- [x] 标题 ✅ YYYY-MM-DD #性质`
    待办行 `- [ ] 标题 #性质`（`📅 YYYY-MM-DD` 为截止日，可选）
    性质标签：#体系搭建 / #skill开发 / #文档写作 / #项目跟进 / #研究学习 / #其他

产物（默认**只打印不写盘**；`--out <path>` 才落文件）：一份 markdown 速览——
    总览（记录天数／完成／未完成／逾期）· 性质分布 · 最活跃的若干天 ·
    未完成清单 · 本月主线（摘自文件头，有则回显）。

用法：
    python monthly_review.py --log-dir "<库根>/04 AI Work/工作日志"                # 默认上一月
    python monthly_review.py --log-dir "<库根>/04 AI Work/工作日志" --month 2026-09
    python monthly_review.py --log-dir "<库根>/04 AI Work/工作日志" --month 2026-09 --out review.md

退出码：0 成功（含该月节数为零）；2 用法/环境错误；3 该月日志文件均不存在。
写盘用 LF 行尾、UTF-8。零第三方依赖（仅标准库）。
"""
import argparse
import datetime
import io
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SEC_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*(?:（(.*?)）)?\s*$")
DONE_RE = re.compile(r"^-\s*\[[xX]\]\s*(.*)$")
OPEN_RE = re.compile(r"^-\s*\[\s*\]\s*(.*)$")
CHECK_RE = re.compile(r"✅\s*\d{4}-\d{2}-\d{2}")
DUE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
TAG_RE = re.compile(r"#([^\s#]+)")
HEADLINE_RE = re.compile(r"📌\s*本月主线")

FIXED = ("体系搭建", "skill开发", "文档写作", "项目跟进", "研究学习", "其他")
TOP_N = 5


def die(msg, code=2):
    sys.stderr.write("错误：%s\n" % msg)
    sys.exit(code)


def read_text(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def split_body(body):
    """任务行正文 → {text, tags, due}：剥掉完成日期／截止日／已知性质标签。"""
    due = DUE_RE.search(body)
    tags = [t for t in TAG_RE.findall(body) if t in FIXED]
    text = CHECK_RE.sub("", body)
    text = DUE_RE.sub("", text)
    text = TAG_RE.sub(lambda m: "" if m.group(1) in FIXED else m.group(0), text)
    text = re.sub(r"\s+", " ", text).strip().strip("·|—-—").strip()
    return {"text": text, "tags": tags, "due": due.group(1) if due else ""}


def parse_sections(text):
    """逐行扫描：只在节标题之后收集 `- [x]` / `- [ ]` 行，天然跳过文件头说明。"""
    secs, cur = [], None
    for ln in text.splitlines():
        m = SEC_RE.match(ln)
        if m:
            cur = {"date": m.group(1), "title": (m.group(2) or "").strip(),
                   "done": [], "open": []}
            secs.append(cur)
            continue
        if cur is None:
            continue
        dm = DONE_RE.match(ln)
        if dm:
            cur["done"].append(split_body(dm.group(1)))
            continue
        om = OPEN_RE.match(ln)
        if om:
            cur["open"].append(split_body(om.group(1)))
    return secs


def parse_mainline(text):
    """抓文件头「📌 本月主线」后的连续引言块（可无）。"""
    out, hit = [], False
    for ln in text.splitlines():
        if HEADLINE_RE.search(ln):
            hit = True
            continue
        if hit:
            if ln.startswith(">"):
                out.append(ln.lstrip("> ").rstrip())
            elif ln.strip() == "":
                if out:
                    break
            else:
                break
    return "\n".join(out).strip()


def load_month(log_dir, ym):
    """→ (sections, mainline, files_used)；合并同月两文件。"""
    files = ["%s-待办.md" % ym, "%s-办结.md" % ym]
    used, secs, mainline = [], [], ""
    for fn in files:
        p = os.path.join(log_dir, fn)
        if os.path.isfile(p):
            t = read_text(p)
            used.append(fn)
            secs.extend(parse_sections(t))
            if not mainline:
                mainline = parse_mainline(t)
    secs.sort(key=lambda s: s["date"])
    return secs, mainline, used


def render(ym, secs, mainline, used, today, top_n=TOP_N):
    n_days = len(secs)
    done = [d for s in secs for d in s["done"]]
    opens = [(s["date"], o) for s in secs for o in s["open"]]
    overdue = [x for x in opens if x[1]["due"] and x[1]["due"] < today.isoformat()]

    tag_count = {}
    untag = 0
    for d in done:
        if d["tags"]:
            for t in d["tags"]:
                tag_count[t] = tag_count.get(t, 0) + 1
        else:
            untag += 1

    L = []
    L.append("# %s 月度回顾" % ym)
    L.append("")
    L.append("> 数据源：%s ｜ 生成于 %s" % (
        " ＋ ".join(used) if used else "（无）", today.isoformat()))
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append("| 记录天数（有节的日期） | %d 天 |" % n_days)
    L.append("| 已完成 | %d 条 |" % len(done))
    L.append("| 未完成 | %d 条 |" % len(opens))
    L.append("| 其中逾期（截止日早于生成日） | %d 条 |" % len(overdue))
    L.append("")

    L.append("## 性质分布")
    L.append("")
    if done:
        L.append("| 性质 | 完成数 | 占比 |")
        L.append("|---|---|---|")
        total = len(done)
        for t, c in sorted(tag_count.items(), key=lambda kv: (-kv[1], kv[0])):
            L.append("| #%s | %d | %.1f%% |" % (t, c, 100.0 * c / total))
        if untag:
            L.append("| （未标注） | %d | %.1f%% |" % (untag, 100.0 * untag / total))
        L.append("| **合计** | **%d** | **100%%** |" % total)
    else:
        L.append("（本月无已完成条目）")
    L.append("")

    L.append("## 最活跃的 %d 天" % top_n)
    L.append("")
    active = sorted([s for s in secs if s["done"]],
                    key=lambda s: (-len(s["done"]), s["date"]))[:top_n]
    if active:
        L.append("| 日期 | 主题 | 完成数 |")
        L.append("|---|---|---|")
        for s in active:
            L.append("| %s | %s | %d |" % (s["date"], s["title"] or "—", len(s["done"])))
    else:
        L.append("（本月无已完成条目）")
    L.append("")

    L.append("## 未完成清单")
    L.append("")
    if opens:
        L.append("| 节日期 | 事项 | 截止 | 性质 |")
        L.append("|---|---|---|---|")
        for date, o in opens:
            mark = " ⚠" if (o["due"] and o["due"] < today.isoformat()) else ""
            L.append("| %s | %s | %s | %s |" % (
                date, o["text"] or "—", (o["due"] or "—") + mark,
                ("、".join("#" + t for t in o["tags"]) or "—")))
    else:
        L.append("（本月无未完成条目）")
    L.append("")

    if mainline:
        L.append("## 本月主线（摘自日志文件头）")
        L.append("")
        L.append(mainline)
        L.append("")

    return "\n".join(L).rstrip() + "\n"


def prev_month(today):
    y, m = today.year, today.month
    return "%04d-%02d" % (y - 1, 12) if m == 1 else "%04d-%02d" % (y, m - 1)


def main():
    ap = argparse.ArgumentParser(description="工作日志月度回顾生成器")
    ap.add_argument("--log-dir", required=True, help="工作日志目录（…/04 AI Work/工作日志）")
    ap.add_argument("--month", default=None, help="目标月份 YYYY-MM（默认上一月）")
    ap.add_argument("--out", default=None, help="写盘路径（默认只打印不写盘）")
    ap.add_argument("--top", type=int, default=TOP_N, help="最活跃天数（默认 %d）" % TOP_N)
    args = ap.parse_args()

    log_dir = os.path.abspath(args.log_dir)
    if not os.path.isdir(log_dir):
        die("日志目录不存在：%s" % log_dir)

    today = datetime.date.today()
    ym = args.month or prev_month(today)
    if not re.match(r"^\d{4}-\d{2}$", ym):
        die("--month 需为 YYYY-MM：%s" % ym)

    secs, mainline, used = load_month(log_dir, ym)
    if not used:
        die("该月日志文件均不存在：%s / %s" % (
            os.path.join(log_dir, "%s-待办.md" % ym),
            os.path.join(log_dir, "%s-办结.md" % ym)), code=3)

    report = render(ym, secs, mainline, used, today, args.top)

    if args.out:
        out = os.path.abspath(args.out)
        parent = os.path.dirname(out)
        if parent and not os.path.isdir(parent):
            die("输出目录不存在：%s" % parent)
        with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(report)
        n_done = sum(len(s["done"]) for s in secs)
        print("已写入：%s（%s，%d 天／%d 条完成）" % (out, ym, len(secs), n_done))
        sys.exit(0)

    sys.stdout.write(report)
    sys.exit(0)


if __name__ == "__main__":
    main()
