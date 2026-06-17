from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class ManualInterventionRequired(RuntimeError):
    """Raised when CAPTCHA, MFA, or a manual-only step blocks automation."""


class BrowserUnavailable(RuntimeError):
    """Raised when Playwright is not installed in the VM."""


class BrowserSession:
    def __init__(self, profile_dir: Path, downloads_dir: Path, headful: bool = True):
        self.profile_dir = profile_dir
        self.downloads_dir = downloads_dir
        self.headful = headful
        self._playwright: Optional[Any] = None
        self.context: Optional[Any] = None

    def __enter__(self) -> "BrowserSession":
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise BrowserUnavailable("Playwright is not installed. Install requirements-vm.txt and run `playwright install chromium`.") from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=not self.headful,
            accept_downloads=True,
            downloads_path=str(self.downloads_dir),
        )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.context:
            self.context.close()
        if self._playwright:
            self._playwright.stop()

    @property
    def page(self) -> Any:
        if not self.context:
            raise BrowserUnavailable("Browser context is not started.")
        return self.context.pages[0] if self.context.pages else self.context.new_page()


def detect_manual_challenge(page: Any) -> Optional[str]:
    indicators = ("captcha", "mfa", "multi-factor", "verification code", "verify you are human")
    try:
        text = page.locator("body").inner_text(timeout=1500).casefold()
    except Exception:
        return None
    for indicator in indicators:
        if indicator in text:
            return indicator
    return None


def pause_for_manual_if_needed(page: Any, source: str) -> None:
    challenge = detect_manual_challenge(page)
    if challenge:
        raise ManualInterventionRequired(f"{source} requires manual intervention ({challenge}). Do not bypass it.")
