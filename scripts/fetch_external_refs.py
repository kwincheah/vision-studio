"""Download external VisionMaster reference documents for offline analysis.

Some hosts reject the harness fetcher's Accept header (IIS 406) or redirect
cross-origin, so the documents are pulled with a plain HTTP client instead and
stored under ``docs/references/external`` for figure extraction.
"""
import os
import sys
import ssl
import urllib.request

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "docs", "references", "external")

SOURCES = [
    # VisionMaster V3.0.2 user manual (Chinese) - contains annotated UI region
    # breakdowns and per-tool parameter figures.
    ("visionmaster_v3.0.2_user_manual_cn.pdf",
     "https://www.ceiaec.org/ueditor/php/upload/file/20190710/"
     "VisionMaster%e7%ae%97%e6%b3%95%e5%b9%b3%e5%8f%b0%e7%94%a8%e6%88%b7%e6%89%8b%e5%86%8cV3.0.2.pdf"),
    # VisionMaster 4.3.0 maintenance-version user manual (Chinese).
    ("visionmaster_v4.3.0_user_manual_cn.pdf",
     "https://pinfo.hikrobotics.com/hkws/unzip/20250729144858_90792_doc/"
     "%E6%B5%B7%E5%BA%B7%E6%9C%BA%E5%99%A8%E4%BA%BAVision%20Master"
     "%E7%AE%97%E6%B3%95%E5%BC%80%E5%8F%91%E5%B9%B3%E5%8F%B0_%E7%94%A8%E6%88%B7"
     "%E6%89%8B%E5%86%8C_4.3.0%E7%BB%B4%E6%8A%A4%E7%89%88%E6%9C%AC_20250729.pdf"),
    # VisionMaster 3D algorithm platform manual (UI structure reference).
    ("visionmaster_3d_v2.2.0_user_manual_cn.pdf",
     "https://pinfo.hikrobotics.com/hkws/unzip/20240919112534_17943_doc/"
     "%E6%B5%B7%E5%BA%B7%E6%9C%BA%E5%99%A8%E4%BA%BAVM3D%E7%AE%97%E6%B3%95"
     "%E5%BC%80%E5%8F%91%E5%B9%B3%E5%8F%B0_%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C"
     "_V2.2.0_20240914.pdf"),
    # Technical paper describing the VisionMaster operating interface regions.
    ("visionmaster_interface_paper_cn.pdf",
     "https://www.fvti.cn/_upload/article/files/e3/3c/66f2d31d46c3a4140b0830286bb1/"
     "e7edaade-376a-4d0c-bc77-ec3cd5cac576.pdf"),
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
}


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    failures = []
    for name, url in SOURCES:
        target = os.path.join(OUT, name)
        if os.path.exists(target) and os.path.getsize(target) > 50_000:
            print(f"cached  {name} ({os.path.getsize(target)} bytes)")
            continue
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=90, context=ctx) as resp:
                data = resp.read()
            if len(data) < 5_000:
                raise ValueError(f"suspiciously small response: {len(data)} bytes")
            with open(target, "wb") as fh:
                fh.write(data)
            print(f"ok      {name} ({len(data)} bytes)")
        except Exception as exc:
            print(f"FAILED  {name}: {type(exc).__name__}: {exc}")
            failures.append(name)

    print(f"\n{len(SOURCES) - len(failures)}/{len(SOURCES)} documents available in {OUT}")
    for name in failures:
        print(f"  unavailable: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
