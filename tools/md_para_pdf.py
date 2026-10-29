"""Converte os relatórios .md de docs/ em PDF A4 (markdown-it + Chromium/Playwright).

Os diagramas mermaid são renderizados pelo mermaid.js antes de imprimir.
Uso: python tools/md_para_pdf.py docs/relatorio_parte1_edge.md docs/relatorio_parte2_fog_cloud.md
"""

import sys
from pathlib import Path

from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

CSS = """
@page { size: A4; margin: 18mm 18mm 18mm 18mm; }
body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.45; color: #1f2328; }
h1 { font-size: 19pt; margin: 0 0 2pt; color: #b71c1c; }
h2 { font-size: 13pt; margin: 0 0 8pt; color: #444; font-weight: 600; }
h3 { font-size: 12pt; margin: 16pt 0 6pt; border-bottom: 1px solid #ddd; padding-bottom: 2pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.5pt; }
th, td { border: 1px solid #d0d7de; padding: 4pt 6pt; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
code { font-family: Menlo, monospace; font-size: 8.8pt; background: #f6f8fa; padding: 0 2pt; }
pre { background: #f6f8fa; padding: 8pt; font-size: 8.3pt; white-space: pre-wrap; word-break: break-all; }
pre code { padding: 0; }
img { max-width: 100%; border: 1px solid #d0d7de; margin: 4pt 0; }
.mermaid { text-align: center; margin: 8pt 0; }
hr { border: 0; border-top: 1px solid #ddd; }
h3, table, pre, img, .mermaid { break-inside: avoid; }
h3 { break-after: avoid; }
"""


def converter(md_path: Path):
    md = MarkdownIt("commonmark").enable("table")
    padrao = md.renderer.rules.get("fence")

    def fence(tokens, idx, options, env):
        token = tokens[idx]
        if token.info.strip() == "mermaid":
            return f'<div class="mermaid">{token.content}</div>'
        return padrao(tokens, idx, options, env)

    md.renderer.rules["fence"] = fence
    corpo = md.render(md_path.read_text(encoding="utf-8"))
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><style>{CSS}</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script></head>
<body>{corpo}<script>mermaid.initialize({{startOnLoad: false, theme: 'neutral'}});
mermaid.run().then(() => document.body.dataset.pronto = '1');</script></body></html>"""
    html_path = md_path.with_suffix(".tmp.html")   # ao lado do .md: caminhos das imagens funcionam
    html_path.write_text(html, encoding="utf-8")
    pdf_path = md_path.with_suffix(".pdf")
    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch()
            pagina = navegador.new_page()
            pagina.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            pagina.wait_for_selector("body[data-pronto='1']", timeout=15000)
            pagina.pdf(path=str(pdf_path), format="A4", print_background=True,
                       display_header_footer=True, header_template="<span></span>",
                       footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#888">'
                                       'CardioIA — Fase 3 · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
                       margin={"top": "16mm", "bottom": "16mm", "left": "16mm", "right": "16mm"})
            navegador.close()
    finally:
        html_path.unlink(missing_ok=True)
    print(f"{pdf_path}")


if __name__ == "__main__":
    for arquivo in sys.argv[1:]:
        converter(Path(arquivo))
