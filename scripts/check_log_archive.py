#!/usr/bin/env python3
"""check_log_archive.py — AI 工作日志「归档闸」：检查并（可选）执行节级归档（含未完成回流）。

规则来源：skill `life-manager` §2「归档机制」——
  ① 节内**零未完成** 且 节日期**距今 ≥7 天** ⇒ 该节**整节**迁入同目录 `YYYY-MM-办结.md`；
  ② **未完成回流**：满龄节若含未完成项，**先**把这些项承接至当月**最新节**的 `⏳` 段
     （条目末尾标「承接自 <日期> 节」），**原节该条去掉状态位**（`- [ ] X` → `- X ｜ 未完 · 已承接至 <日期> 节`）
     ⇒ 该节归零后照常迁出。由此同时保住两条承诺：**未完成必在当月文件**、
     **办结的日期节恒零未完成**；原文不删，仅去状态位（故「原文零改动」精确为**除回流项状态位外**）。

本脚本把规则做成**一条命令**：**默认只检查、不写盘**（等同 `--dry-run`），加 `--apply` 才执行。
动因：该规则原为「每次读日志须顺带执行」的**软约束**，靠执行方记性，实测有漏做；
按体系原则 **P2「工具执行的确定性边界」**——能用脚本搞定的，不交给模型自由发挥。

用法：
    python check_log_archive.py --log-dir "<工作日志目录>"
    python check_log_archive.py --log-dir "<工作日志目录>" --apply
    python check_log_archive.py --log-dir "<工作日志目录>" --json
    python check_log_archive.py --log-dir "<工作日志目录>" --apply --no-carry-over
    python check_log_archive.py --log-dir "<工作日志目录>" --today 2026-10-20 --threshold 7

另报告：历史月份遗留的**空壳待办文件**（零日期节、仅剩表头）。
退出码：0 = 无需归档；1 = 存在应迁未迁；2 = 用法／环境错误；3 = 执行后守恒校验未过。

纯标准库、零依赖；不写死绝对路径（库根由 `--log-dir` 传入）。
"""
import argparse
import copy
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
PLACEHOLDERS = ("（无）", "（暂无）", "（暂无 · 新增待办后按格式写入）")


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
        "> 语法与结构说明见同月 `%s-待办.md` 文件头；节序升序、**除回流项状态位外原文零改动**（仅整节搬移）。" % month,
        "> 读取提示：未完成待办必在当月文件（本文件日期节恒零未完成），读待办时无需扫描本文件。",
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


def carry_over_sections(secs, threshold, today):
    """把满龄节的未完成项承接至当月最新节；就地改 secs，返回承接条数。"""
    if len(secs) < 2:
        return 0
    latest = max(secs, key=lambda s: s["date"])
    carried = 0
    for sec in secs:
        if sec is latest or age_days(sec["date"], today) < threshold:
            continue
        opens = [l for l in sec["lines"] if l.startswith("- [ ]")]
        if not opens:
            continue
        sec["lines"] = ["- " + l[6:] + " ｜ 未完 · 已承接至 %s 节" % latest["date"]
                        if l.startswith("- [ ]") else l for l in sec["lines"]]
        add = ["- [ ] " + l[6:] + "（承接自 %s 节）" % sec["date"] for l in opens]
        j = len(latest["lines"]) - 1
        while j >= 0 and not latest["lines"][j].strip():
            j -= 1
        body, tail = latest["lines"][:j + 1], latest["lines"][j + 1:]
        if body and body[-1].strip() in PLACEHOLDERS:
            body = body[:-1]
        latest["lines"] = body + [""] + add + tail
        carried += len(opens)
    return carried


def move_sections(log_dir, it, threshold, today):
    take, keep = [], []
    for sec in it["secs"]:
        if sec_open(sec) == 0 and age_days(sec["date"], today) >= threshold:
            take.append(sec)
        else:
            keep.append(sec)
    if not take:
        return 0, True
    dpath = done_path_for(log_dir, it["month"])
    exists = os.path.exists(dpath)
    if exists:
        dhead, dsecs = split_head_sections(read_lines(dpath))
    else:
        dhead, dsecs = default_head(it["month"], threshold), []
    b_act = tally(it["head"] + flatten(it["secs"]))
    b_done = tally(read_lines(dpath)) if exists else {"done": 0, "open": 0}
    merged = sorted(dsecs + take, key=lambda s: s["date"])
    write_lines(dpath, dhead + flatten(merged))
    write_lines(it["path"], it["head"] + flatten(keep))
    a_act = tally(read_lines(it["path"]))
    a_done = tally(read_lines(dpath))
    ok = (b_act["done"] + b_done["done"] == a_act["done"] + a_done["done"] and
          b_act["open"] + b_done["open"] == a_act["open"] + a_done["open"])
    return len(take), ok


def do_apply(log_dir, items, threshold, today, carry):
    moved, carried, ok = 0, 0, True
    for it in items:
        if carry:
            before = tally(it["head"] + flatten(it["secs"]))
            carried += carry_over_sections(it["secs"], threshold, today)
            after = tally(it["head"] + flatten(it["secs"]))
            if before["done"] != after["done"] or before["open"] != after["open"]:
                ok = False          # 不变量：回流只换载体，不改状态计数
        n, good = move_sections(log_dir, it, threshold, today)
        moved += n
        ok = ok and good
    return moved, carried, ok


def report(result, as_json):
    if as_json:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return
    sys.stdout.write("归档闸 · %s（阈值 %d 天 · 今天 %s）\n"
                     % (result["log_dir"], result["threshold"], result["today"]))
    if result["candidates"]:
        sys.stdout.write("应迁未迁 %d 节：\n" % len(result["candidates"]))
        for c in result["candidates"]:
            tail = "（含 %d 条待回流）" % c["carry_over"] if c["carry_over"] else ""
            sys.stdout.write("  %s  %s  %d 行%s\n" % (c["file"], c["date"], c["lines"], tail))
    else:
        sys.stdout.write("应迁未迁 0 节 —— 无需归档\n")
    if result["leftover_shells"]:
        sys.stdout.write("历史月份空壳待办文件 %d 个（零条目，可清理）：%s\n"
                         % (len(result["leftover_shells"]), "、".join(result["leftover_shells"])))
    if result["applied"]:
        sys.stdout.write("已迁 %d 节、回流 %d 条；守恒校验 %s\n"
                         % (result["moved_sections"], result["carried_over"],
                            "通过" if result.get("conservation_ok") else "未通过"))


def main():
    ap = argparse.ArgumentParser(
        description="AI 工作日志归档闸：默认只检查（--dry-run 为默认行为），--apply 才执行迁移")
    ap.add_argument("--log-dir", required=True, help="工作日志目录（内含 YYYY-MM-待办.md）")
    ap.add_argument("--apply", action="store_true", help="执行迁移；缺省仅检查")
    ap.add_argument("--dry-run", action="store_true", help="显式声明只检查（默认行为，与 --apply 互斥）")
    ap.add_argument("--no-carry-over", action="store_true", help="关闭未完成回流（默认开启）")
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
    carry = not args.no_carry_over

    cands, pend = [], []
    for it in items:
        probe = copy.deepcopy(it["secs"])
        if carry:
            carry_over_sections(probe, args.threshold, today)
        for sec in probe:
            if age_days(sec["date"], today) >= args.threshold and sec_open(sec) == 0:
                src = next((s for s in it["secs"] if s["date"] == sec["date"]), sec)
                n_open = sec_open(src)
                cands.append({"file": it["name"], "date": sec["date"],
                              "lines": len(sec["lines"]), "carry_over": n_open})
                if n_open:
                    pend.append("%s %s（%d 条回流）" % (it["name"], sec["date"], n_open))

    result = {
        "log_dir": log_dir,
        "today": today.isoformat(),
        "threshold": args.threshold,
        "carry_over_enabled": carry,
        "candidates": cands,
        "carry_over_pending": pend,
        "leftover_shells": shells,
        "applied": False,
        "moved_sections": 0,
        "carried_over": 0,
    }

    if not args.apply:
        result["exit"] = 1 if cands else 0
        report(result, args.json)
        sys.exit(result["exit"])

    if not cands:
        result["exit"] = 0
        report(result, args.json)
        sys.exit(0)

    moved, carried, ok = do_apply(log_dir, items, args.threshold, today, carry)
    result["applied"] = True
    result["moved_sections"] = moved
    result["carried_over"] = carried
    result["conservation_ok"] = ok
    result["exit"] = 0 if ok else 3
    report(result, args.json)
    sys.exit(result["exit"])


if __name__ == "__main__":
    main()
