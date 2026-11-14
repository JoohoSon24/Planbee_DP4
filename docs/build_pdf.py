"""ARCHITECTURE.md 를 PDF 로 만든다.   python docs/build_pdf.py   (markdown 패키지와 Chrome 필요)"""
import subprocess
import tempfile
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
CSS = '''
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans CJK KR", "Apple SD Gothic Neo", "Malgun Gothic", sans-serif; font-size: 9.6pt; line-height: 1.6; color: #22201a; margin: 0; }
h1 { font-size: 21pt; margin: 0 0 4pt; }
h1 + p { color: #7b776b; font-size: 8.8pt; margin: 0 0 10pt; padding-bottom: 9pt; border-bottom: 2px solid #22201a; }
h2 { font-size: 13.5pt; margin: 20pt 0 6pt; break-after: avoid; border-left: 4px solid #d39410; padding-left: 8pt; }
h3 { font-size: 10.6pt; margin: 13pt 0 4pt; break-after: avoid; color: #7a5407; }
p { margin: 0 0 6pt; }
ul { margin: 0 0 6pt; padding-left: 16pt; } li { margin-bottom: 3pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 9pt; font-size: 8.7pt; }
tr { break-inside: avoid; }
th { background: #f2f0e9; text-align: left; color: #4b483f; }
th, td { border: 0.6pt solid #cdc8b8; padding: 4pt 6pt; vertical-align: top; }
code { font-family: "Noto Sans Mono CJK KR", "DejaVu Sans Mono", monospace; font-size: 8.2pt; background: #f2f0e9; padding: 0.5pt 3pt; border-radius: 2pt; }
pre { background: #f7f5ef; border: 0.6pt solid #cdc8b8; border-radius: 4pt; padding: 8pt 10pt; margin: 4pt 0 9pt; break-inside: avoid; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: 8pt; }
'''
body = markdown.markdown((HERE / "ARCHITECTURE.md").read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
html = f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>Plan Bee 백엔드 구조</title><style>{CSS}</style></head><body>{body}</body></html>'
with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
    f.write(html)
out = HERE / "PlanBee_Backend_Architecture.pdf"
subprocess.run(["google-chrome", "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={out}", f.name], check=True, capture_output=True)
print(out)
