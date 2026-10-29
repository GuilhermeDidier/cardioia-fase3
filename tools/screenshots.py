"""Captura prints do dashboard e do editor do Node-RED (Playwright).

Uso (Node-RED rodando em localhost:1880):
  python tools/screenshots.py dashboard docs/img/dashboard_alerta.png
  python tools/screenshots.py dashboard docs/img/dashboard_celular.png --largura 390
  python tools/screenshots.py editor docs/img/nodered_flow.png --largura 1920 --altura 720
  python tools/screenshots.py url docs/img/api_swagger.png --url http://localhost:8000/docs
"""

import argparse

from playwright.sync_api import sync_playwright

URLS = {
    "dashboard": "http://localhost:1880/dashboard/paciente",
    "editor": "http://localhost:1880/",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("alvo", choices=[*URLS, "url"])
    parser.add_argument("saida")
    parser.add_argument("--largura", type=int, default=1440)
    parser.add_argument("--altura", type=int, default=900)
    parser.add_argument("--espera", type=float, default=3, help="segundos para o painel receber dados")
    parser.add_argument("--url", help="endereço qualquer, com o alvo 'url'")
    args = parser.parse_args()

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page(viewport={"width": args.largura, "height": args.altura})
        pagina.goto(args.url if args.alvo == "url" else URLS[args.alvo], wait_until="networkidle")
        pagina.wait_for_timeout(args.espera * 1000)
        pagina.screenshot(path=args.saida, full_page=args.alvo == "dashboard")
        navegador.close()
    print(f"salvo em {args.saida}")


if __name__ == "__main__":
    main()
