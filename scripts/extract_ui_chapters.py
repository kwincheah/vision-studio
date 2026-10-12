"""Extract the software-operation chapters of the external VisionMaster manual.

Locates the chapter that documents the operating interface, the flow editor and
the module parameter dialog, then dumps those pages' text plus their figures so
the interface structure can be specified from vendor documentation.
"""
import os
import re
import sys
import json

import pypdfium2 as pdfium

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXT = os.path.join(ROOT, "docs", "references", "external")
OUT_TXT = os.path.join(EXT, "ui_chapters_cn.txt")

DOC = os.path.join(EXT, "visionmaster_v4.3.0_user_manual_cn.pdf")

# Terms that identify pages describing the operating interface itself.
UI_TERMS = [
    "操作界面", "软件界面", "主界面", "功能区", "工具箱", "流程图",
    "参数配置", "输入参数", "输出参数", "运行参数", "显示设置",
    "模块参数", "全局变量", "方案管理", "模块列表", "图像显示",
    "工具条", "工具栏", "状态栏", "流程编辑",
]

SCAN_FIRST, SCAN_LAST = 20, 200


def page_text(pdf, idx, limit=6000):
    try:
        tp = pdf[idx].get_textpage()
        return tp.get_text_range(0, min(limit, tp.count_chars()))
    except Exception:
        return ""


def main() -> int:
    if not os.path.exists(DOC):
        print("external 4.3.0 manual not present")
        return 1

    pdf = pdfium.PdfDocument(DOC)
    print(f"{len(pdf)} pages")

    scored = []
    for i in range(SCAN_FIRST - 1, min(SCAN_LAST, len(pdf))):
        text = page_text(pdf, i)
        score = sum(text.count(term) for term in UI_TERMS)
        if score:
            scored.append((score, i + 1, text))

    scored.sort(reverse=True, key=lambda t: t[0])
    print(f"{len(scored)} UI-relevant pages found; top 25:")
    for score, page_no, text in scored[:25]:
        head = " ".join(text.split())[:100]
        print(f"  p{page_no:4d} score={score:3d}  {head}")

    # Dump the full text of the most relevant pages for specification work.
    with open(OUT_TXT, "w", encoding="utf-8") as fh:
        for score, page_no, text in sorted(scored[:60], key=lambda t: t[1]):
            fh.write(f"\n{'=' * 78}\n=== PAGE {page_no} (score {score})\n{'=' * 78}\n")
            fh.write(text)
    print(f"\nwrote {OUT_TXT}")

    # Save full-page renders of the highest scoring pages as visual evidence.
    fig_dir = os.path.join(EXT, "ui_pages")
    os.makedirs(fig_dir, exist_ok=True)
    for score, page_no, _ in sorted(scored[:20], key=lambda t: t[1]):
        page = pdf[page_no - 1]
        pil = page.render(scale=1.6).to_pil()
        path = os.path.join(fig_dir, f"vm43ui_p{page_no:03d}.png")
        pil.save(path)
    print(f"rendered {min(20, len(scored))} pages into {fig_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
