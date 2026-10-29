"""Configuração da API, lida do ambiente (arquivo api/.env).

As chaves de acesso não têm valor padrão: sem elas a API não sobe, para que
nenhuma chave de exemplo vá parar em produção.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ_REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    chave_dispositivo: str
    chave_equipe: str
    banco: str
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    email_de: str = "monitor@cardioia.local"
    email_para: str = "equipe@cardioia.local"
    silencio_s: int = 60
    verificar_silencio_em_loop: bool = True

    @classmethod
    def do_ambiente(cls):
        load_dotenv(RAIZ_REPO / "api" / ".env")
        faltando = [n for n in ("API_CHAVE_DISPOSITIVO", "API_CHAVE_EQUIPE") if not os.getenv(n)]
        if faltando:
            raise RuntimeError(f"Defina {', '.join(faltando)} em api/.env (modelo em api/.env.exemplo)")
        if os.environ["API_CHAVE_DISPOSITIVO"] == os.environ["API_CHAVE_EQUIPE"]:
            raise RuntimeError("API_CHAVE_DISPOSITIVO e API_CHAVE_EQUIPE precisam ser diferentes")
        banco = Path(os.getenv("BANCO_SQLITE", "api/dados/cardioia.db"))
        return cls(
            chave_dispositivo=os.environ["API_CHAVE_DISPOSITIVO"],
            chave_equipe=os.environ["API_CHAVE_EQUIPE"],
            banco=str(banco if banco.is_absolute() else RAIZ_REPO / banco),
            smtp_host=os.getenv("SMTP_HOST", "localhost"),
            smtp_port=int(os.getenv("SMTP_PORT", "1025")),
            email_de=os.getenv("EMAIL_DE", "monitor@cardioia.local"),
            email_para=os.getenv("EMAIL_PARA", "equipe@cardioia.local"),
            silencio_s=int(os.getenv("SILENCIO_S", "60")),
        )
