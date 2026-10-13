#!/usr/bin/env python3
"""export_todo.py — 项目待办导出器：读项目待办 md，出 CSV（汇总 + 明细）与按人文本。

数据源：项目文件夹的 `待办事项.md`（结构：`## <条线>` → `### <负责人>` → `- [ ] 任务行`）。
产物（落系统下载目录，可用 --out 覆盖）：
  <前缀>_待办汇总.csv   长表：负责人 / 条线 / 未完成数 / 逾期数
  <前缀>_待办明细.csv   全量未完成行：条线 / 负责人 / 事项 / 截止日期 / 是否逾期
  <前缀>_待办_<人名>.txt 每人一份现成文本（--person <名字> 或 --all-persons）

纪律（来自 alignment.md）：**只导未完成**；AI 备菜不端菜——本脚本只生成文件，不发送；
条线以项目待办文件头「条线清单：」行的集合为准，清单外的 `##` 标题记为「未分类」并显式导出。

用法：
    python export_todo.py --todo-file "<项目>/待办事项.md"
    python export_todo.py --todo-file "<项目>/待办事项.md" --person <负责人名>
    python export_todo.py --todo-file "<项目>/待办事项.md" --all-persons
    python export_todo.py --todo-file "<项目>/待办事项.md" --out <目录> --prefix <项目名>

退出码：0 成功（含「无未完成」）；2 用法/环境错误；3 待办文件不存在。
纯标准库、零依赖；条线/负责人/日期解析均为确定性文本规则（P2：执行不交给模型自由发挥）。
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

DUE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
HEADER_LINES = ("#", ">", "`", "---", "", None)
DEFAULT_LINES = ("综合事务", "财务", "法律", "业务")


def die(msg):
    sys.stderr.write("错误：%s\n" % msg)
    sys.exit(2)


def read_lines(path):
    with io.open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def parse_lineset(text):
    m = re.search(r"条线清单[：:]\s*(.+)", text)
    if not m:
        return list(DEFAULT_LINES)
    return [x.strip() for x in m.group(1).replace("／", "/").split("/") if x.strip()]


def parse_todo(path):
    """→ (lineset, rows)；rows = [dict(line,person,text,due,done,unclassified)]。"""
    lines = read_lines(path)
    lineset = parse_lineset("\n".join(lines))
    rows, cur_line, cur_person = [], None, None
    for ln in lines:
        if ln.startswith("## "):
            h = ln[3:].strip()
            cur_line = h if h in lineset else (cur_line if h in ("待办",) else h)
            cur_line = h if h not in ("待办",) else cur_line
            if cur_line not in lineset:
                cur_line = "未分类"
            continue
        if ln.startswith("### "):
            cur_person = ln[4:].strip()
            continue
        if ln.startswith("- [ ]"):
            m = DUE.search(ln)
            text = DUE.sub("", ln[6:]).strip().rstrip(" 　")
            rows.append({"line": cur_line or "未分类", "person": cur_person or "（未分派）",
                         "text": text, "due": m.group(1) if m else "", "done": False})
        elif ln.startswith("- [x]"):
            pass  # 只导未完成
    return lineset, rows


def today():
    return datetime.date.today()


def is_overdue(due, now):
    if not due:
        return False
    try:
        return datetime.date.fromisoformat(due) < now
    except ValueError:
        return False


def summarize(rows, now):
    agg = {}
    for r in rows:
        k = (r["person"], r["line"])
        c = agg.setdefault(k, [0, 0])
        c[0] += 1
        if is_overdue(r["due"], now):
            c[1] += 1
    return [{"person": p, "line": l, "open": c[0], "overdue": c[1]}
            for (p, l), c in sorted(agg.items())]


def write_csv(path, header, rows):
    with io.open(path, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            cells = []
            for h in header:
                v = str(r[h] if isinstance(r, dict) else r)
                cells.append('"%s"' % v.replace('"', '""') if ("," in v or '"' in v or "\n" in v) else v)
            fh.write(",".join(cells) + "\n")


def person_text(name, rows, now):
    mine = [r for r in rows if r["person"] == name]
    if not mine:
        return "%s：暂无未完成待办。" % name
    mine.sort(key=lambda r: (not is_overdue(r["due"], now), r["due"] or "9999", r["line"]))
    out = ["【%s · 未完成待办】共 %d 条（逾期 %d）" % (
        name, len(mine), sum(1 for r in mine if is_overdue(r["due"], now)))]
    for r in mine:
        od = "【逾期】" if is_overdue(r["due"], now) else ""
        due = "（截止 %s）" % r["due"] if r["due"] else ""
        out.append("- %s[%s] %s%s" % (od, r["line"], r["text"], due))
    return "\n".join(out)


def downloads_dir():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
        winreg.CloseKey(key)
        d = os.path.expandvars(val)
        if os.path.isdir(d):
            return d
    except Exception:
        pass
    d = os.path.join(os.path.expanduser("~"), "Downloads")
    return d if os.path.isdir(d) else None


def main():
    ap = argparse.ArgumentParser(description="项目待办导出器：CSV 汇总/明细 + 按人文本（只含未完成）")
    ap.add_argument("--todo-file", required=True, help="项目待办文件路径（…/待办事项.md）")
    ap.add_argument("--person", default=None, help="只出该负责人的文本（可与 --all-persons 并存）")
    ap.add_argument("--all-persons", action="store_true", help="为每个负责人各出一份文本")
    ap.add_argument("--out", default=None, help="输出目录（默认系统下载目录）")
    ap.add_argument("--prefix", default=None, help="文件名前缀（默认取待办文件上级目录名）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要生成的内容，不写盘（默认行为，本参数为显式声明）")
    ap.add_argument("--apply", action="store_true", help="写盘（与 --dry-run 互斥）")
    args = ap.parse_args()

    if args.apply and args.dry_run:
        die("--apply 与 --dry-run 互斥")
    todo = os.path.abspath(args.todo_file)
    if not os.path.isfile(todo):
        sys.stderr.write("错误：待办文件不存在：%s\n" % todo)
        sys.exit(3)

    prefix = args.prefix or os.path.basename(os.path.dirname(todo)) or "待办"
    now = today()
    _, rows = parse_todo(todo)
    if not rows:
        print("无未完成待办，无需导出。")
        sys.exit(0)

    summary = summarize(rows, now)
    apply = args.apply
    outdir = args.out or downloads_dir()
    if apply and not (outdir and os.path.isdir(outdir)):
        die("输出目录不可用：%s（可用 --out 指定）" % outdir)

    made = []
    f_sum = "%s_待办汇总.csv" % prefix
    f_det = "%s_待办明细.csv" % prefix
    sum_rows = summary
    det_rows = [{"条线": r["line"], "负责人": r["person"], "事项": r["text"],
                 "截止日期": r["due"], "逾期": "是" if is_overdue(r["due"], now) else ""}
                for r in sorted(rows, key=lambda r: (r["person"], r["line"], r["due"] or "9999"))]
    targets = [(f_sum, ["person", "line", "open", "overdue"], sum_rows),
               (f_det, ["条线", "负责人", "事项", "截止日期", "逾期"], det_rows)]
    if args.all_persons:
        for name in sorted({r["person"] for r in rows}):
            targets.append(("%s_待办_%s.txt" % (prefix, name), None, person_text(name, rows, now)))
    if args.person:
        if args.person not in {r["person"] for r in rows}:
            die("负责人「%s」在未完成清单中不存在" % args.person)
        targets.append(("%s_待办_%s.txt" % (prefix, args.person), None, person_text(args.person, rows, now)))

    print("导出（%s）：%d 条未完成、%d 个负责人×条线组合" % ("写盘" if apply else "演练", len(rows), len(summary)))
    for fname, header, data in targets:
        print("  %s" % fname)
        if header is None:
            if apply:
                with io.open(os.path.join(outdir, fname), "w", encoding="utf-8") as fh:
                    fh.write(data + "\n")
        elif apply:
            write_csv(os.path.join(outdir, fname), header, data)
    if apply:
        print("已写入：%s" % outdir)
    else:
        print("（演练未写盘；加 --apply 写入）")
    if args.person:
        print()
        print(person_text(args.person, rows, now))
    sys.exit(0)


if __name__ == "__main__":
    main()
