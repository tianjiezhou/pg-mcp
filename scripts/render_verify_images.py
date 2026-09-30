"""Render the live verification log into terminal-style PNG evidence images.

Reads verify_run.log (produced by verify_mcp_features.py against the real
MCP server) and renders three dark-terminal PNGs, one per scenario.
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"D:\zhoutianjie\Desktop\pg-mcp")
LOG = ROOT / "verify_screenshots" / "verify_run.log"
OUT = ROOT / "verify_screenshots"

BG = (12, 12, 14)
FG = (210, 210, 210)
GREEN = (135, 220, 135)
RED = (240, 130, 130)
YELLOW = (230, 200, 110)
CYAN = (120, 200, 220)
GREY = (130, 130, 130)

TITLE = "  Windows PowerShell — pg-mcp-verify  —  D:\\zhoutianjie\\Desktop\\pg-mcp"
FONT_SIZE = 22
CHARS_PER_LINE = 118  # wrap threshold for long lines


def load_font() -> ImageFont.FreeTypeFont:
    for name in ["msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc"]:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def find_section(lines: list[str], header: str) -> list[str]:
    """Return lines of one scenario: from the dashed line above the header
    through the dashed line below its result block."""
    idx = next(i for i, ln in enumerate(lines) if header in ln)
    start = idx - 1 if idx > 0 and set(lines[idx - 1].strip()) == {"-"} else idx
    end = len(lines)
    for j in range(idx + 1, len(lines)):
        s = lines[j].strip()
        if s.startswith("[验证") or s.startswith("[完成") or s.startswith("[启动"):
            end = j - 1  # drop the dashed separator above the next header
            break
    return lines[start:end]


def wrap(line: str) -> list[str]:
    if len(line) <= CHARS_PER_LINE:
        return [line]
    return [line[i : i + CHARS_PER_LINE] for i in range(0, len(line), CHARS_PER_LINE)]


def colorize(line: str) -> tuple[int, int, int]:
    s = line.strip()
    if set(s) == {"="} and s:
        return CYAN
    if set(s) == {"-"} and s:
        return GREY
    if s.startswith("[") and ("验证" in s or "启动" in s):
        return CYAN
    if "security_violation" in s and "success" in s:
        return YELLOW
    if 'success": true' in s:
        return GREEN
    if 'success": false' in s:
        return RED if "security_violation" not in s and "database_error" not in s else YELLOW
    if "预期" in s or "配置：" in s:
        return YELLOW
    return FG


def render(header: str, out_name: str) -> None:
    lines = LOG.read_text(encoding="utf-8").splitlines()
    section = [wrapped for raw in find_section(lines, header) for wrapped in wrap(raw)]

    font = load_font()
    lh = 32
    pad_x = 28
    pad_y = 22
    title_h = 44
    width = 1660
    height = title_h + pad_y * 2 + lh * len(section)

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, width, title_h], fill=(38, 38, 44))
    d.text((16, 10), TITLE, fill=(190, 190, 190), font=font)

    y = title_h + pad_y
    for line in section:
        d.text((pad_x, y), line.replace("\t", "    "), fill=colorize(line), font=font)
        y += lh

    img.save(OUT / out_name)
    print(f"rendered {out_name}  ({width}x{height}, {len(section)} lines)")


if __name__ == "__main__":
    render("[验证 1]", "验证1_多数据库路由_20260930.png")
    render("[验证 2]", "验证2_安全控制_黑名单表拦截_20260930.png")
    render("[验证 3]", "验证3_可观测性_metrics全链路指标_20260930.png")
