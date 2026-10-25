from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values


REQUIRED = (
    "DEPLOY_DOMAIN", "ACME_EMAIL", "POSTGRES_DB", "POSTGRES_USER",
    "POSTGRES_PASSWORD", "PSEUDONYM_SALT",
)
PLACEHOLDERS = ("replace", "example.com", "change-me", "signaldesk-dev-only")


def validate(path: Path) -> list[str]:
    values = dotenv_values(path)
    errors = []
    for key in REQUIRED:
        value = (values.get(key) or "").strip()
        if not value:
            errors.append(f"{key}: valore mancante")
        elif any(marker in value.lower() for marker in PLACEHOLDERS):
            errors.append(f"{key}: sostituire il valore di esempio")
    if (values.get("COOKIE_SECURE") or "").lower() != "true":
        errors.append("COOKIE_SECURE deve essere true")
    origin = (values.get("PUBLIC_ORIGIN") or "").rstrip("/")
    domain = (values.get("DEPLOY_DOMAIN") or "").strip()
    if domain and origin != f"https://{domain}":
        errors.append("PUBLIC_ORIGIN deve coincidere con https://DEPLOY_DOMAIN")
    if domain and domain not in (values.get("ALLOWED_HOSTS") or "").split(","):
        errors.append("DEPLOY_DOMAIN deve essere presente in ALLOWED_HOSTS")
    if len(values.get("POSTGRES_PASSWORD") or "") < 20:
        errors.append("POSTGRES_PASSWORD deve contenere almeno 20 caratteri")
    if len(values.get("PSEUDONYM_SALT") or "") < 32:
        errors.append("PSEUDONYM_SALT deve contenere almeno 32 caratteri")
    if (values.get("PUBLIC_PREVIEW_ENABLED") or "").lower() == "true" and not (values.get("YOUTUBE_API_KEY") or "").strip():
        errors.append("YOUTUBE_API_KEY è obbligatoria quando PUBLIC_PREVIEW_ENABLED=true")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida la configurazione production di SignalDesk")
    parser.add_argument("path", nargs="?", default=".env.production")
    path = Path(parser.parse_args().path)
    if not path.exists():
        raise SystemExit(f"File non trovato: {path}")
    errors = validate(path)
    if errors:
        raise SystemExit("Configurazione non valida:\n- " + "\n- ".join(errors))
    print("Configurazione production valida")


if __name__ == "__main__":
    main()
