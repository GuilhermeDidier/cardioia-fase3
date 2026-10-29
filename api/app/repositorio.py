"""Persistência em SQLite: leituras, último status do dispositivo e log de e-mails.

Uma conexão por operação: as rotas síncronas do FastAPI rodam em threads, e o
sqlite3 não compartilha conexão entre threads com segurança.
"""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente TEXT NOT NULL,
    seq INTEGER NOT NULL,
    recebida_em REAL NOT NULL,      -- epoch (s) em que a API recebeu
    medida_em REAL NOT NULL,        -- epoch (s) em que o ESP32 mediu = recebida_em - idade_ms
    temp REAL,
    umid INTEGER,
    bpm INTEGER NOT NULL,
    origem TEXT NOT NULL,
    alerta_esp32 INTEGER NOT NULL,
    alerta INTEGER NOT NULL,
    motivo TEXT NOT NULL,
    nivel TEXT NOT NULL,
    divergencia INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leituras_paciente ON leituras (paciente, medida_em);
CREATE TABLE IF NOT EXISTS status (
    paciente TEXT PRIMARY KEY,
    recebido_em REAL NOT NULL,
    dados TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paciente TEXT NOT NULL,
    criado_em REAL NOT NULL,
    tipo TEXT NOT NULL,
    assunto TEXT NOT NULL,
    para TEXT NOT NULL,
    status TEXT NOT NULL,           -- enviado | falhou
    erro TEXT
);
"""


class Repositorio:
    def __init__(self, caminho: str):
        self.caminho = caminho
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)

    def _conectar(self):
        con = sqlite3.connect(self.caminho)
        con.row_factory = sqlite3.Row
        return con

    def criar_tabelas(self):
        with closing(self._conectar()) as con, con:
            con.executescript(ESQUEMA)

    def inserir_leitura(self, **campos) -> int | None:
        colunas = ", ".join(campos)
        marcadores = ", ".join("?" for _ in campos)
        with closing(self._conectar()) as con, con:
            cur = con.execute(f"INSERT INTO leituras ({colunas}) VALUES ({marcadores})", tuple(campos.values()))
            return cur.lastrowid

    def listar_leituras(self, paciente: str, limite: int, so_alertas: bool = False) -> list[dict]:
        filtro = "AND alerta = 1" if so_alertas else ""
        with closing(self._conectar()) as con:
            linhas = con.execute(
                f"SELECT * FROM (SELECT * FROM leituras WHERE paciente = ? {filtro} "
                f"ORDER BY medida_em DESC LIMIT ?) ORDER BY medida_em",
                (paciente, limite),
            ).fetchall()
        return [dict(l) for l in linhas]

    def ultima_leitura(self, paciente: str) -> dict | None:
        with closing(self._conectar()) as con:
            linha = con.execute(
                "SELECT * FROM leituras WHERE paciente = ? ORDER BY medida_em DESC LIMIT 1", (paciente,)
            ).fetchone()
        return dict(linha) if linha else None

    def ultima_chegada(self, paciente: str) -> float | None:
        with closing(self._conectar()) as con:
            linha = con.execute("SELECT MAX(recebida_em) FROM leituras WHERE paciente = ?", (paciente,)).fetchone()
        return linha[0]

    def contar_alertas_desde(self, paciente: str, desde: float) -> dict[str, int]:
        with closing(self._conectar()) as con:
            linhas = con.execute(
                "SELECT motivo FROM leituras WHERE paciente = ? AND alerta = 1 AND medida_em >= ?", (paciente, desde)
            ).fetchall()
        contagem: dict[str, int] = {}
        for (motivo,) in linhas:
            for m in motivo.split("+"):
                contagem[m] = contagem.get(m, 0) + 1
        return contagem

    def salvar_status(self, paciente: str, recebido_em: float, dados: dict):
        with closing(self._conectar()) as con, con:
            con.execute(
                "INSERT INTO status (paciente, recebido_em, dados) VALUES (?, ?, ?) "
                "ON CONFLICT(paciente) DO UPDATE SET recebido_em = excluded.recebido_em, dados = excluded.dados",
                (paciente, recebido_em, json.dumps(dados)),
            )

    def ultimo_status(self, paciente: str) -> dict | None:
        with closing(self._conectar()) as con:
            linha = con.execute("SELECT recebido_em, dados FROM status WHERE paciente = ?", (paciente,)).fetchone()
        return {"recebido_em": linha[0], **json.loads(linha[1])} if linha else None

    def registrar_email(self, **campos) -> int | None:
        colunas = ", ".join(campos)
        marcadores = ", ".join("?" for _ in campos)
        with closing(self._conectar()) as con, con:
            cur = con.execute(f"INSERT INTO emails ({colunas}) VALUES ({marcadores})", tuple(campos.values()))
            return cur.lastrowid

    def contar_emails(self, paciente: str) -> dict[str, int]:
        with closing(self._conectar()) as con:
            linhas = con.execute("SELECT status, COUNT(*) FROM emails WHERE paciente = ? GROUP BY status",
                                 (paciente,)).fetchall()
        return {status: n for status, n in linhas}

    def pacientes(self) -> list[str]:
        with closing(self._conectar()) as con:
            return [p for (p,) in con.execute("SELECT DISTINCT paciente FROM leituras").fetchall()]

    def listar_emails(self, limite: int = 100) -> list[dict]:
        with closing(self._conectar()) as con:
            linhas = con.execute("SELECT * FROM emails ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(l) for l in linhas]
