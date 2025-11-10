thonimport logging
import random
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

class SoftBlockHandler:
    """
    Detects and mitigates "soft blocks" from Bing, such as temporary
    throttling, generic error pages, or CAPTCHA / robot checks.

    This is heuristic-based – it looks for typical phrases and patterns,
    and retries the request with backoff and a rotated User-Agent.
    """

    SOFT_BLOCK_HINTS = [
        "unusual traffic",
        "verify that you are a human",
        "detected unusual activity",
        "please try again later",
        "are you a robot",
        "unusual behavior from your computer",
    ]

    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.5) -> None:
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    # Public API ----------------------------------------------------------- #

    def is_soft_blocked(self, html: str) -> bool:
        lower = html.lower()
        for hint in self.SOFT_BLOCK_HINTS:
            if hint in lower:
                return True
        return False

    def compute_backoff(self, attempt: int) -> float:
        # Simple exponential backoff with jitter.
        base = (self.backoff_factor ** (attempt - 1)) if attempt > 0 else 1.0
        jitter = random.uniform(0, 0.5)
        return base + jitter

    def handle_soft_block(
        self,
        session: requests.Session,
        url: str,
        original_html: Optional[str] = None,
    ) -> str:
        """
        Attempt to recover from a soft-blocked page by retrying the request
        with backoff and minor header variations.

        Returns HTML of the recovered page or raises RuntimeError if not recovered.
        """
        if original_html is not None and not self.is_soft_blocked(original_html):
            return original_html

        attempt = 0
        last_html = original_html or ""

        while attempt < self.max_retries:
            attempt += 1
            delay = self.compute_backoff(attempt)
            logger.warning(
                "Soft block detected. Retrying attempt %d/%d after %.2fs",
                attempt,
                self.max_retries,
                delay,
            )
            time.sleep(delay)

            # Rotate headers slightly to look less like a bot.
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    f"AppleWebKit/537.36 (KHTML, like Gecko) "
                    f"Chrome/{random.randint(110, 125)}.0 Safari/537.36"
                ),
                "Cache-Control": "no-cache",
            }

            try:
                resp = session.get(url, headers=headers, timeout=15)
                last_html = resp.text
            except (requests.Timeout, requests.ConnectionError) as exc:
                logger.warning(
                    "Network error while resolving soft block on attempt %d: %s",
                    attempt,
                    exc,
                )
                continue

            if not self.is_soft_blocked(last_html):
                logger.info("Soft block resolved successfully on attempt %d.", attempt)
                return last_html

        logger.error(
            "Failed to resolve soft block after %d retries for URL: %s",
            self.max_retries,
            url,
        )
        raise RuntimeError("Soft block could not be resolved after retries.")