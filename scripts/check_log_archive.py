#!/usr/bin/env python3
"""check_log_archive.py — AI 工作日志「归档闸」：检查并（可选）执行节级归档。

规则来源：skill `life-manager` §2「归档机制」——节内**零未完成** 且 节日期**距今 ≥7 天**
⇒ 该节**整节**迁入同目录 `YYYY-MM-办结.md`（原文零改动、节序升序、做守恒校验）。

本脚本把这条规则做成**一条命令**：**默认只检查、不写盘**（等同 `--dry-run`），加 `--apply` 才执行。
动因：该规则原为「每次读日志须顺带执行」的**软约束**，靠执行方记性，实测有漏做；
按体系原则 **P2「工具执行的确定性边界」**——能用脚本搞定的，不交给模型自由发挥。

用法：
    python check_log_archive.py --log-dir "<工作日志目录>"
    python check_log_archive.py --log-dir "<工作日志目录>" --apply
    python check_log_archive.py --log-dir "<工作日志目录>" --json
    python check_log_archive.py --log-dir "<工作日志目录>" --today 2026-10-13 --threshold 7

另报告：历史月份遗留的**空壳待办文件**（零条目、仅剩表头）。
退出码：0 = 无需归档；1 = 存在应迁未迁；2 = 用法／环境错误；3 = 执行后守恒校验未过。

纯标准库、零依赖；不写死绝对路径（库根由 `--log-dir` 传入）。
"""
import argparse
import datetime
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SEC = re.compile(r"^## (\d{4}-\d{2}-\d{2})")
TODO_NAME = re.compile(r"^(\d{4}-\d{2})-待办\.md$")


def die(msg):
    sys.stderr.write("错误：%s\n" % msg)
    sys.exit(2)


def read_lines(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def write_lines(path, lines):
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def split_head_sections(lines):
    """→ (head, sections)；head = 首个日期节之前的行，sections = [{'date','lines'}]。"""
    head, secs, cur = [], [], None
    for ln in lines:
        m = SEC.match(ln)
        if m:
            if cur is not None:
                secs.append(cur)
            cur = {"date": m.group(1), "lines": [ln]}
        elif cur is None:
            head.append(ln)
        else:
            cur["lines"].append(ln)
    if cur is not None:
        secs.append(cur)
    return head, secs


def flatten(secs):
    out = []
    for s in secs:
        out.extend(s["lines"])
    return out


def tally(lines):
    done = sum(1 for l in lines if l.startswith("- [x]"))
    openn = sum(1 for l in lines if l.startswith("- [ ]"))
    return {"done": done, "open": openn, "lines": len(lines)}


def sec_open(sec):
    return sum(1 for l in sec["lines"] if l.startswith("- [ ]"))


def age_days(sec_date, today):
    y, m, d = (int(x) for x in sec_date.split("-"))
    return (today - datetime.date(y, m, d)).days


def done_path_for(log_dir, month):
    return os.path.join(log_dir, "%s-办结.md" % month)


def default_head(month, threshold):
    return [
        "# 04 AI Work · 工作日志 · %s · 办结" % month,
        "",
        "> 本文件为**已办结日期节**归档区。判定规则：节内零未完成 且 节日期距今 ≥%d 天（迁入时判定）。" % threshold,
        "> 语法与结构说明见同月 `%s-待办.md` 文件头；节序升序、**原文零改动**（仅整节搬移）。" % month,
        "> 读取提示：未完成待办必在当月文件（本文件恒零未完成），读待办时无需扫描本文件。",
        "",
    ]


def collect(log_dir):
    items, shells = [], []
    for name in sorted(os.listdir(log_dir)):
        m = TODO_NAME.match(name)
        if not m:
            continue
        path = os.path.join(log_dir, name)
        lines = read_lines(path)
        head, secs = split_head_sections(lines)
        if tally(lines)["lines"] and not secs:
            shells.append(name)
        items.append({"name": name, "path": path, "head": head,
                      "secs": secs, "month": m.group(1)})
    return items, shells


def do_apply(log_dir, items, threshold, today):
    moved, ok = 0, True
    for it in items:
        take, keep = [], []
        for sec in it["secs"]:
            if sec_open(sec) == 0 and age_days(sec["date"], today) >= threshold:
                take.append(sec)
            else:
                keep.append(sec)
        if not take:
            continue
        dpath = done_path_for(log_dir, it["month"])
        if os.path.exists(dpath):
            dlines = read_lines(dpath)
            dhead, dsecs = split_head_sections(dlines)
        else:
            dhead, dsecs = default_head(it["month"], threshold), []
        b_act = tally(read_lines(it["path"]))
        b_done = tally(read_lines(dpath)) if os.path.exists(dpath) else {"done": 0, "open": 0}
        merged = sorted(dsecs + take, key=lambda s: s["date"])
        write_lines(dpath, dhead + flatten(merged))
        write_lines(it["path"], it["head"] + flatten(keep))
        a_act = tally(read_lines(it["path"]))
        a_done = tally(read_lines(dpath))
        if (b_act["done"] + b_done["done"] != a_act["done"] + a_done["done"] or
                b_act["open"] + b_done["open"] != a_act["open"] + a_done["open"]):
            ok = False
        moved += len(take)
    return moved, ok


def report(result, as_json):
    if as_json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return
    sys.stdout.write("归档闸 · %s（阈值 %d 天 · 今天 %s）\n"
                     % (result["log_dir"], result["threshold"], result["today"]))
    if result["candidates"]:
        sys.stdout.write("应迁未迁 %d 节：\n" % len(result["candidates"]))
        for c in result["candidates"]:
            sys.stdout.write("  %s  %s  %d 行\n" % (c["file"], c["date"], c["lines"]))
    else:
        sys.stdout.write("应迁未迁 0 节 —— 无需归档\n")
    if result["leftover_shells"]:
        sys.stdout.write("历史月份空壳待办文件 %d 个（零条目，可清理）：%s\n"
                         % (len(result["leftover_shells"]), "、".join(result["leftover_shells"])))
    if result["applied"]:
        sys.stdout.write("已迁 %d 节；守恒校验 %s\n"
                         % (result["moved_sections"],
                            "通过" if result.get("conservation_ok") else "未通过"))


def main():
    ap = argparse.ArgumentParser(
        description="AI 工作日志归档闸：默认只检查（--dry-run 为默认行为），--apply 才执行迁移")
    ap.add_argument("--log-dir", required=True, help="工作日志目录（内含 YYYY-MM-待办.md）")
    ap.add_argument("--apply", action="store_true", help="执行迁移；缺省仅检查")
    ap.add_argument("--dry-run", action="store_true", help="显式声明只检查（默认行为，与 --apply 互斥）")
    ap.add_argument("--threshold", type=int, default=7, help="归档龄期阈值（天），默认 7")
    ap.add_argument("--today", default=None, help="以指定日期为今天（YYYY-MM-DD；复核／回放用）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args()

    if args.apply and args.dry_run:
        die("--apply 与 --dry-run 互斥")
    if args.threshold < 0:
        die("--threshold 不能为负")
    log_dir = os.path.abspath(args.log_dir)
    if not os.path.isdir(log_dir):
        die("--log-dir 不是目录：%s" % log_dir)
    try:
        today = datetime.date.fromisoformat(args.today) if args.today else datetime.date.today()
    except ValueError:
        die("--today 应为 YYYY-MM-DD")

    items, shells = collect(log_dir)
    cands = []
    for it in items:
        for sec in it["secs"]:
            if sec_open(sec) == 0 and age_days(sec["date"], today) >= args.threshold:
                cands.append({"file": it["name"], "date": sec["date"], "lines": len(sec["lines"])})

    result = {
        "log_dir": log_dir,
        "today": today.isoformat(),
        "threshold": args.threshold,
        "candidates": cands,
        "leftover_shells": shells,
        "applied": False,
        "moved_sections": 0,
    }

    if not args.apply:
        result["exit"] = 1 if cands else 0
        report(result, args.json)
        sys.exit(result["exit"])

    if not cands:
        result["exit"] = 0
        report(result, args.json)
        sys.exit(0)

    moved, ok = do_apply(log_dir, items, args.threshold, today)
    result["applied"] = True
    result["moved_sections"] = moved
    result["conservation_ok"] = ok
    result["exit"] = 0 if ok else 3
    report(result, args.json)
    sys.exit(result["exit"])


if __name__ == "__main__":
    main()
