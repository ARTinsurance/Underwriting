from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


SECRET_KEYS = {"PASSWORD", "TOKEN", "COOKIE", "SECRET", "SESSION"}


def load_dotenv_file(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def mask_secret(value: Optional[str]) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return value[:2] + "****" + value[-2:]


def mask_config(config: Dict[str, str]) -> Dict[str, str]:
    masked = {}
    for key, value in config.items():
        masked[key] = mask_secret(value) if any(marker in key.upper() for marker in SECRET_KEYS) else value
    return masked


@dataclass
class Settings:
    quotation_system_url: str
    quotation_system_username: str
    quotation_system_password: str
    quotation_history_fallback_csv: str
    quotation_history_fallback_xlsx: str
    hifleet_url: str
    hifleet_username: str
    hifleet_password: str
    equasis_url: str
    equasis_username: str
    equasis_password: str
    ofac_url: str
    uk_sanctions_url: str
    uk_russia_regs_url: str
    eu_russia_reg_833_url: str
    browser_profile_dir: Path = Path("playwright-profile")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv_file()
        return cls(
            quotation_system_url=os.getenv("QUOTATION_SYSTEM_URL", ""),
            quotation_system_username=os.getenv("QUOTATION_SYSTEM_USERNAME", ""),
            quotation_system_password=os.getenv("QUOTATION_SYSTEM_PASSWORD", ""),
            quotation_history_fallback_csv=os.getenv("QUOTATION_HISTORY_FALLBACK_CSV", ""),
            quotation_history_fallback_xlsx=os.getenv("QUOTATION_HISTORY_FALLBACK_XLSX", ""),
            hifleet_url=os.getenv("HIFLEET_URL", "https://www.hifleet.com"),
            hifleet_username=os.getenv("HIFLEET_USERNAME", ""),
            hifleet_password=os.getenv("HIFLEET_PASSWORD", ""),
            equasis_url=os.getenv("EQUASIS_URL", "https://www.equasis.org/EquasisWeb/public/HomePage"),
            equasis_username=os.getenv("EQUASIS_USERNAME", ""),
            equasis_password=os.getenv("EQUASIS_PASSWORD", ""),
            ofac_url=os.getenv("OFAC_URL", "https://sanctionssearch.ofac.treas.gov/"),
            uk_sanctions_url=os.getenv("UK_SANCTIONS_URL", "https://search-uk-sanctions-list.service.gov.uk/"),
            uk_russia_regs_url=os.getenv("UK_RUSSIA_REGS_URL", "https://www.legislation.gov.uk/uksi/2019/855"),
            eu_russia_reg_833_url=os.getenv("EU_RUSSIA_REG_833_URL", "https://data.europa.eu/apps/eusanctionstracker/entities/%20"),
            browser_profile_dir=Path(os.getenv("BROWSER_PROFILE_DIR", "playwright-profile")),
        )

    def validate_for_browser_run(self) -> None:
        missing = []
        for key in ("quotation_system_url", "quotation_system_username", "quotation_system_password"):
            if not getattr(self, key):
                missing.append(key.upper())
        if missing:
            raise ValueError(f"Missing required quotation system environment variables: {', '.join(missing)}")
