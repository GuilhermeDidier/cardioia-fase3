"""Cliente REST da API do CardioIA (envio e consulta).

Uso como linha de comando (chave da equipe lida de api/.env):
  python -m api.cliente.cliente_rest consultar resumo   --paciente P001
  python -m api.cliente.cliente_rest consultar leituras --paciente P001 --limite 10
  python -m api.cliente.cliente_rest consultar alertas  --paciente P001
  python -m api.cliente.cliente_rest consultar emails
"""

import argparse
import json
import os

import httpx
from dotenv import load_dotenv

from api.app.config import RAIZ_REPO


class ClienteCardioIA:
    """Fala com a API. Recebe um httpx.Client pronto nos testes (TestClient)."""

    def __init__(self, base_url: str = "http://localhost:8000", chave: str = "", http: httpx.Client | None = None):
        self.http = http or httpx.Client(base_url=base_url, timeout=10)
        self.cabecalho = {"X-API-Key": chave}

    def _get(self, caminho: str, **params):
        resposta = self.http.get(caminho, params=params, headers=self.cabecalho)
        resposta.raise_for_status()
        return resposta.json()

    def _post(self, caminho: str, corpo: dict):
        resposta = self.http.post(caminho, json=corpo, headers=self.cabecalho)
        resposta.raise_for_status()
        return resposta.json()

    # envio (papel dispositivo)
    def enviar_leitura(self, paciente: str, leitura: dict) -> dict:
        return self._post(f"/pacientes/{paciente}/leituras", leitura)

    def enviar_status(self, paciente: str, status: dict) -> dict:
        return self._post(f"/pacientes/{paciente}/status", status)

    # consulta (papel equipe)
    def leituras(self, paciente: str, limite: int = 50) -> list:
        return self._get(f"/pacientes/{paciente}/leituras", limite=limite)

    def alertas(self, paciente: str, limite: int = 50) -> list:
        return self._get(f"/pacientes/{paciente}/alertas", limite=limite)

    def resumo(self, paciente: str) -> dict:
        return self._get(f"/pacientes/{paciente}/resumo")

    def emails(self, limite: int = 100) -> list:
        return self._get("/emails", limite=limite)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acao", choices=["consultar"])
    parser.add_argument("o_que", choices=["resumo", "leituras", "alertas", "emails"])
    parser.add_argument("--paciente", default="P001")
    parser.add_argument("--limite", type=int, default=20)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    load_dotenv(RAIZ_REPO / "api" / ".env")
    cliente = ClienteCardioIA(args.url, os.environ.get("API_CHAVE_EQUIPE", ""))
    if args.o_que == "resumo":
        dados = cliente.resumo(args.paciente)
    elif args.o_que == "emails":
        dados = cliente.emails(args.limite)
    else:
        dados = getattr(cliente, args.o_que)(args.paciente, args.limite)
    print(json.dumps(dados, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
