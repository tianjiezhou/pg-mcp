"""Render the coverage run log into a terminal-style PNG evidence image."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"D:\zhoutianjie\Desktop\pg-mcp")
LOG = ROOT / "verify_screenshots" / "coverage_run.log"
OUT = ROOT / "verify_screenshots" / "验证4_测试覆盖_20260930.png"

BG = (12, 12, 14)
FG = (210, 210, 210)
GREEN = (135, 220, 135)
CYAN = (120, 200, 220)
GREY = (130, 130, 130)

TITLE = "  Windows PowerShell — pg-mcp-verify  —  D:\\zhoutianjie\\Desktop\\pg-mcp"
FONT_SIZE = 22
CHARS_PER_LINE = 112


def load_font() -> ImageFont.FreeTypeFont:
    for name in ["msyh.ttc", "msyh.ttf", "simhei.ttf"]:
        try:
            return ImageFont.truetype(f"C:/Windows/Fonts/{name}", FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(line: str) -> list[str]:
    if len(line) <= CHARS_PER_LINE:
        return [line]
    return [line[i : i + CHARS_PER_LINE] for i in range(0, len(line), CHARS_PER_LINE)]


COMMAND = (
    "$ uv run pytest tests/unit tests/e2e/test_mcp.py::TestMCPServer::test_lifespan_initialization"
    ' "tests/e2e/test_mcp.py::TestMCPServer::test_query_tool_invalid_return_type"'
    ' "tests/e2e/test_mcp.py::TestMCPServer::test_query_tool_empty_question"'
    ' "tests/e2e/test_mcp.py::TestMCPServerErrors::test_query_before_initialization"'
    ' "tests/e2e/test_mcp.py::TestMCPServerErrors::test_malformed_question_handling"'
    " --cov=src --cov-report=term -q"
)


def colorize(line: str) -> tuple[int, int, int]:
    s = line.strip()
    if s.startswith("$"):
        return CYAN
    if s.startswith("=====") or s.startswith("_____") or s.startswith("------"):
        return GREY
    if "passed in" in s or "reached" in s or s.endswith("100%"):
        return GREEN
    return FG


def main() -> None:
    lines = [COMMAND, *LOG.read_text(encoding="utf-8").splitlines()]
    section = [w for raw in lines for w in wrap(raw)]

    font = load_font()
    lh = 30
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
        d.text((pad_x, y), line, fill=colorize(line), font=font)
        y += lh

    img.save(OUT)
    print(f"rendered {OUT.name}  ({width}x{height}, {len(section)} lines)")


if __name__ == "__main__":
    main()
