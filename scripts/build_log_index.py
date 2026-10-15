#!/usr/bin/env python3
"""build_log_index.py — 工作日志「办结文件主题索引」生成器。

用途：办结文件（`YYYY-MM-办结.md`）动辄数百 KB、数十节，长周期回顾只能 grep。
本脚本把每月办结文件的**节清单**（节日期 · 主题 · 条数 · 主要性质）压成一个
索引块，插在**文件头**（表头 blockquote 之后、第一节之前）——回顾时看索引直跳。

铁律：
  · **只动文件头**——节内容一字不改（归档「原文零改动」不破）。
  · **幂等**——块以 `<!-- lm-index:begin -->` / `<!-- lm-index:end -->` 包裹，
    重复运行 ＝ 原块整块替换（无损回退：删块即恢复原状）。
  · **默认演练**——只打印将写入的索引块；`--apply` 才落盘。
  · **归档后重跑**——有新节迁入后索引会过期，跑一次刷新即可。

用法：
    python build_log_index.py --log-dir "<库根>/04 AI Work/工作日志"              # 全部办结文件，演练
    python build_log_index.py --log-dir "<...>" --month 2026-09 --apply          # 指定月，写盘

退出码：0 成功；2 用法/环境错误；3 未找到任何办结文件。
零第三方依赖；写盘用 LF 行尾。
"""
import argparse
import datetime
import glob
import io
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

SEC_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*(?:（(.*?)）)?\s*$")
DONE_RE = re.compile(r"^-\s*\[[xX]\]")
OPEN_RE = re.compile(r"^-\s*\[\s*\]\s")
TAG_RE = re.compile(r"#([^\s#]+)")
FILE_RE = re.compile(r"^(\d{4}-\d{2})-办结\.md$")

BEGIN_RE = re.compile(r"^\s*<!--\s*lm-index:begin")
END_RE = re.compile(r"^\s*<!--\s*lm-index:end\s*-->")
BEGIN = "<!-- lm-index:begin（脚本生成 · 勿手改 · 重复运行＝整块替换） -->"
END = "<!-- lm-index:end -->"

FIXED = ("体系搭建", "skill开发", "文档写作", "项目跟进", "研究学习", "其他")


def die(msg, code=2):
    sys.stderr.write("错误：%s\n" % msg)
    sys.exit(code)


def parse_entries(text):
    """→ [dict(date, title, done, tags)]：逐节统计条数与性质分布（只认节标题之后的 `- [x]`）。"""
    entries, cur = [], None
    for ln in text.split("\n"):
        m = SEC_RE.match(ln)
        if m:
            cur = {"date": m.group(1), "title": (m.group(2) or "").strip(),
                   "done": 0, "tags": {}}
            entries.append(cur)
            continue
        if cur is None:
            continue
        if DONE_RE.match(ln):
            cur["done"] += 1
            for t in TAG_RE.findall(ln):
                if t in FIXED:
                    cur["tags"][t] = cur["tags"].get(t, 0) + 1
    return entries


def render_block(entries, today):
    total = sum(e["done"] for e in entries)
    L = [BEGIN]
    L.append("> **📇 主题索引** ｜ %d 节 · %d 条 ｜ 更新 %s" % (
        len(entries), total, today.isoformat()))
    L.append(">")
    L.append("> | 节日期 | 主题 | 条数 | 主要性质 |")
    L.append("> |---|---|---|---|")
    for e in entries:
        tags = sorted(e["tags"].items(), key=lambda kv: (-kv[1], kv[0]))
        tagtxt = " · ".join("#%s×%d" % (t, c) for t, c in tags[:2])
        if len(tags) > 2:
            tagtxt += " …"
        L.append("> | %s | %s | %d | %s |" % (
            e["date"][5:], e["title"] or "—", e["done"], tagtxt or "—"))
    L.append(END)
    return L


def upsert(text, block):
    """→ (new_text | None, action)。已有标记块则整块替换；否则插在第一节之前。"""
    lines = text.split("\n")
    i = j = None
    for k, ln in enumerate(lines):
        if i is None and BEGIN_RE.match(ln):
            i = k
        elif i is not None and END_RE.match(ln):
            j = k
            break
    if i is not None and j is not None:
        return "\n".join(lines[:i] + block + lines[j + 1:]), "replace"

    idx = next((k for k, ln in enumerate(lines) if SEC_RE.match(ln)), None)
    if idx is None:
        return None, "no-section"
    head = lines[:idx]
    while head and head[-1].strip() == "":
        head.pop()
    return "\n".join(head + [""] + block + [""] + lines[idx:]), "insert"


def read_text(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read()


def main():
    ap = argparse.ArgumentParser(description="工作日志办结文件主题索引生成器")
    ap.add_argument("--log-dir", required=True, help="工作日志目录（…/04 AI Work/工作日志）")
    ap.add_argument("--month", default=None, help="目标月份 YYYY-MM（默认全部办结文件）")
    ap.add_argument("--apply", action="store_true", help="写盘（默认只演练）")
    args = ap.parse_args()

    log_dir = os.path.abspath(args.log_dir)
    if not os.path.isdir(log_dir):
        die("日志目录不存在：%s" % log_dir)

    if args.month:
        if not re.match(r"^\d{4}-\d{2}$", args.month):
            die("--month 需为 YYYY-MM：%s" % args.month)
        targets = [os.path.join(log_dir, "%s-办结.md" % args.month)]
        if not os.path.isfile(targets[0]):
            die("该月办结文件不存在：%s" % targets[0], code=3)
    else:
        targets = sorted(glob.glob(os.path.join(log_dir, "*-办结.md")))
        if not targets:
            die("未找到任何办结文件（*-办结.md，目录：%s）" % log_dir, code=3)

    today = datetime.date.today()
    changed = 0
    for path in targets:
        fname = os.path.basename(path)
        text = read_text(path)
        entries = parse_entries(text)
        if not entries:
            print("[跳过] %s：无日期节" % fname)
            continue
        block = render_block(entries, today)
        new_text, action = upsert(text, block)
        if new_text is None:
            print("[跳过] %s：无日期节" % fname)
            continue
        delta = len(new_text.encode("utf-8")) - len(text.encode("utf-8"))
        print("[%s] %s：%d 节 · %d 条 ｜ 字节 %+d" % (
            "写盘" if args.apply else "演练", fname, len(entries),
            sum(e["done"] for e in entries), delta))
        if not args.apply:
            print("  —— 将写入的索引块 ——")
            for ln in block:
                print("  " + ln)
            continue
        if new_text == text:
            print("  （内容无变化，跳过写盘）")
            continue
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(new_text)
        changed += 1

    if not args.apply:
        print("（演练未写盘；加 --apply 生效）")
    else:
        print("完成：%d 个文件已更新" % changed)
    sys.exit(0)


if __name__ == "__main__":
    main()
