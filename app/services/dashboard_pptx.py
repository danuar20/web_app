"""Build PowerPoint presentations with native editable charts for Dashboard 4G.

Styled to match the Dashboard 4G visual design system (colors, fonts, line tension,
and card styling) inside the corporate Infra 2026 presentation template
(``app/resources/report_templates/infra_2026.pptx``, layout ``2_Three Column``).

All charts are created as NATIVE PowerPoint Line Charts (XL_CHART_TYPE.LINE),
NOT images, so users can edit or customize the chart data, series, colors,
and axes directly in PowerPoint.
"""
from __future__ import annotations

import io
import os
import re
from datetime import datetime
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor
from pptx.oxml import parse_xml
from pptx.util import Inches, Pt

_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "resources", "report_templates", "infra_2026.pptx",
)

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Standard layout positions on the 16:9 slide (13.333 x 7.5 in)
# Positioned cleanly below the header banner (y=0.74 in)
GRID_POSITIONS = {
    16: [  # 4x4 grid (16 charts per slide)
        (Inches(0.16 + (idx % 4) * (3.16 + 0.11)), Inches(0.74 + (idx // 4) * (1.58 + 0.08)), Inches(3.16), Inches(1.58))
        for idx in range(16)
    ],
    9: [  # 3x3 grid (9 charts per slide)
        (Inches(0.20 + (idx % 3) * (4.18 + 0.18)), Inches(0.76 + (idx // 3) * (2.10 + 0.12)), Inches(4.18), Inches(2.10))
        for idx in range(9)
    ],
    6: [  # 3x2 grid
        (Inches(0.20), Inches(0.76), Inches(4.18), Inches(3.22)),
        (Inches(4.57), Inches(0.76), Inches(4.18), Inches(3.22)),
        (Inches(8.95), Inches(0.76), Inches(4.18), Inches(3.22)),
        (Inches(0.20), Inches(4.10), Inches(4.18), Inches(3.22)),
        (Inches(4.57), Inches(4.10), Inches(4.18), Inches(3.22)),
        (Inches(8.95), Inches(4.10), Inches(4.18), Inches(3.22)),
    ],
    4: [  # 2x2 grid (matches slide 2 of infra_2026)
        (Inches(0.20), Inches(0.76), Inches(6.37), Inches(3.22)),
        (Inches(6.76), Inches(0.76), Inches(6.37), Inches(3.22)),
        (Inches(0.20), Inches(4.10), Inches(6.37), Inches(3.22)),
        (Inches(6.76), Inches(4.10), Inches(6.37), Inches(3.22)),
    ],
    2: [  # 1x2 side by side
        (Inches(0.30), Inches(0.80), Inches(6.26), Inches(6.40)),
        (Inches(6.76), Inches(0.80), Inches(6.26), Inches(6.40)),
    ],
    1: [  # 1 full view
        (Inches(0.40), Inches(0.80), Inches(12.53), Inches(6.40)),
    ],
}

# Typography scales tuned for compact, clean display across all grid densities
GRID_TYPOGRAPHY = {
    16: {
        "title_size": Pt(8.0),
        "cat_axis_size": Pt(6.0),
        "val_axis_size": Pt(6.0),
        "unit_size": Pt(6.0),
        "legend_size": Pt(6.0),
        "line_width": Pt(1.5),
        "gridline_width": Pt(0.5),
        "card_border_width": Pt(0.75),
        "inset_x": Inches(0.04),
        "inset_y": Inches(0.02),
        "card_radius": 0.04,
    },
    9: {
        "title_size": Pt(8.5),
        "cat_axis_size": Pt(6.5),
        "val_axis_size": Pt(6.5),
        "unit_size": Pt(6.5),
        "legend_size": Pt(7.0),
        "line_width": Pt(1.75),
        "gridline_width": Pt(0.5),
        "card_border_width": Pt(0.85),
        "inset_x": Inches(0.06),
        "inset_y": Inches(0.04),
        "card_radius": 0.035,
    },
    6: {
        "title_size": Pt(9.5),
        "cat_axis_size": Pt(7.0),
        "val_axis_size": Pt(7.0),
        "unit_size": Pt(7.0),
        "legend_size": Pt(7.5),
        "line_width": Pt(2.0),
        "gridline_width": Pt(0.65),
        "card_border_width": Pt(1.0),
        "inset_x": Inches(0.07),
        "inset_y": Inches(0.05),
        "card_radius": 0.035,
    },
    4: {
        "title_size": Pt(10.0),
        "cat_axis_size": Pt(7.5),
        "val_axis_size": Pt(7.5),
        "unit_size": Pt(7.5),
        "legend_size": Pt(8.0),
        "line_width": Pt(2.25),
        "gridline_width": Pt(0.75),
        "card_border_width": Pt(1.0),
        "inset_x": Inches(0.08),
        "inset_y": Inches(0.06),
        "card_radius": 0.035,
    },
    2: {
        "title_size": Pt(11.0),
        "cat_axis_size": Pt(8.5),
        "val_axis_size": Pt(8.5),
        "unit_size": Pt(8.5),
        "legend_size": Pt(8.5),
        "line_width": Pt(2.5),
        "gridline_width": Pt(0.75),
        "card_border_width": Pt(1.0),
        "inset_x": Inches(0.10),
        "inset_y": Inches(0.08),
        "card_radius": 0.03,
    },
    1: {
        "title_size": Pt(12.0),
        "cat_axis_size": Pt(9.0),
        "val_axis_size": Pt(9.0),
        "unit_size": Pt(9.0),
        "legend_size": Pt(9.0),
        "line_width": Pt(2.75),
        "gridline_width": Pt(0.75),
        "card_border_width": Pt(1.0),
        "inset_x": Inches(0.12),
        "inset_y": Inches(0.10),
        "card_radius": 0.025,
    },
}

# Dashboard 4G Design System Colors (exact matches to dashboard_4g.html & Chart.js)
DASHBOARD_PALETTE = {
    # Primary trend & comparison colors
    "trend": RGBColor(0x4F, 0xAC, 0xFE),       # #4facfe (Electric cyan-blue)
    "before": RGBColor(0x00, 0xE6, 0x76),      # #00e676 (Vibrant green)
    "after": RGBColor(0x4F, 0xAC, 0xFE),       # #4facfe (Electric cyan-blue)

    # 4G Band colors (matching FIXED_BAND_COLORS in dashboard_4g.html)
    "l700": RGBColor(0xF0, 0x93, 0xFB),        # #f093fb (Pink/Purple)
    "l900": RGBColor(0xFF, 0x55, 0x55),        # #ff5555 (Red)
    "l1800": RGBColor(0x4F, 0xAC, 0xFE),       # #4facfe (Cyan-blue)
    "l2100": RGBColor(0x00, 0xC8, 0x53),       # #00c853 (Green)
    "l2300_1": RGBColor(0xA7, 0x8B, 0xFA),     # #a78bfa (Lavender)
    "l2300_2": RGBColor(0xFF, 0x9F, 0x40),     # #ff9f40 (Orange)
    "l2300_3": RGBColor(0xF6, 0xC9, 0x0E),     # #f6c90e (Gold)
    "l2300": RGBColor(0xA7, 0x8B, 0xFA),       # #a78bfa (Lavender)
    "l2600_1": RGBColor(0x00, 0xE5, 0xFF),     # #00e5ff (Light Cyan)
    "l2600_2": RGBColor(0x1D, 0xE9, 0xB6),     # #1de9b6 (Teal)
    "l2600_3": RGBColor(0x76, 0xFF, 0x03),     # #76ff03 (Lime)
    "l2600": RGBColor(0x00, 0xE5, 0xFF),       # #00e5ff (Light Cyan)
    "fdd": RGBColor(0x4F, 0xAC, 0xFE),         # #4facfe (Cyan-blue)
    "tdd": RGBColor(0xA7, 0x8B, 0xFA),         # #a78bfa (Lavender)
}

# Fallback sequence matching Dashboard 4G custom chart palette
DEFAULT_SERIES_CYCLE = [
    RGBColor(0x4F, 0xAC, 0xFE),  # #4facfe
    RGBColor(0x00, 0xE6, 0x76),  # #00e676
    RGBColor(0xFF, 0x52, 0x52),  # #ff5252
    RGBColor(0xF6, 0xC9, 0x0E),  # #f6c90e
    RGBColor(0xA7, 0x8B, 0xFA),  # #a78bfa
    RGBColor(0x00, 0xE5, 0xFF),  # #00e5ff
    RGBColor(0xFF, 0x9F, 0x40),  # #ff9f40
    RGBColor(0xF0, 0x93, 0xFB),  # #f093fb
]


class PayloadError(ValueError):
    """Raised when the export payload is invalid."""


def parse_hex_color(hex_str: str | None) -> RGBColor | None:
    """Parse '#RRGGBB' or 'rgba(...)' to an RGBColor if valid."""
    if not hex_str or not isinstance(hex_str, str):
        return None
    hex_str = hex_str.strip()
    if hex_str.startswith("#"):
        h = hex_str.lstrip("#")
        if len(h) in (6, 8):
            try:
                return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            except ValueError:
                return None
    m = re.match(r"rgba?\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", hex_str, re.IGNORECASE)
    if m:
        try:
            return RGBColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def resolve_series_color(series_name: str, s_idx: int, user_color_str: str | None, ui_config: dict[str, Any] | None = None) -> RGBColor:
    """Resolve series color prioritizing dashboard UI config, band names, user color, and palette cycle."""
    parsed = parse_hex_color(user_color_str)
    if parsed:
        return parsed

    s_name_lower = series_name.strip().lower()
    ui = ui_config or {}

    if "before" in s_name_lower:
        c = parse_hex_color(ui.get("beforeColor"))
        return c if c else DASHBOARD_PALETTE["before"]
    if "after" in s_name_lower:
        c = parse_hex_color(ui.get("afterColor"))
        return c if c else DASHBOARD_PALETTE["after"]

    s_key = re.sub(r"[^a-z0-9_]+", "", s_name_lower)
    if s_key in DASHBOARD_PALETTE:
        return DASHBOARD_PALETTE[s_key]

    if s_idx == 0:
        c = parse_hex_color(ui.get("trendColor"))
        if c:
            return c

    return DEFAULT_SERIES_CYCLE[s_idx % len(DEFAULT_SERIES_CYCLE)]


def extract_unit_from_title(title: str) -> str | None:
    """Extract unit suffix from title like '4G Payload (GB)' -> 'GB'."""
    m = re.search(r"\(([^)]+)\)\s*$", title)
    if m:
        return m.group(1).strip()
    return None


def format_category_label(cat_str: Any) -> str:
    """Format 'YYYY-MM-DD' to friendly '14 Oct'."""
    s = str(cat_str).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        yr, mo, day = m.groups()
        mo_name = MONTHS[int(mo) - 1]
        return f"{int(day)} {mo_name}"
    return s


def simplify_hourly_categories(categories: list[Any]) -> list[str]:
    """Convert dense 'YYYY-MM-DD HH:MM' hourly labels into clean daily labels.

    If categories contain full date and hour, showing every label causes unreadable clutter.
    Instead, display daily date label ('14 Oct') at each date change and keep intermediate
    hourly ticks blank so points map 1:1 on the X-axis without visual collision.
    """
    sample = [str(c).strip() for c in categories if c and isinstance(c, (str, int))]
    has_date_hour = any(re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}", s) for s in sample[:12])

    if not has_date_hour:
        # Check if daily 'YYYY-MM-DD'
        has_date = any(re.match(r"^\d{4}-\d{2}-\d{2}$", s) for s in sample[:12])
        if has_date:
            return [format_category_label(c) for c in categories]
        return [str(c) for c in categories]

    # Hourly pattern: 'YYYY-MM-DD HH:MM'
    simplified: list[str] = []
    seen_dates: set[str] = set()
    for c in categories:
        s = str(c).strip()
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2}))?", s)
        if m:
            yr, mo, day, hr, mn = m.groups()
            mo_name = MONTHS[int(mo) - 1]
            date_key = f"{int(day)} {mo_name}"
            if date_key not in seen_dates:
                seen_dates.add(date_key)
                simplified.append(date_key)
            else:
                simplified.append(" ")  # Space tick preserves clean coordinate spacing without showing 'None'
        else:
            simplified.append(s)
    return simplified


def _remove_initial_slides(prs: Presentation) -> None:
    """Remove existing template slides cleanly so fresh custom slides inherit the layout."""
    r_id_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    sldIdLst = prs.slides._sldIdLst
    for slide_id in list(sldIdLst):
        rid = slide_id.get(r_id_attr)
        if rid:
            try:
                prs.part.drop_rel(rid)
            except Exception:
                pass
        sldIdLst.remove(slide_id)


def _add_header_title(slide, section: str, scope_text: str | None = None) -> None:
    """Add the banner title textbox with customizable corporate title."""
    tb = slide.shapes.add_textbox(Inches(0.09), Inches(0.0), Inches(8.5), Inches(0.72))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.05)
    tf.margin_top = Inches(0.02)
    tf.margin_right = Inches(0.05)
    tf.margin_bottom = Inches(0.02)

    p0 = tf.paragraphs[0]
    p0.space_after = Pt(2)
    r1 = p0.add_run()
    r1.text = "Dashboard 4G\n"
    r1.font.name = "Poppins"
    r1.font.size = Pt(18)
    r1.font.bold = True
    r1.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    r2 = p0.add_run()
    r2.text = "KPI Monitoring |  "
    r2.font.name = "Poppins"
    r2.font.size = Pt(13)
    r2.font.bold = True
    r2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    r3 = p0.add_run()
    r3.text = section.strip()
    r3.font.name = "Poppins"
    r3.font.size = Pt(13)
    r3.font.bold = True
    r3.font.color.rgb = RGBColor(0xFF, 0xC0, 0x00)

    if scope_text:
        r4 = p0.add_run()
        r4.text = f"   ({scope_text})"
        r4.font.name = "Segoe UI"
        r4.font.size = Pt(9.5)
        r4.font.bold = False
        r4.font.color.rgb = RGBColor(0xE2, 0xE8, 0xF0)


def build_dashboard_pptx(payload: dict[str, Any], template_path: str | None = None) -> tuple[bytes, dict[str, int]]:
    """Build a multi-slide PowerPoint deck with native editable charts styled like Dashboard 4G.

    Returns (pptx_bytes, {"charts": total_charts, "slides": total_slides}).
    """
    if not isinstance(payload, dict):
        raise PayloadError("Payload must be a dictionary")

    charts = payload.get("charts")
    if not isinstance(charts, list) or len(charts) == 0:
        raise PayloadError("Please select at least one chart to export")
    if len(charts) > 100:
        raise PayloadError("Maximum 100 charts supported per export")

    per_slide = int(payload.get("per_slide") or 4)
    if per_slide not in (1, 2, 4, 6, 9, 16):
        per_slide = 4

    section = str(payload.get("section") or "KPI Trend").strip()
    scope = payload.get("scope") or {}
    ui_config = payload.get("ui_config") or {}

    scope_parts = []
    if scope.get("date_range"):
        scope_parts.append(str(scope["date_range"]).replace("Date: ", "").strip())
    if scope.get("filter"):
        scope_parts.append(str(scope["filter"]).replace("Filter: ", "").strip())
    scope_text = " • ".join(scope_parts) if scope_parts else None

    tpl_path = template_path or _TEMPLATE_PATH
    if not os.path.exists(tpl_path):
        alt_path = os.path.join(os.path.dirname(tpl_path), "fb_share.pptx")
        if os.path.exists(alt_path):
            tpl_path = alt_path
        else:
            raise FileNotFoundError(f"Template pptx not found at {tpl_path}")

    prs = Presentation(tpl_path)
    # Ensure standard 16:9 widescreen
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Use layout 11 (2_Three Column) which has the corporate header banner
    slide_layout = prs.slide_layouts[11] if len(prs.slide_layouts) > 11 else prs.slide_layouts[-1]
    _remove_initial_slides(prs)

    positions = GRID_POSITIONS.get(per_slide, GRID_POSITIONS[4])
    typo = GRID_TYPOGRAPHY.get(per_slide, GRID_TYPOGRAPHY[4])

    total_charts = len(charts)
    slide_count = 0

    for i in range(0, total_charts, per_slide):
        group = charts[i : i + per_slide]
        slide = prs.slides.add_slide(slide_layout)
        slide_count += 1

        # Header title box
        slide_title = section
        if total_charts > per_slide:
            slide_title = f"{section} (Part {slide_count})"
        _add_header_title(slide, slide_title, scope_text)

        # Place native editable charts
        for c_idx, chart_item in enumerate(group):
            if c_idx >= len(positions):
                break
            left, top, width, height = positions[c_idx]

            title = str(chart_item.get("title") or f"Chart {i + c_idx + 1}").strip()
            raw_categories = chart_item.get("categories") or []
            categories = simplify_hourly_categories(raw_categories)
            series_list = chart_item.get("series") or []
            unit = chart_item.get("unit") or extract_unit_from_title(title)

            if not categories and not series_list:
                continue

            # 1. Add Card Container behind chart (Dashboard card elevation aesthetic)
            card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            card.line.color.rgb = RGBColor(0xE2, 0xE8, 0xF0)
            card.line.width = typo["card_border_width"]
            card.adjustments[0] = typo["card_radius"]

            # 2. Build CategoryChartData
            chart_data = CategoryChartData()
            chart_data.categories = categories

            for s_item in series_list:
                s_name = str(s_item.get("name") or "Value").strip()
                s_vals = s_item.get("values") or []
                cleaned_vals = []
                for v in s_vals:
                    if v is None:
                        cleaned_vals.append(None)
                    else:
                        try:
                            cleaned_vals.append(float(v))
                        except (ValueError, TypeError):
                            cleaned_vals.append(None)
                chart_data.add_series(s_name, cleaned_vals)

            # 3. Add Native Line Chart inside card
            inset_x = typo["inset_x"]
            inset_y = typo["inset_y"]
            chart_shape = slide.shapes.add_chart(
                XL_CHART_TYPE.LINE,
                left + inset_x,
                top + inset_y,
                width - (2 * inset_x),
                height - (2 * inset_y),
                chart_data
            )
            ch = chart_shape.chart

            # 4. Chart Title (Poppins, reduced & proportional font size)
            ch.has_title = True
            ch.chart_title.text_frame.text = title
            p_title = ch.chart_title.text_frame.paragraphs[0]
            p_title.font.name = "Poppins"
            p_title.font.size = typo["title_size"]
            p_title.font.bold = True
            p_title.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)

            # 5. Legend (Bottom, Segoe UI, compact font size)
            ch.has_legend = len(series_list) > 1
            if ch.has_legend:
                ch.legend.position = XL_LEGEND_POSITION.BOTTOM
                ch.legend.font.name = "Segoe UI"
                ch.legend.font.size = typo["legend_size"]
                ch.legend.font.color.rgb = RGBColor(0x33, 0x41, 0x55)

            # 6. Value Axis (Y Axis) - clean horizontal gridlines & compact font size
            val_ax = ch.value_axis
            val_ax.has_major_gridlines = True
            val_ax.major_gridlines.format.line.color.rgb = RGBColor(0xE2, 0xE8, 0xF0)
            val_ax.major_gridlines.format.line.width = typo["gridline_width"]
            val_ax.tick_labels.font.name = "Segoe UI"
            val_ax.tick_labels.font.size = typo["val_axis_size"]
            val_ax.tick_labels.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

            # Only show Y axis title on spacious grids (<= 6 charts) to avoid clutter
            if unit and per_slide <= 6:
                val_ax.has_title = True
                val_ax.axis_title.text_frame.text = unit
                p_unit = val_ax.axis_title.text_frame.paragraphs[0]
                p_unit.font.name = "Segoe UI"
                p_unit.font.size = typo["unit_size"]
                p_unit.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

            # 7. Category Axis (X Axis) - clean Segoe UI labels, compact font size
            cat_ax = ch.category_axis
            cat_ax.tick_labels.font.name = "Segoe UI"
            cat_ax.tick_labels.font.size = typo["cat_axis_size"]
            cat_ax.tick_labels.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

            # Prevent PowerPoint auto-skipping labels which causes sparse/blank labels
            # on dense hourly/daily category sets. Explicitly enforce tickLblSkip and tickMarkSkip = 1.
            try:
                auto_elem = cat_ax._element.find("{http://schemas.openxmlformats.org/drawingml/2006/chart}auto")
                if auto_elem is not None:
                    cat_ax._element.remove(auto_elem)

                ns_c = "http://schemas.openxmlformats.org/drawingml/2006/chart"
                cat_ax._element.append(parse_xml(f'<c:tickLblSkip xmlns:c="{ns_c}" val="1"/>'))
                cat_ax._element.append(parse_xml(f'<c:tickMarkSkip xmlns:c="{ns_c}" val="1"/>'))

                # If lots of categories (> 15), slightly rotate labels (-45 deg or -90 deg) for readability
                if len(categories) > 15:
                    txPr = cat_ax._element.find("{http://schemas.openxmlformats.org/drawingml/2006/chart}txPr")
                    if txPr is not None:
                        bodyPr = txPr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}bodyPr")
                        if bodyPr is not None:
                            bodyPr.set("rot", "-5400000")  # -90 degrees
            except Exception:
                pass

            # 8. Series Line Styling: smooth curved line (tension 0.4), dashboard colors, scaled width
            plot = ch.plots[0]
            for s_idx, ser in enumerate(plot.series):
                ser.smooth = True  # Smooth curved lines matching Chart.js tension 0.4
                ser.format.line.width = typo["line_width"]
                s_item = series_list[s_idx] if s_idx < len(series_list) else {}
                color = resolve_series_color(
                    ser.name,
                    s_idx,
                    s_item.get("color"),
                    ui_config
                )
                ser.format.line.color.rgb = color

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), {"charts": total_charts, "slides": slide_count}
