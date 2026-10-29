"""Autenticação por chave de API com papel, no header X-API-Key.

- dispositivo: o ESP32 (ou a ponte MQTT) só envia leituras e status;
- equipe: a equipe de saúde só consulta.

Sem chave ou com chave inválida → 401. Chave válida do papel errado → 403.
"""

import secrets

from fastapi import Header, HTTPException, Request


def exigir_papel(papel: str):
    def verificar(request: Request, x_api_key: str | None = Header(default=None)) -> str:
        config = request.app.state.config
        chaves = {"dispositivo": config.chave_dispositivo, "equipe": config.chave_equipe}
        # compare_digest: a comparação leva o mesmo tempo acerte ou erre
        dono = next((p for p, c in chaves.items() if x_api_key and secrets.compare_digest(x_api_key, c)), None)
        if dono is None:
            raise HTTPException(401, "Chave de API ausente ou inválida", headers={"WWW-Authenticate": "ApiKey"})
        if dono != papel:
            raise HTTPException(403, f"Esta rota exige o papel '{papel}'")
        return dono
    return verificar
