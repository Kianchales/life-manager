#!/usr/bin/env python3
"""export_todo.py — 项目待办导出器：读项目待办 md，出一个排版好的 Excel 明细表。

数据源：项目文件夹的 `待办事项.md`（结构：`# <条线>` → `## <负责人>` → `- [ ] 任务行`）。
产物（落系统下载目录，可用 --out 覆盖）：`<前缀>_待办.xlsx`，单 sheet 明细：
  列：条线 / 负责人 / 事项 / 截止日期 / 状态
  排版：表头加粗填色、冻结首行、自动列宽、逾期整行标红、按负责人分区隔行底色；
        顶部大标题行（项目名 ＋ 生成日期 ＋ 统计一句）。
纪律（来自 alignment.md）：**只导未完成**；AI 备菜不端菜——本脚本只生成文件，不发送。

用法：
    python export_todo.py --todo-file "<项目>/待办事项.md" --apply
    python export_todo.py --todo-file "<项目>/待办事项.md" --out <目录> --prefix <项目名>

退出码：0 成功（含「无未完成」）；2 用法/环境错误；3 待办文件不存在。
写 .xlsx 使用标准库 zip+xml 手工构造（零第三方依赖）。
"""
import argparse
import datetime
import io
import os
import re
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DUE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
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
    """→ (lineset, rows)；rows = [dict(line,person,text,due)]（只未完成）。"""
    lines = read_lines(path)
    lineset = parse_lineset("\n".join(lines))
    rows, cur_line, cur_person = [], None, None
    for ln in lines:
        # 层级：# <条线> → ## <负责人> → - [ ] 任务行
        if ln.startswith("## "):
            cur_person = ln[3:].strip()
            continue
        if ln.startswith("# "):
            h = ln[2:].strip()
            if not h or h == "待办事项" or "待办总表" in h:
                continue                      # 文件标题与视图节不算条线
            cur_line = h if h in lineset else "未分类"
            cur_person = None                 # 进入新条线，负责人归属重置
            continue
        if ln.startswith("- [ ]"):
            m = DUE.search(ln)
            text = DUE.sub("", ln[6:]).strip().rstrip(" 　")
            rows.append({"line": cur_line or "未分类", "person": cur_person or "（未分派）",
                         "text": text, "due": m.group(1) if m else ""})
    return lineset, rows


def is_overdue(due, now):
    if not due:
        return False
    try:
        return datetime.date.fromisoformat(due) < now
    except ValueError:
        return False


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


# ---------------- 极简 xlsx 写出（零依赖） ----------------

def col_name(idx):
    s = ""
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def write_xlsx(path, title, headers, rows, widths, overdue_flags, band_flags):
    """rows = [[c1, c2, ...]]；overdue_flags/band_flags 与行等长。"""
    T = ' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    ncol = len(headers)
    ncols = col_name(ncol)
    last = len(rows) + 4  # 数据从第 5 行起（1 标题 + 2 空 + 1 表头）

    # 行 XML
    body = []

    def row_xml(r, cells, style=None):
        st = ' s="%s"' % style if style else ""
        cs = ['<c r="%s%d"%s t="inlineStr"><is><t>%s</t></is></c>' % (col_name(i + 1), r, st, v)
              for i, v in enumerate(cells)]
        return '<row r="%d">%s</row>' % (r, "".join(cs))

    r = 1
    body.append('<row r="1" ht="22" customHeight="1">' +
                ('<c r="A1" s="1" t="inlineStr"><is><t>%s</t></is></c>' % esc(title)) +
                "".join('<c r="%s1" s="1"/>' % col_name(i + 2) for i in range(ncol - 1)) + '</row>')
    body.append(row_xml(3, [esc(h) for h in headers], style=2))
    r = 4
    for i, (row, od, band) in enumerate(zip(rows, overdue_flags, band_flags), start=1):
        style = 4 if od else (3 if band else None)
        body.append(row_xml(r, [esc(c) for c in row], style=style))
        r += 1

    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet%s>' % T +
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="3" topLeftCell="A4" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
             '<cols>%s</cols>' % "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i + 1, i + 1, w) for i, w in enumerate(widths)) +
             '<sheetData>%s</sheetData>' % "".join(body) +
             '<autoFilter ref="A3:%s%d"/>' % (ncols, last) +
             '</worksheet>')

    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet%s>' % T +
              '<fonts count="6">'
              '<font><sz val="11"/><name val="微软雅黑"/></font>'                     # 0 默认
              '<font><b/><sz val="14"/><color rgb="FF1F3864"/><name val="微软雅黑"/></font>'  # 1 标题
              '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="微软雅黑"/></font>'  # 2 表头白字
              '<font><sz val="11"/><name val="微软雅黑"/></font>'                     # 3 隔行
              '<font><b/><sz val="11"/><color rgb="FFC00000"/><name val="微软雅黑"/></font>'  # 4 逾期红
              '<font><sz val="9"/><color rgb="FF808080"/><name val="微软雅黑"/></font>'       # 5 脚注灰
              '</fonts>'
              '<fills count="5">'
              '<fill><patternFill patternType="none"/></fill>'
              '<fill><patternFill patternType="gray125"/></fill>'
              '<fill><patternFill patternType="solid"><fgColor rgb="FF2F5597"/></patternFill></fill>'  # 2 表头蓝
              '<fill><patternFill patternType="solid"><fgColor rgb="FFF2F6FC"/></patternFill></fill>'  # 3 隔行淡蓝
              '<fill><patternFill patternType="solid"><fgColor rgb="FFFCE4E4"/></patternFill></fill>'  # 4 逾期淡红
              '</fills>'
              '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
              '<border><left/><right/><top/><bottom style="thin"><color rgb="FFB0B0B0"/></bottom><diagonal/></border></borders>'
              '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
              '<cellXfs count="6">'
              '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'                 # 0
              '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/>'                 # 1 标题
              '<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'  # 2 表头
              '<xf numFmtId="0" fontId="3" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'  # 3 隔行
              '<xf numFmtId="0" fontId="4" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>'  # 4 逾期
              '<xf numFmtId="0" fontId="5" fillId="0" borderId="0" xfId="0"/>'                 # 5 脚注
              '</cellXfs></styleSheet>')

    content = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="xml" ContentType="application/xml"/>'
               '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
               '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
               '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
               '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>')
    wbrels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
              '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
              '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
              '</Relationships>')
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook%s><sheets><sheet name="待办明细" sheetId="1" r:id="rId1"/></sheets></workbook>'
          % (' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wbrels)
        z.writestr("xl/styles.xml", styles)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


def main():
    ap = argparse.ArgumentParser(description="项目待办导出器：单 Excel 明细表（只含未完成）")
    ap.add_argument("--todo-file", required=True, help="项目待办文件路径（…/待办事项.md）")
    ap.add_argument("--out", default=None, help="输出目录（默认系统下载目录）")
    ap.add_argument("--prefix", default=None, help="文件名前缀（默认取待办文件上级目录名）")
    ap.add_argument("--dry-run", action="store_true", help="显式声明只检查（默认行为，与 --apply 互斥）")
    ap.add_argument("--apply", action="store_true", help="写盘（与 --dry-run 互斥）")
    args = ap.parse_args()

    if args.apply and args.dry_run:
        die("--apply 与 --dry-run 互斥")
    todo = os.path.abspath(args.todo_file)
    if not os.path.isfile(todo):
        sys.stderr.write("错误：待办文件不存在：%s\n" % todo)
        sys.exit(3)

    prefix = args.prefix or os.path.basename(os.path.dirname(todo)) or "待办"
    now = today() if False else datetime.date.today()
    _, rows = parse_todo(todo)
    if not rows:
        print("无未完成待办，无需导出。")
        sys.exit(0)

    outdir = args.out or downloads_dir()
    if args.apply and not (outdir and os.path.isdir(outdir)):
        die("输出目录不可用：%s（可用 --out 指定）" % outdir)

    headers = ["条线", "负责人", "事项", "截止日期", "状态"]
    sorted_rows = sorted(rows, key=lambda r: (r["person"], is_overdue(r["due"], now) is False,
                                              r["due"] or "9999", r["line"]))
    data, od_flags, band_flags = [], [], []
    prev_person, band = None, False
    for r in sorted_rows:
        if r["person"] != prev_person:
            band = not band
            prev_person = r["person"]
        od = is_overdue(r["due"], now)
        data.append([r["line"], r["person"], r["text"], r["due"] or "—",
                     "逾期" if od else ("今日到期" if r["due"] == now.isoformat() else "进行中")])
        od_flags.append(od)
        band_flags.append(band and not od)
    n_od = sum(1 for f in od_flags if f)
    persons = sorted({r["person"] for r in rows})
    title = "%s · 未完成待办 %d 条（逾期 %d ｜ 涉及 %d 人： %s）  —  导出于 %s" % (
        prefix, len(rows), n_od, len(persons), "、".join(persons), now.isoformat())

    out_path = os.path.join(outdir or "", "%s_待办.xlsx" % prefix)
    print("导出（%s）：%d 条未完成（逾期 %d），%d 位负责人" % (
        "写盘" if args.apply else "演练", len(rows), n_od, len(persons)))
    print("  %s" % out_path)
    if not args.apply:
        print("（演练未写盘；加 --apply 写入）")
        sys.exit(0)
    write_xlsx(out_path, title, headers, data,
               widths=[10, 10, 72, 12, 9], overdue_flags=od_flags, band_flags=band_flags)
    print("已写入：%s" % outdir)
    sys.exit(0)


if __name__ == "__main__":
    main()
