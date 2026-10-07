from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    sources: tuple[int, int, int]


def load_config(root: Path) -> Config:
    env_path = root / "credentials" / "project.env"
    if not env_path.exists():
        raise FileNotFoundError(f"Missing credentials file: {env_path}")

    load_dotenv(env_path, override=True)

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    source_values = [os.getenv(f"SOURCE_{i}") for i in range(1, 4)]

    if not api_id or not api_hash:
        raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH are required.")
    if any(not value for value in source_values):
        raise ValueError("SOURCE_1, SOURCE_2 and SOURCE_3 are required.")

    return Config(
        api_id=int(api_id),
        api_hash=api_hash,
        sources=tuple(int(value) for value in source_values),
    )
