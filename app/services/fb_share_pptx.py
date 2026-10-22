"""Build the weekly Crowdsource FB Share PowerPoint report from a template deck.

The template (``app/resources/report_templates/fb_share.pptx``) ships two slides:

* slide 1 — headline KPI boxes (Telkomsel / IOH / XLS share + WoW delta), written
  summary, FB Share by NOP table, city level table, and the regional trend chart.
* slide 2 — one trend chart per NOP.

Everything is filled in place so the deck keeps the template's fonts, colours and
layout: chart series are replaced (formatting untouched), tables are resized by
cloning their existing rows, and cell text keeps its original run formatting.

The module is deliberately framework-free (no Flask, no DB) so it can be unit
tested against a plain ``report`` dict.
"""
from __future__ import annotations

import copy
import io
from datetime import date

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Pt

# ── Palette used by the template ────────────────────────────────────────────
BLACK = RGBColor(0x00, 0x00, 0x00)
RED = RGBColor(0xC0, 0x00, 0x00)
ORANGE = RGBColor(0xE1, 0x6A, 0x54)
BLUE = RGBColor(0x46, 0x8F, 0xAF)
GREEN = RGBColor(0x86, 0xAB, 0x89)
AMBER = RGBColor(0xDA, 0x83, 0x59)
GREY = RGBColor(0x80, 0x80, 0x80)
DASH = "\u2013"  # en dash, used for "no data"

PROVIDER_KEYS = ("tsel", "ioh", "xls")
COMPARE_KEYS = ("wow", "mom", "yoy")


# ── Small formatting helpers ────────────────────────────────────────────────

def _f2(value, dash=DASH):
    """Format a number with 2 decimals, or an en dash when missing."""
    if value is None:
        return dash
    return f"{float(value):.2f}"


def _title(name):
    """DB names are upper case; the deck writes them in Title Case."""
    if not name:
        return ""
    return " ".join(w.capitalize() if len(w) > 2 else w for w in str(name).split())


def _week_label(yw):
    """202640 -> W40'26 (empty string when unknown)."""
    try:
        yw = int(yw)
        return f"W{yw % 100:02d}'{str(yw)[2:4]}"
    except (TypeError, ValueError):
        return ""


def _month_label(yw):
    """202640 -> Sep (ISO week 40 of 2026 starts in September)."""
    try:
        d = date.fromisocalendar(int(str(yw)[:4]), int(str(yw)[4:]), 1)
        return d.strftime("%b %Y")
    except (TypeError, ValueError):
        return ""


# ── Text / table primitives ─────────────────────────────────────────────────

def _add_run(paragraph, text, rpr_template=None, bold=None, color=None, size=None):
    """Append a run to *paragraph*, optionally cloning formatting from *rpr_template*."""
    run = paragraph.add_run()
    run.text = text
    if rpr_template is not None:
        existing = run._r.find(qn("a:rPr"))
        if existing is not None:
            run._r.remove(existing)
        run._r.insert(0, copy.deepcopy(rpr_template))
    if bold is not None:
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    if size is not None:
        run.font.size = size
    return run


def _rewrite_paragraph(paragraph, parts, bold_template=None):
    """Replace all runs of *paragraph* with ``parts`` = [(text, bold, color), ...]."""
    bold_rpr = None
    plain_rpr = None
    if paragraph.runs:
        plain_rpr = copy.deepcopy(paragraph.runs[0]._r.find(qn("a:rPr")))
        for run in paragraph.runs:
            rpr = run._r.find(qn("a:rPr"))
            if rpr is not None and rpr.get("b") in ("1", "true"):
                bold_rpr = copy.deepcopy(rpr)
                break
    for run in list(paragraph.runs):
        run._r.getparent().remove(run._r)
    for text, bold, color in parts:
        if bold:
            template = bold_rpr if bold_rpr is not None else bold_template
        else:
            template = plain_rpr if plain_rpr is not None else bold_template
        _add_run(paragraph, text, template, bold=bold, color=color)


def _set_cell(cell, text, color=None, bold=None, size=None):
    """Write *text* into a table cell, keeping the cell's original run formatting."""
    tf = cell.text_frame
    paragraphs = list(tf.paragraphs)
    for extra in paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    paragraph = tf.paragraphs[0]
    if paragraph.runs:
        first = paragraph.runs[0]
        for run in paragraph.runs[1:]:
            run._r.getparent().remove(run._r)
        first.text = "" if text is None else str(text)
        target = first
    else:
        target = paragraph.add_run()
        target.text = "" if text is None else str(text)
    if bold is not None:
        target.font.bold = bold
    if color is not None:
        target.font.color.rgb = color
    if size is not None:
        target.font.size = size
    return target


def _resize_table(table, header_rows, data_rows):
    """Grow/shrink a table to ``header_rows + data_rows`` by cloning its last body row."""
    trs = table._tbl.tr_lst
    body = trs[header_rows:]
    while len(body) > data_rows > 0:
        tr = body.pop()
        tr.getparent().remove(tr)
    if data_rows <= 0:
        return
    if not body:
        return
    while len(body) < data_rows:
        new_tr = copy.deepcopy(body[-1])
        body[-1].addnext(new_tr)
        body.append(new_tr)


def _table_cells(table, row_index):
    return [cell for cell in table.rows[row_index].cells]


# ── Slide lookup helpers ────────────────────────────────────────────────────

def _text_shapes(slide):
    return [sh for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]


def _find_text_shape(slide, needle):
    for sh in _text_shapes(slide):
        if needle.lower() in sh.text_frame.text.lower():
            return sh
    return None


def _kpi_shapes(slide):
    """The three headline boxes: two paragraphs, the second one starts with '('."""
    found = []
    for sh in _text_shapes(slide):
        paragraphs = [p for p in sh.text_frame.paragraphs if p.text.strip()]
        if len(paragraphs) == 2 and paragraphs[1].text.strip().startswith("("):
            found.append(sh)
    found.sort(key=lambda s: s.left or 0)
    return found


def _tables(slide):
    return [sh for sh in slide.shapes if getattr(sh, "has_table", False) and sh.has_table]


def _charts(slide):
    charts = [sh for sh in slide.shapes if getattr(sh, "has_chart", False) and sh.has_chart]
    charts.sort(key=lambda s: ((s.top or 0), (s.left or 0)))
    return charts


def _set_chart_title(chart, text):
    """Overwrite a chart title without losing its formatting."""
    if not chart.has_title:
        chart.has_title = True
    tf = chart.chart_title.text_frame
    if tf.paragraphs and tf.paragraphs[0].runs:
        tf.paragraphs[0].runs[0].text = text
        for run in tf.paragraphs[0].runs[1:]:
            run._r.getparent().remove(run._r)
    else:
        tf.text = text


def _replace_chart_data(chart, categories, series):
    """Replace categories + series values, leaving series formatting intact."""
    data = CategoryChartData()
    data.categories = [str(c) for c in categories]
    for name, values in series:
        data.add_series(name, list(values))
    # The sample links charts to an external workbook. Remove that link so
    # replace_data creates an embedded workbook usable on any user's machine.
    external = chart._chartSpace.find(qn("c:externalData"))
    if external is not None:
        rid = external.get(qn("r:id"))
        if rid and chart.part.rels[rid].is_external:
            chart.part.drop_rel(rid)
            chart._chartSpace.remove(external)
    chart.replace_data(data)


# ── Slide 1: headline, branch table, city table, regional trend ─────────────

def _fill_headline(slide, report):
    summary = report.get("summary") or {}
    share = report.get("share") or {}
    wow = report.get("wow") or {}
    shapes = _kpi_shapes(slide)
    for shape, key in zip(shapes, PROVIDER_KEYS):
        value = share.get(key)
        delta = wow.get(key)
        paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
        if len(paragraphs) < 2:
            continue
        _rewrite_paragraph(paragraphs[0], [(_f2(value), None, None)])
        delta_text = f"({_f2(delta)}%)" if delta is not None else f"({DASH})"
        _rewrite_paragraph(paragraphs[1], [(delta_text, None, None)])


def _fill_title(slide, report, suffix):
    shape = _find_text_shape(slide, "Network Benchmarking")
    if shape is None:
        return
    paragraphs = [p for p in shape.text_frame.paragraphs if p.text.strip()]
    if not paragraphs:
        return
    runs = paragraphs[0].runs
    if len(runs) >= 3:
        runs[2].text = suffix
        for extra in runs[3:]:
            extra._r.getparent().remove(extra._r)
    else:
        paragraphs[0].runs[0].text = suffix


def _fill_branch_table(table, report):
    rows = report.get("branch_table") or []
    _resize_table(table, 2, len(rows))
    for index, row in enumerate(rows):
        cells = _table_cells(table, index + 2)
        name = row.get("name") or ""
        _set_cell(cells[0], name, bold=True)
        share = row.get("share") or {}
        for col, key in enumerate(PROVIDER_KEYS, start=1):
            _set_cell(cells[col], _f2(share.get(key)), bold=row.get("is_regional"))
        col = 4
        for key in COMPARE_KEYS:
            values = row.get(key) or {}
            for provider in PROVIDER_KEYS:
                value = values.get(provider)
                _set_cell(cells[col], _f2(value), color=RED if (value or 0) < 0 else BLACK)
                col += 1


def _fill_city_table(table, report):
    rows = report.get("city_table") or []
    threshold = report.get("threshold") or 95.0
    _resize_table(table, 2, max(len(rows), 1))
    if not rows:
        cells = _table_cells(table, 2)
        _set_cell(cells[0], "No data")
        for cell in cells[1:]:
            _set_cell(cell, "")
        return
    # The template row height is tuned for 52 cities; shrink the font slightly when
    # the city master list grows so the table never runs past the slide edge.
    size = Pt(6.5) if len(rows) > 56 else (Pt(6.8) if len(rows) > 52 else None)
    for index, row in enumerate(rows):
        cells = _table_cells(table, index + 2)
        _set_cell(cells[0], row.get("branch") or "", size=size)
        _set_cell(cells[1], row.get("city") or "", size=size)
        tsel = row.get("tsel")
        share_color = ORANGE if (tsel is not None and tsel < threshold) else BLACK
        _set_cell(cells[2], _f2(tsel), color=share_color, size=size)
        status = (row.get("status") or "").upper()
        if row.get("missing"):
            _set_cell(cells[3], "N/A", color=GREY, size=size)
        elif status == "WIN":
            _set_cell(cells[3], "WIN", color=BLUE, size=size)
        elif status == "LOSE":
            _set_cell(cells[3], "LOSE", color=RED, size=size)
        else:
            _set_cell(cells[3], status or DASH, color=GREY, size=size)
        olo = row.get("olo")
        olo_color = GREEN if olo == "XLS" else (AMBER if olo == "IOH" else GREY)
        _set_cell(cells[4], olo or DASH, color=olo_color, size=size)
        col = 5
        for key in COMPARE_KEYS:
            values = row.get(key) or {}
            for provider in PROVIDER_KEYS:
                value = values.get(provider)
                _set_cell(cells[col], _f2(value), color=RED if (value or 0) < 0 else BLACK, size=size)
                col += 1


def _fill_trend_chart(chart, trend):
    weeks = trend.get("weeks") or []
    if not weeks:
        return
    regional = (trend.get("regional") or {}).get("tsel") or []
    series = [("_Regional", regional)]
    branches = trend.get("branches") or []
    branch_series = trend.get("branch_series") or {}
    for branch in branches:
        series.append((f"_{branch}", (branch_series.get(branch) or {}).get("tsel") or []))
    _replace_chart_data(chart, weeks, series)


# ── Summary text ────────────────────────────────────────────────────────────

def _verb(delta):
    if delta is None:
        return "was not comparable"
    if abs(delta) < 0.05:
        return "was maintained"
    return "slightly increased" if delta > 0 else "slightly decreased"


def _compare_note(report, key):
    info = (report.get("compare") or {}).get(key) or {}
    ref = report.get("yearweek")
    week = info.get("week")
    if not week:
        return "no comparison week with data"
    text = f"{_week_label(ref)} vs {_week_label(week)}"
    if info.get("shift"):
        text += f", {_week_label(info.get('nominal'))} blank"
    return text


def _degradation(report, key):
    """Worst NOP and its two weakest cities for one comparison window."""
    branch_rows = [r for r in (report.get("branch_table") or []) if not r.get("is_regional")]
    scored = [(r.get("name"), (r.get(key) or {}).get("tsel")) for r in branch_rows]
    scored = [(name, delta) for name, delta in scored if delta is not None and delta < 0]
    if not scored:
        return None
    branch = min(scored, key=lambda item: item[1])[0]
    cities = []
    for row in report.get("city_table") or []:
        if row.get("branch") != branch:
            continue
        delta = (row.get(key) or {}).get("tsel")
        if delta is not None and delta < 0:
            cities.append((row.get("city"), delta))
    cities.sort(key=lambda item: item[1])
    names = [_title(name) for name, _ in cities[:2]]
    return branch, names


def _data_notes(report):
    """'For city X no data( since Wnn)' clause for the latest week."""
    city_last = report.get("city_last_week") or {}
    missing, zero = [], []
    for row in report.get("city_table") or []:
        if row.get("missing"):
            last = city_last.get(row.get("city"))
            missing.append((_title(row.get("city")), last))
        elif row.get("zero"):
            zero.append(_title(row.get("city")))
    clauses = []
    for name in zero[:2]:
        clauses.append(f"for city {name} no data")
    grouped = {}
    for name, last in missing:
        grouped.setdefault(last, []).append(name)
    for last, names in list(grouped.items())[:1]:
        joined = " and ".join(names[:2])
        suffix = f" since W{int(last) % 100}" if last else ""
        clauses.append(f"for {joined} no data{suffix}")
    if not clauses:
        return ""
    text = ", ".join(clauses[:2])
    return " " + text[0].upper() + text[1:] + "."


def _summary_paragraphs(report):
    """Compose the written summary, mirroring the template's paragraph structure."""
    summary = report.get("summary") or {}
    region = report.get("region_label") or "Regional"
    ref = report.get("yearweek")
    share = report.get("share") or {}

    week_no = int(ref) % 100 if ref else None
    year = str(ref)[:4] if ref else ""

    # 1. Consistent leadership ------------------------------------------------
    wins = summary.get("win_city")
    reported = summary.get("reported_city")
    trend = report.get("trend") or {}
    win_series = (trend.get("achievement") or {}).get("win") or []
    last4 = [v for v in win_series[-4:] if v is not None]
    if len(last4) >= 4 and len(set(last4)) == 1:
        period = "over the past four consecutive weeks"
    else:
        period = f"in {_week_label(ref)}"
    lead = (
        f"Telkomsel has consistently outperformed competitors, securing wins in "
        f"{wins if wins is not None else DASH} cities across the {region} area {period}."
    )
    para1 = [("Consistent Leadership", True, None), (": ", False, None),
             (lead, False, None), (_data_notes(report), False, None)]

    # 2. Dominance ------------------------------------------------------------
    para2 = [
        ("Facebook Share Dominance", True, None),
        (f": In W{week_no} of {year}", False, None),
        (", Telkomsel maintained its dominance in Facebook share at ", False, None),
        (f"{_f2(share.get('tsel'))}%", True, None),
        (f", far ahead of Indosat ({_f2(share.get('ioh'))}%) and XL Smart "
         f"({_f2(share.get('xls'))}%).", False, None),
    ]

    # 3. Score trend ----------------------------------------------------------
    wow_delta = summary.get("regional_wow")
    above = [
        r.get("name") for r in (report.get("branch_table") or [])
        if not r.get("is_regional") and ((r.get("share") or {}).get("tsel") or 0) >= 90
    ]
    total_nop = len([r for r in (report.get("branch_table") or []) if not r.get("is_regional")])
    if total_nop and len(above) == total_nop:
        nop_text = f"all {total_nop} NOP stayed above 90%"
    elif above:
        nop_text = f"{len(above)} of {total_nop} NOP stayed above 90%"
    else:
        nop_text = "no NOP reached 90%"
    para3 = [
        ("Score Trend", True, None),
        (f": Telkomsel's regional share {_verb(wow_delta)} week on week "
         f"({_f2(wow_delta)} pp) and {nop_text}; "
         f"{summary.get('win_city', DASH)} of {summary.get('reported_city', DASH)} "
         f"reported cities held WIN status.", False, None),
    ]

    # 4-6. WoW / MoM / YoY ----------------------------------------------------
    compare_paras = []
    for key, label in (("wow", "WOW"), ("mom", "MOM"), ("yoy", "YOY")):
        delta = summary.get(f"regional_{key}")
        text = f" trend ({_compare_note(report, key)}): regional {_verb(delta)} ({_f2(delta)} pp)."
        degradation = _degradation(report, key)
        if degradation:
            branch, cities = degradation
            if cities:
                text += (f" For NOP Level, degradation contributed by NOP {_title(branch)} "
                         f"city {', '.join(cities)}")
            else:
                text += f" For NOP Level, degradation contributed by NOP {_title(branch)}"
        else:
            text += " No NOP degradation recorded."
        compare_paras.append([(label, True, None), (text, False, None)])

    return [para1, para2, para3] + compare_paras


def _fill_summary(slide, report):
    shape = _find_text_shape(slide, "Summary")
    if shape is None:
        return
    tf = shape.text_frame
    paragraphs = list(tf.paragraphs)
    if not paragraphs:
        return
    # Paragraph 0 keeps the "Summary :" heading; paragraph 1 is the body template.
    template_p = paragraphs[1]._p if len(paragraphs) > 1 else paragraphs[0]._p
    for extra in paragraphs[1:]:
        extra._p.getparent().remove(extra._p)
    bodies = _summary_paragraphs(report)
    # The text box auto-grows downwards from its fixed top edge, so a long week
    # (many no-data cities) would spill off the slide. Step the font down when the
    # composed text is noticeably longer than the template's ~900 characters.
    total_chars = sum(len(t) for parts in bodies for t, _, _ in parts)
    size = Pt(8.5) if total_chars > 1000 else None
    anchor = paragraphs[0]._p
    for parts in bodies:
        new_p = copy.deepcopy(template_p)
        anchor.addnext(new_p)
        anchor = new_p
        paragraph = next(p for p in tf.paragraphs if p._p is new_p)
        for run in list(paragraph.runs):
            run._r.getparent().remove(run._r)
        bold_rpr = plain_rpr = None
        for run in template_p.findall(qn("a:r")):
            rpr = run.find(qn("a:rPr"))
            if rpr is None:
                continue
            if rpr.get("b") in ("1", "true"):
                bold_rpr = bold_rpr if bold_rpr is not None else copy.deepcopy(rpr)
            else:
                plain_rpr = plain_rpr if plain_rpr is not None else copy.deepcopy(rpr)
        for text, bold, color in parts:
            _add_run(paragraph, text, bold_rpr if bold else plain_rpr,
                     bold=bold, color=color, size=size)


# ── Slide 2: per-NOP trends ─────────────────────────────────────────────────

def _fill_nop_slide(slide, report):
    trend = report.get("trend") or {}
    weeks = trend.get("weeks") or []
    branches = trend.get("branches") or []
    branch_series = trend.get("branch_series") or {}
    charts = _charts(slide)
    if not weeks:
        return
    for index, chart in enumerate(charts):
        if index >= len(branches):
            continue
        branch = branches[index]
        data = branch_series.get(branch) or {}
        series = [
            ("_Telkomsel", data.get("tsel") or []),
            ("_IOH", data.get("ioh") or []),
            ("_XLS", data.get("xls") or []),
        ]
        _replace_chart_data(chart.chart, weeks, series)
        _set_chart_title(chart.chart, branch)


# ── Public entry point ──────────────────────────────────────────────────────

def build_fb_share_pptx(template_path, report):
    """Return the filled report deck (:class:`bytes`) for *report*.

    ``report`` is the dict assembled from ``build_fb_share_compare`` /
    ``build_fb_share_trend`` — see ``app/routes/fb_pptx_routes.py``.
    """
    prs = Presentation(template_path)
    slides = list(prs.slides)
    if not slides:
        raise ValueError("FB Share template has no slides")

    summary_slide = slides[0]
    suffix = f"R11 {report.get('region_label') or 'PUMA'} | {_week_label(report.get('yearweek'))}".strip()
    _fill_title(summary_slide, report, suffix)
    _fill_headline(summary_slide, report)
    _fill_summary(summary_slide, report)

    tables = _tables(summary_slide)
    branch_table = next((t for t in tables if len(t.table.columns) == 13), None)
    city_table = next((t for t in tables if len(t.table.columns) == 14), None)
    if branch_table is not None:
        _fill_branch_table(branch_table.table, report)
    if city_table is not None:
        _fill_city_table(city_table.table, report)

    charts = _charts(summary_slide)
    if charts:
        _fill_trend_chart(charts[0].chart, report.get("trend") or {})

    if len(slides) > 1:
        _fill_nop_slide(slides[1], report)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
