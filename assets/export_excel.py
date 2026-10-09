#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行导出 xlsx（不依赖浏览器下载管线，零第三方依赖）。

背景：WorkBuddy 自带的**内置预览窗口**沿用了受限的 WebContents/沙箱策略，
页面里的下载（`URL.createObjectURL` + `a.download`，以及 `showSaveFilePicker`）
在其中会被静默取消——表现为保存下来 0 字节、或压根不产生文件。
用外部浏览器（Chrome / Edge）双击打开页面则一切正常。

因此本脚本提供第三条可靠通道：直接读生成页面里的 DATA / AUTHORS
（保证与页面所见完全一致），手写 xlsx 落盘到 exports/，不依赖 openpyxl。

用法：
  python export_excel.py authors            # 作者统计分析（作者卡片全部字段）
  python export_excel.py author <姓名>       # 单个作者
  python export_excel.py papers             # 全部论文（默认字段）
  python export_excel.py papers <主题id>     # 某研究方向的论文
  python export_excel.py papers <作者名>     # 某作者的论文
  python export_excel.py papers <搜索词>     # 标题模糊匹配
"""
import os, re, sys, json, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
# 换会议时只改这三个环境变量（或用 --html/--rsrc/--out），不必改代码
HTML = os.environ.get('GUIDE_HTML') or os.path.join(BASE, 'interspeech2026_authors.html')
RSRC = os.environ.get('GUIDE_RSRC') or os.path.join(BASE, 'render.py')
OUTDIR = os.environ.get('GUIDE_OUTDIR') or os.path.join(BASE, 'exports')


def field_defs(name):
    """从 render.py 里解析 const AUTHOR_FIELDS / PAPER_FIELDS 的 [('k','label'),...]，
    保证命令行导出的列与页面导出面板完全一致（避免手抄 key 对不上）。"""
    blk = re.search(r'const ' + name + r'=\[(.*?)\];', open(RSRC, encoding='utf8').read(), re.S)
    if not blk:
        sys.exit('render.py 里找不到 const ' + name)
    return re.findall(r"k:'([^']+)',\s*label:'([^']+)'", blk.group(1))


AUTHOR_FIELDS = field_defs('AUTHOR_FIELDS')
PAPER_FIELDS = field_defs('PAPER_FIELDS')


def load():
    html = open(HTML, encoding='utf8').read()

    def grab(pat):
        m = re.search(pat + r' = (\{.*?\});\n', html, re.M) or \
            re.search(pat + r' = (\[.*?\]);\n', html, re.M)
        if not m:
            sys.exit('页面里找不到 ' + pat)
        return json.loads(re.sub(r'\bundefined\b', 'null', m.group(1)))
    return grab('const DATA'), grab('const AUTHORS')


def _join(v):
    if v is None: return ''
    if isinstance(v, (list, tuple)): return '；'.join(str(x) for x in v if x is not None)
    return str(v)


def author_row(a, data):
    six = data.get('papers') or []
    return {
        'name': a.get('name') or '', 'affs': _join(a.get('affs')), 'emails': _join(a.get('emails')),
        'countries': _join(a.get('countries')), 'org': a.get('org') or '',
        'conf': (('%s分（%s）' % (a['conf'], '高' if a['conf'] >= 80 else '中' if a['conf'] >= 55 else '低'))
                 if a.get('conf') is not None else ''),
        'papers': '；'.join(six[i].get('t', '') for i in (a.get('pids') or []) if isinstance(i, int) and 0 <= i < len(six)),
    }


def paper_row(p):
    six = p.get('six') or {}
    return {'t': p.get('t') or '', 'a': p.get('a') or '', 'summary': p.get('summary') or '',
            'motivation': six.get('motivation') or '', 'problem': six.get('problem') or '',
            'method': six.get('method') or '', 'dataset': _join(p.get('datasets') or p.get('dataset') or ''),
            'experiments': six.get('experiments') or '', 'contribution': six.get('contribution') or '',
            'u': p.get('u') or '', 'doi': p.get('doi') or '', 'pdf': p.get('pdf') or p.get('u') or ''}


def scope_rows(kind, kw, data, authors):
    """返回 [dict]，key 与 render.py 的 *_FIELDS 一一对应。"""
    if kind in ('authors', 'author'):
        sel = authors
        if kind == 'author':
            sel = [a for a in authors if re.search(re.escape(kw), (a.get('name') or ''), re.I)]
            if not sel:
                sys.exit('没找到匹配的作者：' + kw)
        return [author_row(a, data) for a in sel]
    # papers
    if not kw:
        return [paper_row(p) for p in data['papers']]
    rx = re.compile(re.escape(kw), re.I)
    return [paper_row(p) for p in data['papers']
            if rx.search(p.get('t') or '') or rx.search(p.get('a') or '')
            or rx.search(p.get('theme') or '') or rx.search(p.get('sess') or '')]


def _col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s


def _plain_xlsx(rows, fields, path):
    """零依赖手写 xlsx（只有标准库 zipfile），openpyxl 没装时也能用。"""
    import zipfile
    def esc(v):
        return (str(v).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                .replace('"', '&quot;'))
    body = []
    body.append('<row r="1">' + ''.join(
        '<c r="%s1" t="inlineStr"><is><t>%s</t></is></c>' % (_col(i), esc(l)) for i, (k, l) in enumerate(fields)) + '</row>')
    for ri, r in enumerate(rows, start=2):
        body.append('<row r="%d">%s</row>' % (ri, ''.join(
            '<c r="%s%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>'
            % (_col(i), ri, esc(r.get(k) or '')) for i, (k, l) in enumerate(fields))))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<dimension ref="A1:%s%d"/><sheetData>%s</sheetData></worksheet>'
             % (_col(len(fields) - 1), len(rows), ''.join(body)))
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    wbxml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
             ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    wbrel = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ct); z.writestr('_rels/.rels', rels)
        z.writestr('xl/workbook.xml', wbxml); z.writestr('xl/_rels/workbook.xml.rels', wbrel)
        z.writestr('xl/worksheets/sheet1.xml', sheet)


def write_xlsx(rows, fields, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment
        wb = Workbook(); ws = wb.active; ws.title = 'Sheet1'
        ws.append([l for _, l in fields])
        for h in ws[1]: h.font = Font(bold=True)
        for r in rows:
            ws.append([(r.get(k, '') or '') if not isinstance(r.get(k, ''), (list, dict)) else json.dumps(r.get(k, ''), ensure_ascii=False) for k, _ in fields])
        for c in ws.columns:
            w = max((len(str(c[i].value)) for i in range(min(60, len(c))) if c[i].value is not None), default=8)
            for i in range(1, len(c)):
                c[i].alignment = Alignment(vertical='top', wrap_text=len(str(c[i].value or '')) > 40)
        ws.column_dimensions['A'].width = min(60, max(12, w))
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = 'A1:%s%d' % (_col(len(fields) - 1), len(rows) + 1)
        wb.save(path)
    except ImportError:
        _plain_xlsx(rows, fields, path)
    print('written %s  rows=%d  cols=%d  bytes=%d' % (path, len(rows), len(fields), os.path.getsize(path)))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('kind', choices=['authors', 'author', 'papers'])
    ap.add_argument('kw', nargs='?', default='')
    a = ap.parse_args()
    data, authors = load()
    print('DATA papers=%d  AUTHORS=%d' % (len(data['papers']), len(authors)))
    rows = scope_rows(a.kind, a.kw, data, authors)
    if not rows:
        sys.exit('没有匹配到任何记录')
    fields = PAPER_FIELDS if a.kind == 'papers' else AUTHOR_FIELDS
    tag = a.kw or ('author' if a.kind == 'authors' else 'paper')
    safe = re.sub(r'[^\w.\-\u4e00-\u9fa5]+', '_', str(tag))[:24]
    path = os.path.join(OUTDIR, 'Interspeech2026_%s_%s.xlsx' % ('作者统计分析' if a.kind != 'papers' else '全部论文', safe))
    write_xlsx(rows, fields, path)
