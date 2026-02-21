import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent

load_dotenv(PROJECT_DIR / ".env")


@dataclass
class Config:
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")

    MODEL: str = "claude-haiku-4-5"
    PROFILE: str = "software_product"
    USE_SCREENSHOTS: bool = False
    INPUT_FILE: str = str(PROJECT_DIR / "input.csv")
    OUTPUT_FILE: str = str(PROJECT_DIR / "output.csv")

    WORKERS: int = 3
    MAX_RETRIES: int = 3
    RETRY_WAIT: int = 10

    JINA_TIMEOUT: int = 25
    JINA_RETRIES: int = 3
    JINA_MIN_LENGTH: int = 100
    PAGE_TEXT_LIMIT: int = 6000
    PROCESSED_TEXT_LIMIT: int = 1500
    JINA_FALLBACK_PLAYWRIGHT: bool = True

    FALLBACK_MODEL: str = "claude-sonnet-4-6"

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = str(PROJECT_DIR / "icp-qualifier.log")


config = Config()
