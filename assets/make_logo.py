"""Build the Limitful logo files. The wordmark is drawn as outlines so it looks the same everywhere.

Needs the Outfit variable font (SIL Open Font License), from
https://github.com/google/fonts/tree/main/ofl/outfit, and fontTools:

    uv run --with fonttools python assets/make_logo.py "Outfit[wght].ttf" assets
"""
import sys, pathlib
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

font_path, out = sys.argv[1], pathlib.Path(sys.argv[2])
GREEN, CREAM, AMBER, DEEP_AMBER, INK = "#0b6b58", "#eef2ef", "#f4c63a", "#e2a900", "#13201a"

font = instantiateVariableFont(TTFont(font_path), {"wght": 600})
glyphs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
cap = font["OS/2"].sCapHeight

def word(text, x, baseline, cap_height):
    """SVG path data for text set with its cap height at `cap_height`, and its width."""
    scale = cap_height / cap
    parts, pen_x = [], 0
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x + pen_x * scale, baseline)))
        parts.append(pen.getCommands())
        pen_x += glyphs[name].width
    return " ".join(parts), pen_x * scale

def asterisk(cx, cy, length, fill, indent="  "):
    """A six-armed footnote asterisk: flared arms with round ends."""
    k = length / 40
    neck, tip = 2.6 * k, 6.4 * k
    petal = (f"M {-neck:.2f} 0 L {-tip:.2f} {-(length - tip):.2f} "
             f"A {tip:.2f} {tip:.2f} 0 0 1 {tip:.2f} {-(length - tip):.2f} L {neck:.2f} 0 Z")
    arms = "\n".join(f'{indent}  <path d="{petal}" transform="rotate({i * 60})"/>' for i in range(6))
    return (f'{indent}<g transform="translate({cx:.1f} {cy:.1f})" fill="{fill}">\n{arms}\n'
            f'{indent}  <circle r="{4.2 * k:.2f}"/>\n{indent}</g>')

def lockup(x, baseline, cap_height, ink, star):
    """The mark, then the name: returns (svg, total width)."""
    radius = cap_height * 0.74
    centre_y = baseline - cap_height / 2
    path, width = word("Limitful", x + radius * 2 + cap_height * 0.34, baseline, cap_height)
    body = asterisk(x + radius, centre_y, radius, star) + f'\n  <path d="{path}" fill="{ink}"/>'
    return body, radius * 2 + cap_height * 0.34 + width

TITLE = '  <title id="t">Limitful</title>\n'
# --- the lockup on its own, for light and dark pages
for name, ink, star in (("wordmark.svg", INK, DEEP_AMBER), ("wordmark-dark.svg", CREAM, AMBER)):
    body, width = lockup(8, 118, 96, ink, star)
    (out / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width + 16:.0f} 164" role="img" aria-labelledby="t">\n'
        f'{TITLE}{body}\n</svg>\n')

# --- the banner: the lockup on a block of colour, with the fine print where fine print goes
W, H, CAP = 1280, 640, 132
body, width = lockup(0, 0, CAP, CREAM, AMBER)
x0, base = (W - width) / 2, H / 2 + CAP / 2
body, _ = lockup(x0, base, CAP, CREAM, AMBER)
fine, fine_w = word("limits apply", 0, 0, 15)
fine, _ = word("limits apply", W - 56 - fine_w, H - 44, 15)
(out / "banner.svg").write_text(
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t">\n'
    f'  <title id="t">Limitful. Fine print: limits apply.</title>\n'
    f'  <rect width="{W}" height="{H}" rx="40" fill="{GREEN}"/>\n{body}\n'
    f'{asterisk(W - 56 - fine_w - 16, H - 44 - 8, 8, AMBER)}\n'
    f'  <path d="{fine}" fill="{CREAM}" opacity="0.75"/>\n</svg>\n')

# --- the icon: the mark alone on a tile
(out / "logo.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-labelledby="t">\n'
    f'{TITLE}  <rect x="4" y="4" width="120" height="120" rx="28" fill="{GREEN}"/>\n'
    f'{asterisk(64, 64, 42, AMBER)}\n</svg>\n')
print("written:", sorted(p.name for p in out.glob("*.svg")))
