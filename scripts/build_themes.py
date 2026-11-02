# -*- coding: utf-8 -*-
"""
build_themes.py — NetKPI theme compiler.

Generates static/css/skins/<skin>.css from the existing dark/light rules
found inside <style> blocks of templates/*.html.

Architecture
------------
The app keeps `data-theme="light|dark"` on <html> as the *mode* attribute:
every existing `[data-theme="..."]` rule and every JS `isDark` check keeps
working untouched. A new attribute `data-skin="<id>"` marks the active skin.
Each generated skin file re-declares every colour-bearing rule of its mode,
re-scoped under `[data-skin="<id>"]`, with colour literals remapped onto the
skin palette. Skin files are loaded LAST in <body> so they win the cascade
(child templates' <style> blocks live earlier in the document); the source
`!important` flag is preserved per declaration.

Colour mapping heuristics (source of truth is this file)
---------------------------------------------------------
* Neutral (saturation < 0.28): mapped onto the skin's neutral ramps by
  lightness rank. Backgrounds use the surface ramp, text uses the text ramp,
  low-alpha whites/blacks keep their alpha on the new neutral.
* Saturated colours map by hue family onto the skin's single accent or its
  semantic status colours (pass/warn/breach), preserving lightness *delta*
  vs the source family's anchor colour so dark/light variants survive.
* Accent gradients (the #4facfe -> #00f2fe family) are flattened to a solid
  accent; neutral gradients keep their stops remapped.
* box-shadow collapses to one neutral elevation shadow (anti-glow).

Re-run after editing templates:  python scripts/build_themes.py
"""

import os
import re
import glob
import colorsys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(ROOT, "templates")
OUT_DIR = os.path.join(ROOT, "static", "css", "skins")

# ---------------------------------------------------------------------------
# Skin palettes (single source of truth; also mirrored into base.html JS
# registry by hand — keep in sync).
# ---------------------------------------------------------------------------
# Each skin: mode, human name, purpose (shown in the picker), swatches for
# the picker card, and token ramps.
#   surf: 5 stops from page background (darkest/lowest) to strongest surface
#   text: 4 stops from muted to strongest
SKINS = {
    "midnight": {
        "mode": "dark",
        "name": "Midnight",
        "purpose": "Low-glare violet ink surfaces for night-shift monitoring",
        "swatch": ["#0b0e1c", "#171d38", "#7f8dfc"],
        "bg": "#0b0e1c",
        "surf": ["#0b0e1c", "#12162b", "#171d38", "#1e2547", "#263057"],
        "text": ["#9da6c5", "#c2c9e2", "#f0f3fd", "#ffffff"],
        "line": "#262e50",
        "accent": "#7f8dfc",
        "pass": "#43d391",
        "warn": "#e3b262",
        "breach": "#ff6e84",
        "shadow": "rgba(2, 4, 14, 0.55)",
        "chart": ["#7f8dfc", "#43d391", "#e3b262", "#ff6e84", "#58c6d8", "#c99cf0", "#f0917a", "#9fb0ff"],
    },
    "ember": {
        "mode": "dark",
        "name": "Ember",
        "purpose": "Warm charcoal with a single copper accent, long incident reviews",
        "swatch": ["#14110e", "#231d17", "#d08a52"],
        "bg": "#14110e",
        "surf": ["#14110e", "#1c1712", "#231d17", "#2b241c", "#342b21"],
        "text": ["#b0a090", "#d4c8bb", "#f7f1eb", "#ffffff"],
        "line": "#332a20",
        "accent": "#d08a52",
        "pass": "#7fae6e",
        "warn": "#e0a33f",
        "breach": "#e0564a",
        "shadow": "rgba(10, 6, 3, 0.55)",
        "chart": ["#d08a52", "#7fae6e", "#e0a33f", "#e0564a", "#c9a227", "#8ba888", "#b8763e", "#e6c37a"],
    },
    "paper": {
        "mode": "light",
        "name": "Paper",
        "purpose": "Warm print-style surfaces for weekly reporting decks",
        "swatch": ["#f1ede4", "#fffdf9", "#2f4f66"],
        "bg": "#f1ede4",
        "surf": ["#e6e0d3", "#f1ede4", "#faf7f0", "#fffdf9", "#ffffff"],
        "text": ["#6e6758", "#454035", "#1c1813", "#000000"],
        "line": "#d9d2c2",
        "accent": "#2f4f66",
        "pass": "#2e7d4d",
        "warn": "#a96f12",
        "breach": "#a8342a",
        "shadow": "rgba(42, 38, 32, 0.14)",
        "chart": ["#2f4f66", "#2e7d4d", "#a96f12", "#a8342a", "#6b7f54", "#805d8c", "#c07f3e", "#4a6b8a"],
    },
    "signal": {
        "mode": "light",
        "name": "Signal",
        "purpose": "High-contrast daylight theme for field ops and projectors",
        "swatch": ["#f3f5f4", "#ffffff", "#0f766e"],
        "bg": "#f3f5f4",
        "surf": ["#e6eae8", "#f3f5f4", "#fcfdfd", "#ffffff", "#ffffff"],
        "text": ["#525c56", "#353c38", "#121714", "#000000"],
        "line": "#d2d9d5",
        "accent": "#0f766e",
        "pass": "#15803d",
        "warn": "#b45309",
        "breach": "#b91c1c",
        "shadow": "rgba(12, 17, 14, 0.12)",
        "chart": ["#0f766e", "#15803d", "#b45309", "#b91c1c", "#1d4ed8", "#7c3aed", "#be6d12", "#334155"],
    },
}

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(s):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(v)))) for v in rgb))


def rgba_str(rgb, a):
    return "rgba({}, {}, {}, {})".format(*(int(round(v)) for v in rgb), a)


def hsl_of(rgb):
    r, g, b = [v / 255.0 for v in rgb]
    h, l, s = colorsys.rgb_to_hls(r, g, b)  # note: colorsys order is hls
    return h * 360.0, s, l


def hsl_to_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb((h % 360.0) / 360.0, l, s)
    return (r * 255.0, g * 255.0, b * 255.0)


def lerp(c1, c2, t):
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))


def ramp_pick(ramp_rgb, t):
    """Interpolate along a ramp (list of rgb) with t in 0..1."""
    t = max(0.0, min(1.0, t))
    n = len(ramp_rgb) - 1
    pos = t * n
    i = min(int(pos), n - 1)
    return lerp(ramp_rgb[i], ramp_rgb[i + 1], pos - i)


# Source anchors (measured from the app's existing palettes)
SRC_ACCENT = "#4facfe"
SRC_PASS = "#00e676"
SRC_BREACH = "#ff5252"
SRC_WARN = "#ffd166"

COLOR_RE = re.compile(
    r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b"
    r"|rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)"
)

NAMED = {"white": "#ffffff", "black": "#000000", "transparent": None}


def parse_color(token):
    """-> (rgb, alpha) or None."""
    token = token.strip().lower()
    if token in NAMED:
        v = NAMED[token]
        return (hex_to_rgb(v), 1.0) if v else None
    if token.startswith("#"):
        return hex_to_rgb(token), 1.0
    m = re.match(r"rgba?\((.*?)\)", token)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        rgb = tuple(float(p) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return rgb, a
    return None


def family_of(h, s, rgb=None):
    """Hue family of a saturated colour. Returns 'accent'/'pass'/'warn'/'breach'.

    Neutrals are decided by *chroma* (max-min channel spread), not HSL
    saturation: dark slate colours like #0f172a or #64748b have low chroma but
    high HSL saturation, and must stay neutral instead of becoming accent.
    """
    if rgb is not None:
        chroma = (max(rgb) - min(rgb)) / 255.0
        _, _, l = hsl_of(rgb)
        if chroma <= 0.18 or (chroma <= 0.28 and l < 0.22):
            return None
    elif s < 0.28:
        return None
    if 15 < h < 345:
        if 170 <= h <= 270:
            return "accent"
        if 115 <= h < 170:
            return "pass"
        if 25 < h < 115:
            return "warn"
        if 270 < h < 345:
            return "accent"
    return "breach"


def opposite_text_ramp(skin):
    """Text ramp for an *inverted island*: a surface whose polarity is the
    opposite of the skin mode (a dark banner inside a light theme, a white card
    inside a dark theme). Ordered weak -> strong."""
    text = [hex_to_rgb(c) for c in skin["text"]]
    if skin["mode"] == "light":
        ink = text[3]
        paper = hex_to_rgb(skin["surf"][4])
        return [lerp(ink, paper, t) for t in (0.55, 0.72, 0.86, 1.0)]
    light = text[3]
    base = hex_to_rgb(skin["bg"])
    return [lerp(base, light, t) for t in (0.30, 0.18, 0.10, 0.04)]


def map_color(token, skin, prop=""):
    """Map one source colour literal onto the skin palette."""
    parsed = parse_color(token)
    if not parsed:
        return token
    (r, g, b), a = parsed
    mode = skin["mode"]
    h, s, l = hsl_of((r, g, b))
    is_text = prop in ("color", "fill", "stroke", "caret-color")

    fam = family_of(h, s, (r, g, b))

    if fam is None:
        # ---- neutral ----
        surf = [hex_to_rgb(c) for c in skin["surf"]]
        text = [hex_to_rgb(c) for c in skin["text"]]
        if a < 0.6 and (r > 235 and g > 235 and b > 235):
            # low-alpha white overlay -> skin's strong text as overlay
            out = ramp_pick(text, 0.85)
            return rgba_str(out, a)
        if a < 0.6 and max(r, g, b) < 20:
            # low-alpha pure black overlay -> black veil (or ink veil in light)
            out = (0, 0, 0) if mode == "dark" else hex_to_rgb(skin["text"][-1])
            return rgba_str(out, a)
        if mode == "dark":
            if l < 0.45 and not is_text:   # surface
                t = (l - 0.075) / (0.265 - 0.075)
                out = ramp_pick(surf, t)
            elif l < 0.35:                 # dark text on a light island
                u = (0.35 - l) / 0.35
                out = ramp_pick(opposite_text_ramp(skin), u)
            elif l >= 0.45 and not is_text:  # light surface (white card)
                t = (l - 0.35) / (1.0 - 0.35)
                out = ramp_pick(text, t)
            else:                           # light text on dark shell
                t = (l - 0.35) / (1.0 - 0.35)
                out = ramp_pick(text, t)
        else:
            if l > 0.55 and not is_text:   # light surface: higher L = whiter
                t = (l - 0.885) / (1.0 - 0.885)
                out = ramp_pick(surf, t)
            elif l > 0.60:                 # light text on a dark island
                u = (l - 0.60) / 0.40
                out = ramp_pick(opposite_text_ramp(skin), u)
            else:
                if is_text:
                    # dark text on light surfaces: lower L = stronger emphasis
                    t = 1.0 - (l - 0.10) / 0.50
                    out = ramp_pick(text, t)
                else:
                    # dark surface in a light theme: it stays dark (inverted
                    # island like the OKR banner), tinted by the ink anchor
                    ink = hex_to_rgb(skin["text"][3])
                    paper = hex_to_rgb(skin["surf"][4])
                    out = lerp(ink, lerp(ink, paper, 0.25), min(1.0, l / 0.55))
        if a < 1.0:
            if is_text:
                # keep a legibility floor: hierarchy survives, 35%-alpha labels do not
                a = max(a, 0.62)
            return rgba_str(out, a)
        return rgb_to_hex(out)

    # ---- saturated family ----
    fam_rgb = hex_to_rgb(skin[fam])
    fh, fs, fl = hsl_of(fam_rgb)
    anchor = {"accent": SRC_ACCENT, "pass": SRC_PASS, "warn": SRC_WARN, "breach": SRC_BREACH}[fam]
    _, _, al = hsl_of(hex_to_rgb(anchor))
    # Blend toward white / page ink instead of pure HSL lightness shifts: a
    # darkened accent keeps its hue but stops turning neon (e.g. #0620f1).
    delta = l - al
    if delta >= 0:
        out = lerp(fam_rgb, (255, 255, 255), min(1.0, delta * 0.95))
    else:
        base = hex_to_rgb(skin["surf"][1]) if mode == "dark" else hex_to_rgb(skin["text"][3])
        out = lerp(fam_rgb, base, min(1.0, -delta * 1.35))
    return rgba_str(out, a) if a < 1.0 else rgb_to_hex(out)


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------

COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
STYLE_RE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)
THEME_ATTR_RE = re.compile(r"\[data-theme\s*=\s*(['\"])(dark|light)\1\]")


def extract_css():
    chunks = []
    for path in sorted(glob.glob(os.path.join(TEMPLATES, "*.html"))):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for m in STYLE_RE.finditer(text):
            chunks.append((os.path.basename(path), m.group(1)))
    return chunks


def split_top_level(css):
    """Split css text into a list of nodes: ('rule', selector, body) or
    ('at', at_header, [child nodes]). Ignores stray text."""
    css = COMMENT_RE.sub("", css)
    nodes = []
    i, n = 0, len(css)
    while i < n:
        # skip whitespace
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            break
        # read up to '{' or ';'
        j = i
        depth = 0
        while j < n and (css[j] != "{" or depth > 0):
            if css[j] == "{" and depth == 0:
                break
            if css[j] == "(":
                depth += 1
            elif css[j] == ")":
                depth -= 1
            j += 1
        header = css[i:j].strip()
        if j >= n or css[j] != "{":
            # stray text / at-statement like @charset; skip to next ';'
            i = j + 1
            continue
        # find matching close brace
        depth = 1
        k = j + 1
        while k < n and depth > 0:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        body = css[j + 1:k - 1]
        if header.startswith("@"):
            name = header.split()[0]
            if name in ("@media", "@supports"):
                nodes.append(("at", header, split_top_level(body)))
            # @keyframes/@font-face dropped from skins (layout-agnostic, and
            # they are mode-independent so the base ones still apply)
        else:
            nodes.append(("rule", header, body))
        i = k
    return nodes


def split_decls(body):
    """Split declaration block into (prop, value, important)."""
    decls = []
    for chunk in body.split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        prop, value = prop.strip(), value.strip()
        if not prop or not value:
            continue
        important = False
        if value.endswith("!important"):
            important = True
            value = value[: -len("!important")].strip()
        decls.append((prop, value, important))
    return decls


COLORISH = re.compile(r"color|background|border|outline|shadow|fill|stroke|caret")


def rel_lum(rgb):
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def readable_on(base_rgb, dark_rgb, light_rgb):
    """Pick the text tone that reads on base_rgb."""
    return dark_rgb if rel_lum(base_rgb) > 0.42 else light_rgb


def page_var_color(name, skin):
    """Per-page design tokens (--hs-*, --ran-*, --rhi-*, --redcov-*, --cei-*,
    --sow-*). Those pages ship their own light/dark token sets, so map them by
    role onto the skin ramps instead of letting the generic heuristic run."""
    prefix = None
    for p in ("--hs-", "--ran-", "--rhi-", "--redcov-", "--cei-", "--sow-"):
        if name.startswith(p):
            prefix = p
            break
    if not prefix:
        return None
    suffix = name[len(prefix):]
    surf = [hex_to_rgb(c) for c in skin["surf"]]
    text = [hex_to_rgb(c) for c in skin["text"]]
    dark = skin["mode"] == "dark"
    accent = hex_to_rgb(skin["accent"])
    passc = hex_to_rgb(skin["pass"])
    breach = hex_to_rgb(skin["breach"])
    paper = surf[4] if not dark else surf[0]
    ink = text[3]

    if "shadow" in suffix:
        return None
    if suffix in ("bg", "background"):
        return skin["bg"]
    if "card" in suffix or "surface" in suffix or "panel" in suffix:
        return rgb_to_hex(surf[3] if not dark else surf[2])
    if "border" in suffix or "line" in suffix:
        return skin["line"]
    if "muted" in suffix or "sub" in suffix:
        return rgb_to_hex(text[0])
    if "danger" in suffix or "fail" in suffix or "breach" in suffix:
        if "bg" in suffix:
            return rgb_to_hex(lerp(breach, surf[2] if dark else paper, 0.82))
        if "dark" in suffix:
            return "#7f1d1d" if not dark else rgb_to_hex(lerp(breach, hex_to_rgb(skin["bg"]), 0.50))
        if "header" in suffix:
            return "#b91c1c" if not dark else rgb_to_hex(lerp(breach, hex_to_rgb(skin["bg"]), 0.32))
        return rgb_to_hex(lerp(breach, ink, 0.25) if not dark else lerp(breach, (255, 255, 255), 0.35))
    if "ok" in suffix or "good" in suffix or "pass" in suffix:
        if "bg" in suffix:
            return rgb_to_hex(lerp(passc, surf[2] if dark else paper, 0.82))
        return rgb_to_hex(lerp(passc, ink, 0.35) if not dark else lerp(passc, (255, 255, 255), 0.3))
    if "text" in suffix or "fg" in suffix or "foreground" in suffix:
        return rgb_to_hex(text[2])
    if "accent" in suffix or "primary" in suffix or "active-bg" in suffix:
        return skin["accent"]
    if "active-text" in suffix:
        return rgb_to_hex(readable_on(accent, ink if not dark else hex_to_rgb(skin["bg"]), paper))
    return None


def var_color(name, skin):
    """Shell anchor variables are mapped by name, not by heuristic: they carry
    the page background, body text and sidebar shell, so they must land exactly
    on the skin's anchors."""
    surf = [hex_to_rgb(c) for c in skin["surf"]]
    text = [hex_to_rgb(c) for c in skin["text"]]
    dark = skin["mode"] == "dark"
    if name == "--bg-main":
        return skin["bg"]
    if name == "--text-main":
        return skin["text"][2]
    if name == "--bg-sidebar":
        base = surf[2] if dark else surf[3]
        return rgba_str(base, 0.78 if dark else 0.92)
    if name == "--border-sidebar":
        return skin["line"]
    if name == "--nk-grid":
        return rgba_str(text[2], 0.08)
    # Page-level variables from unbalance_prb and siblings:
    if name == "--bg":
        return skin["bg"]
    if name == "--text":
        return skin["text"][2]
    if name == "--muted":
        return skin["text"][1]
    if name == "--surface":
        return skin["surf"][2] if dark else skin["surf"][3]
    if name == "--surface-solid":
        return skin["surf"][2] if dark else skin["surf"][4]
    if name == "--surface2":
        return skin["surf"][3] if dark else skin["surf"][2]
    if name == "--border":
        return skin["line"]
    if name == "--border-subtle":
        return skin["line"]
    if name == "--accent":
        return skin["accent"]
    page = page_var_color(name, skin)
    if page:
        return page
    return None


def transform_value(prop, value, skin):
    p = prop.lower()
    if p.startswith("--"):
        fixed = var_color(p, skin)
        if fixed:
            return fixed
        # unknown custom property (e.g. a page-local token): map its colour value
        # heuristically instead of dropping it
        if COLOR_RE.search(value) and "gradient" not in value:
            return COLOR_RE.sub(lambda m: map_color(m.group(0), skin, p), value)
        return None
    if "gradient" in value:
        if "transparent" in value:
            # halo / glow layer: drop it (anti-slop R-13 — no decorative glow)
            return "none"
        stops = [parse_color(c) for c in COLOR_RE.findall(value)]
        stops = [s for s in stops if s]
        bright_accent = stops and all(
            family_of(*hsl_of(s[0])[:2], s[0]) == "accent" and hsl_of(s[0])[2] > 0.45 and s[1] >= 0.9
            for s in stops
        )
        if p.startswith("background") and bright_accent:
            # the #4facfe -> #00f2fe brand gradient becomes one solid accent
            return "var(--nk-accent)"
        # tints and neutral gradients keep their character, stops remapped
        return COLOR_RE.sub(lambda m: map_color(m.group(0), skin, p), value)
    if p in ("box-shadow", "text-shadow"):
        if value.strip().lower() in ("none", "0"):
            return value
        return "var(--nk-shadow-1)" if p == "box-shadow" else "none"
    if COLOR_RE.search(value):
        return COLOR_RE.sub(lambda m: map_color(m.group(0), skin, p), value)
    return None  # no colour here


def compile_skin(skin_id, skin):
    """Collect every colour-bearing declaration of the skin's mode and emit it
    re-scoped under [data-skin="<id>"]."""
    sel = '[data-skin="{}"]'.format(skin_id)
    mode = skin["mode"]

    # ordered map: (wrappers, selector_tuple, prop) -> (value, important)
    collected = {}
    order = []

    def norm_selector(raw):
        parts = []
        for single in raw.split(","):
            single = re.sub(r"\s+", " ", single).strip()
            if not single:
                continue
            if single in (":root", "html"):
                parts.append(sel)
            else:
                parts.append(sel + " " + single)
        return tuple(parts)

    def walk(nodes, wrappers):
        for node in nodes:
            if node[0] == "at":
                walk(node[2], wrappers + (node[1],))
                continue
            _, selector, body = node
            # When compiling a DARK skin, if the selector already carried
            # [data-theme="light"], skip it completely!
            if mode == "dark" and '[data-theme="light"]' in selector:
                continue
            if mode == "light" and '[data-theme="dark"]' in selector:
                continue

            _is_dark_rule = False
            m = THEME_ATTR_RE.search(selector)
            if m:
                if m.group(2) != mode:
                    continue
                _is_dark_rule = (m.group(2) == "dark")
                base_sel = THEME_ATTR_RE.sub("", selector).strip()
            else:
                base_sel = selector.strip()
            if not base_sel:  # bare [data-theme="dark"] block (CSS variables)
                base_sel = ":root"
            # When compiling a DARK skin, ignore base rules that came from an
            # unthemed/light block (e.g. bare `.filter-card { background: #fff }`).
            # Dark skins only take rules that were either under [data-theme="dark"]
            # or don't hardcode light surfaces.
            if mode == "dark" and not _is_dark_rule:
                # drop unthemed light card/surface/background rules so they don't overwrite dark surfaces
                pass
            decls = []
            for prop, value, important in split_decls(body):
                pl = prop.lower()
                is_var = pl.startswith("--")
                if not is_var and not COLORISH.search(pl):
                    continue
                # In DARK skins, if a rule was NOT scoped under [data-theme="dark"]
                # and hardcodes a light surface (e.g. background: #fff / background: white),
                # do NOT let it overwrite dark surfaces.
                if mode == "dark" and not _is_dark_rule and pl in ("background", "background-color"):
                    pcol = parse_color(value)
                    if pcol and pcol[1] > 0.8 and hsl_of(pcol[0])[2] > 0.8:
                        continue
                new = transform_value(pl, value, skin)
                if new is not None:
                    decls.append((prop, new, important))
            if not decls:
                continue
            parts = norm_selector(base_sel)
            if not parts:
                continue
            for prop, value, important in decls:
                key = (wrappers, parts, prop)
                if prop.lower() in ("background", "background-color") and any(
                    p.endswith(" body") or p == "body" for p in parts
                ):
                    # the page background is a shell anchor: always the skin bg,
                    # never a heuristic surface colour
                    value = "var(--nk-bg)"
                if key not in collected:
                    order.append(key)
                collected[key] = (value, important)

    for _fname, css in extract_css():
        walk(split_top_level(css), ())

    # group consecutive keys sharing (wrappers, selector) into one block
    out, buf_key, buf_lines = [], None, []

    def flush():
        if buf_key is None:
            return
        wrappers, parts = buf_key
        rule = ",\n".join(parts) + " {\n" + "\n".join(buf_lines) + "\n}"
        for w in reversed(wrappers):
            rule = w + " {\n" + rule + "\n}"
        out.append(rule)

    for key in order:
        wrappers, parts, prop = key
        value, important = collected[key]
        if buf_key != (wrappers, parts):
            flush()
            buf_key, buf_lines = (wrappers, parts), []
        buf_lines.append("    {}: {}{};".format(prop, value, " !important" if important else ""))
    flush()
    return out


# ---------------------------------------------------------------------------
# Skin file header + hand-authored craft layer
# ---------------------------------------------------------------------------

def token_block(skin_id, skin):
    acc = hex_to_rgb(skin["accent"])
    lines = [
        ':root[data-skin="{}"] {{'.format(skin_id),
        "    --nk-bg: {};".format(skin["bg"]),
        "    --nk-surface-1: {};".format(skin["surf"][1]),
        "    --nk-surface-2: {};".format(skin["surf"][2]),
        "    --nk-surface-3: {};".format(skin["surf"][3]),
        "    --nk-text-1: {};".format(skin["text"][2]),
        "    --nk-text-2: {};".format(skin["text"][1]),
        "    --nk-text-3: {};".format(skin["text"][0]),
        "    --nk-line: {};".format(skin["line"]),
        "    --nk-accent: {};".format(skin["accent"]),
        "    --nk-accent-soft: {};".format(rgba_str(acc, 0.14)),
        "    --nk-pass: {};".format(skin["pass"]),
        "    --nk-warn: {};".format(skin["warn"]),
        "    --nk-breach: {};".format(skin["breach"]),
        "    --nk-shadow-1: 0 6px 24px {};".format(skin["shadow"]),
        "    --nk-island-label: {};".format(
            rgb_to_hex(lerp(hex_to_rgb(skin["text"][2]), (255, 255, 255), 0.55))
        ),
        "    --nk-grid: {};".format(
            rgba_str(hex_to_rgb(skin["text"][2]), 0.08)
        ),
    ]
    for i, c in enumerate(skin["chart"], start=1):
        lines.append("    --nk-chart-{}: {};".format(i, c))
    # The OKR pages reference shadcn-style tokens (--card, --border, --foreground,
    # --muted-foreground, ...) that are never defined anywhere in the app, so
    # those declarations currently resolve to nothing. Define them inside skin
    # scope only — the default palettes keep their current rendering.
    # Note: shadcn defines --muted as a surface, but Unbalance PRB and sibling
    # pages define --muted as a text color (muted text). To keep both working,
    # --muted is assigned to the muted text token, and --muted-bg to the surface.
    lines.extend([
        "    --background: var(--nk-bg);",
        "    --foreground: var(--nk-text-1);",
        "    --card: var(--nk-surface-2);",
        "    --card-foreground: var(--nk-text-1);",
        "    --popover: var(--nk-surface-2);",
        "    --popover-foreground: var(--nk-text-1);",
        "    --primary: var(--nk-accent);",
        "    --muted: var(--nk-text-2);",
        "    --muted-foreground: var(--nk-text-2);",
        "    --muted-bg: var(--nk-surface-1);",
        "    --secondary: var(--nk-surface-2);",
        "    --accent: var(--nk-accent);",
        "    --destructive: var(--nk-breach);",
        "    --border: var(--nk-line);",
        "    --input: var(--nk-line);",
        "    --ring: var(--nk-accent);",
    ])
    lines.append("}")
    return "\n".join(lines)


def craft_layer(skin_id):
    """Hand-authored anti-slop craft layer: solid surfaces, no glow, single
    accent discipline, real focus rings, tabular numerals."""
    s = '[data-skin="{}"]'.format(skin_id)
    return """
/* ── craft layer (hand-authored, see scripts/build_themes.py) ── */
{s} .sidebar,
{s} .topbar {{
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
}}

{s} .card,
{s} .kpi-card,
{s} .table-card {{
    box-shadow: none;
    border: 1px solid var(--nk-line);
}}

{s} .card:hover,
{s} .kpi-card:hover {{
    box-shadow: none;
}}

{s} .theme-toggle-btn:hover,
{s} .menu-item:hover,
{s} .btn:hover {{
    box-shadow: none;
}}

/* one deliberate accent: active nav keeps a single accent bar, no glow */
{s} .menu-item.active {{
    background: var(--nk-accent-soft) !important;
    color: var(--nk-accent) !important;
    border-left-color: var(--nk-accent) !important;
}}

{s} .sub-item.active {{
    color: var(--nk-accent) !important;
    font-weight: 700 !important;
}}

{s} .menu-item:hover,
{s} .sub-item:hover {{
    color: var(--nk-accent) !important;
}}

/* primary action buttons stay matte on the skin accent: no glowing gradients */
{s} .btn-apply,
{s} button[type="submit"].btn-apply,
{s} a.btn-apply,
{s} .btn-load {{
    background: var(--nk-accent) !important;
    background-image: none !important;
    color: #ffffff !important;
    box-shadow: none !important;
}}

{s} .btn-load:hover,
{s} .btn-apply:hover,
{s} button[type="submit"].btn-apply:hover {{
    background: var(--nk-accent) !important;
    box-shadow: none !important;
    opacity: 0.92;
}}

/* form controls (radio/checkbox) follow the skin accent */
{s} input[type="radio"],
{s} input[type="checkbox"] {{
    accent-color: var(--nk-accent);
}}

/* tab buttons in capacity & monitoring pages */
{s} .tab-btn {{
    background: transparent !important;
}}
{s} .tab-btn.active {{
    color: var(--nk-accent) !important;
    background: transparent !important;
    border-bottom-color: var(--nk-accent) !important;
}}
{s} .tab-btn:hover {{
    color: var(--nk-accent) !important;
    background: var(--nk-accent-soft) !important;
}}

/* excel export button text */
{s} .btn-xlsx {{
    background: var(--nk-pass) !important;
    color: #ffffff !important;
    box-shadow: none !important;
}}

/* brand mark follows the skin accent instead of the blue gradient */
{s} .sidebar-logo svg stop {{
    stop-color: var(--nk-accent);
}}

/* user avatar in topbar matches the skin accent */
{s} .account-avatar {{
    background: var(--nk-accent) !important;
    background-image: none !important;
    box-shadow: none !important;
}}

/* topbar title follows the skin text color */
{s} .topbar-title {{
    color: var(--nk-text-1) !important;
}}

/* readable data: tabular numerals so KPI columns never wobble */
{s} .data-table td,
{s} .data-table th,
{s} .kpi-value,
{s} .kpi-num {{
    font-variant-numeric: tabular-nums;
}}

/* ensure all input placeholders stay clearly legible across themes */
{s} input::placeholder,
{s} textarea::placeholder {{
    color: var(--nk-text-3) !important;
    opacity: 0.85 !important;
}}

/* form labels and filter titles must meet WCAG AA */
{s} .filter-group label,
{s} .filter-title,
{s} .filter-label,
{s} .exp-label,
{s} .menu-section-label,
{s} .sidebar-brand-sub,
{s} .topbar-sub {{
    color: var(--nk-text-2) !important;
}}

/* ── Universal overrides for inline-styled cyan/blue accents and backgrounds ── */
{s} [style*="color:#4facfe"],
{s} [style*="color: #4facfe"],
{s} [style*="color:#0284c7"],
{s} [style*="color: #0284c7"],
{s} [style*="color:#38bdf8"],
{s} [style*="color: #38bdf8"],
{s} [style*="color:#00f2fe"],
{s} [style*="color: #00f2fe"] {{
    color: var(--nk-accent) !important;
}}

{s} [style*="background: rgba(79,172,254"],
{s} [style*="background: rgba(79, 172, 254"],
{s} [style*="background:rgba(79,172,254"],
{s} [style*="background:rgba(79, 172, 254"],
{s} [style*="background: #4facfe"],
{s} [style*="background:#4facfe"] {{
    background: var(--nk-accent-soft) !important;
}}

{s} [style*="border: 1px solid rgba(79,172,254"],
{s} [style*="border: 1px solid rgba(79, 172, 254"],
{s} [style*="border: 1px dashed rgba(79,172,254"],
{s} [style*="border: 1px dashed rgba(79, 172, 254"],
{s} [style*="border-color: rgba(79,172,254"],
{s} [style*="border-color: rgba(79, 172, 254"],
{s} [style*="border-color: #4facfe"],
{s} [style*="border-color:#4facfe"] {{
    border-color: var(--nk-line) !important;
}}

/* ── Dashboard submenu: Range card, preset buttons, date labels, and tabs ── */
{s} .filter-toggle-bar i,
{s} .filter-toggle-bar .fa-sliders-h {{
    color: var(--nk-accent) !important;
}}

{s} .date-panel span[style*="Range:"],
{s} .filter-panel span[style*="Range:"],
{s} .date-panel label[style*="Show Comparison Shading"],
{s} .filter-panel label[style*="Show Comparison Shading"],
{s} #sitePasteCount,
{s} #clusterFilterBadge {{
    color: var(--nk-accent) !important;
}}

{s} .date-label {{
    color: var(--nk-text-1) !important;
    opacity: 0.9 !important;
}}

{s} .btn-xs {{
    border-color: var(--nk-line) !important;
    color: var(--nk-text-1) !important;
}}

{s} .btn-xs:hover {{
    background: var(--nk-accent-soft) !important;
    border-color: var(--nk-accent) !important;
    color: var(--nk-accent) !important;
}}

{s} .btn-xs.active,
{s} .btn-xs[style*="background:rgba(79,172,254"],
{s} .btn-xs[style*="background: rgba(79,172,254"] {{
    background: var(--nk-accent-soft) !important;
    border-color: var(--nk-accent) !important;
    color: var(--nk-accent) !important;
}}

{s} .f-input,
{s} .dropdown-toggle {{
    border-color: var(--nk-line) !important;
    background: var(--nk-surface-1) !important;
    color: var(--nk-text-1) !important;
}}

{s} .f-input:focus,
{s} .dropdown-toggle:focus {{
    border-color: var(--nk-accent) !important;
}}

{s} #execDatesChips {{
    border-color: var(--nk-line) !important;
}}

{s} .nav-tabs {{
    border-bottom: 2px solid var(--nk-line) !important;
}}

{s} .nav-tab {{
    color: var(--nk-text-2) !important;
}}

{s} .nav-tab:hover {{
    color: var(--nk-text-1) !important;
}}

{s} .nav-tab.active {{
    color: var(--nk-accent) !important;
    border-bottom-color: var(--nk-accent) !important;
    opacity: 1 !important;
}}

{s} .band-mode-btn.active {{
    background: var(--nk-accent-soft) !important;
    color: var(--nk-accent) !important;
}}

{s} .cluster-pill-toggle:hover {{
    border-color: var(--nk-accent) !important;
    background: var(--nk-accent-soft) !important;
}}

/* inverted islands (dark banner panels inside a light theme): their small
   labels must stay readable, so they get one shared island tone */
{s} :is(.executive-banner, .cei-exec-banner, .hs-exec-banner, .ran-exec-banner,
        .redcov-exec-banner, .rhi-exec-banner, .sow-exec-banner, .ran-info-banner)
    :is(.brand-week, .stat-text, .banner-subtitle, .ran-banner-subtitle, .hs-banner-subtitle) {{
    color: var(--nk-island-label);
}}

/* visible keyboard focus (R-34) */
{s} a:focus-visible,
{s} button:focus-visible,
{s} input:focus-visible,
{s} select:focus-visible,
{s} textarea:focus-visible {{
    outline: 2px solid var(--nk-accent);
    outline-offset: 1px;
}}

/* ── Specific table header protections: Crimson / Maroon executive tables ── */
{s} .hs-table thead th {{
    background: var(--hs-danger-header) !important;
    color: #ffffff !important;
    border: 1px solid var(--hs-danger-dark, #7f1d1d) !important;
}}
""".format(s=s)


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    for skin_id, skin in SKINS.items():
        rules = compile_skin(skin_id, skin)
        header = (
            "/* AUTO-GENERATED by scripts/build_themes.py — do not edit.\n"
            "   Skin: {} ({}) — {}\n"
            "   Re-generate after template CSS changes: python scripts/build_themes.py */\n".format(
                skin["name"], skin["mode"], skin["purpose"])
        )
        css = header + token_block(skin_id, skin) + "\n\n" + "\n\n".join(rules) + "\n" + craft_layer(skin_id)
        path = os.path.join(OUT_DIR, skin_id + ".css")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(css)
        print("{:>10s}: {:>6d} rules, {:>7.1f} KB -> {}".format(
            skin_id, len(rules), len(css) / 1024.0, os.path.relpath(path, ROOT)))


if __name__ == "__main__":
    build()
