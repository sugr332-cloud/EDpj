"""Runtime configuration for EDpj.

Phase 0-A only needs a database connection and the Elite Dangerous journal
directory. Values are read from environment variables (or a `.env` file) so
the same code runs against local SQLite (fast tests) or PostgreSQL (per
docker-compose.yml) without code changes.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_journal_dir() -> str:
    # Elite Dangerous writes journals here on Windows; on Linux (Proton/Steam
    # Deck) it typically lives under compatdata. There is no reliable OS
    # default, so this is just a reasonable placeholder — always override via
    # EDPJ_JOURNAL_DIR or --dir.
    return str(Path.home() / "Saved Games" / "Frontier Developments" / "Elite Dangerous")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EDPJ_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/edpj.db"
    journal_dir: str = _default_journal_dir()


settings = Settings()
