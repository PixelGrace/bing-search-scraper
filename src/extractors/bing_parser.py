thonimport logging
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from extractors.softblock_handler import SoftBlockHandler

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENTS = [
    # A small rotation of common desktop user agents.
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
]

@dataclass
class SearchQueryMeta:
    term: str
    resultsPerPage: int
    page: int
    url: str
    marketCode: str
    languageCode: str

class BingSearchScraper:
    """
    A lightweight Bing search scraper focused on extracting structured SERP data.

    It does not try to be bulletproof against every layout change, but it uses
    stable selectors observed on Bing search result pages.
    """

    BASE_URL = "https://www.bing.com/search"

    def __init__(
        self,
        market_code: str = "en-US",
        language_code: str = "en",
        results_per_page: int = 10,
        include_html: bool = False,
        softblock_handler: Optional[SoftBlockHandler] = None,
        request_timeout: int = 10,
        proxy: Optional[str] = None,
    ) -> None:
        self.market_code = market_code
        self.language_code = language_code
        self.results_per_page = results_per_page
        self.include_html = include_html
        self.softblock_handler = softblock_handler or SoftBlockHandler()
        self.request_timeout = request_timeout
        self.proxy = proxy

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept-Language": language_code,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,image/avif,image/webp,*/*;q=0.8"
                ),
            }
        )
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def search(
        self,
        term: str,
        pages: int = 1,
        results_per_page: Optional[int] = None,
        market_code: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Perform a Bing search and return structured data for each requested page.

        Returns a list of page-level SERP objects as described in the README.
        """
        rp = results_per_page or self.results_per_page
        mkt = market_code or self.market_code
        lang = language_code or self.language_code

        results: List[Dict[str, Any]] = []

        for page in range(1, pages + 1):
            url = self._build_search_url(
                term=term,
                page=page,
                results_per_page=rp,
                market_code=mkt,
                language_code=lang,
            )
            search_meta = SearchQueryMeta(
                term=term,
                resultsPerPage=rp,
                page=page,
                url=url,
                marketCode=mkt,
                languageCode=lang,
            )

            html = self._fetch_page(url)
            page_result = self._parse_page(html, search_meta)
            results.append(page_result)

            # Be respectful: short sleep to reduce the risk of being blocked.
            time.sleep(random.uniform(0.8, 1.6))

        return results

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _build_search_url(
        self,
        term: str,
        page: int,
        results_per_page: int,
        market_code: str,
        language_code: str,
    ) -> str:
        first = (page - 1) * results_per_page + 1
        params = {
            "q": term,
            "mkt": market_code,
            "setLang": language_code,
            "count": results_per_page,
            "first": first,
        }
        return f"{self.BASE_URL}?{urlencode(params)}"

    def _fetch_page(self, url: str) -> str:
        headers = {
            "User-Agent": random.choice(DEFAULT_USER_AGENTS),
        }

        logger.debug("Requesting Bing SERP: %s", url)
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.request_timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                logger.warning(
                    "Network error on attempt %d fetching %s: %s",
                    attempt,
                    url,
                    exc,
                )
                if attempt >= self.softblock_handler.max_retries:
                    raise
                time.sleep(self.softblock_handler.compute_backoff(attempt))
                continue

            if self.softblock_handler.is_soft_blocked(resp.text):
                logger.warning("Potential soft-block detected for url: %s", url)
                html = self.softblock_handler.handle_soft_block(
                    session=self.session,
                    url=url,
                    original_html=resp.text,
                )
                return html

            if not resp.ok:
                logger.warning(
                    "Unexpected HTTP status %s for url %s",
                    resp.status_code,
                    url,
                )

            return resp.text

    def _parse_page(
        self, html: str, meta: SearchQueryMeta
    ) -> Dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")

        results_total = self._extract_results_total(soup)
        organic_results = self._extract_organic_results(soup)
        paid_results = self._extract_paid_results(soup)
        people_also_ask = self._extract_people_also_ask(soup)
        related_queries = self._extract_related_queries(soup)

        result: Dict[str, Any] = {
            "searchQuery": {
                "term": meta.term,
                "resultsPerPage": meta.resultsPerPage,
                "page": meta.page,
                "url": meta.url,
                "marketCode": meta.marketCode,
                "languageCode": meta.languageCode,
            },
            "html": html if self.include_html else None,
            "htmlSnapshotUrl": None,
            "resultsTotal": results_total,
            "organicResults": organic_results,
            "paidResults": paid_results,
            "peopleAlsoAsk": people_also_ask,
            "relatedQueries": related_queries,
        }
        return result

    # --------------------------------------------------------------------- #
    # Parsing helpers
    # --------------------------------------------------------------------- #

    def _extract_results_total(self, soup: BeautifulSoup) -> Optional[int]:
        """
        Extract the approximate number of results, e.g. "1,234 results".
        """
        try:
            count_el = soup.select_one("#b_tween .sb_count")
            if not count_el or not count_el.get_text(strip=True):
                return None
            text = count_el.get_text(" ", strip=True)
            # Usually something like "1,234 results" or "About 1,234 results"
            digits = "".join(ch for ch in text if ch.isdigit())
            return int(digits) if digits else None
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to parse results total: %s", exc)
            return None

    def _extract_organic_results(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        # Organic results are typically li.b_algo in the #b_results list
        organic_listings = soup.select("#b_results li.b_algo")
        position = 0

        for li in organic_listings:
            title_el = li.find("h2")
            link = title_el.find("a") if title_el else None
            if not link or not link.get("href"):
                continue

            position += 1
            url = link.get("href")
            title = link.get_text(strip=True)

            desc_el = li.find("p")
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            display_url_el = li.select_one("div.b_attribution cite")
            displayed_url = display_url_el.get_text(strip=True) if display_url_el else url

            icon_el = li.select_one("img.favicon, img.b_primicon")
            icon_url = icon_el.get("src") if icon_el and icon_el.get("src") else None

            emphasized_keywords: List[str] = []
            for strong in li.find_all("strong"):
                kw = strong.get_text(strip=True)
                if kw and kw.lower() not in {k.lower() for k in emphasized_keywords}:
                    emphasized_keywords.append(kw)

            items.append(
                {
                    "iconUrl": icon_url,
                    "displayedUrl": displayed_url,
                    "title": title,
                    "url": url,
                    "description": description,
                    "emphasizedKeywords": emphasized_keywords,
                    "type": "organic",
                    "position": position,
                }
            )

        return items

    def _extract_paid_results(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        # Paid ads often live in containers with class "b_ad" or "b_adresult"
        paid_blocks = soup.select("#b_results li.b_ad, #b_results li.b_adresult")
        position = 0

        for li in paid_blocks:
            title_el = li.find("h2")
            link = title_el.find("a") if title_el else None
            if not link or not link.get("href"):
                continue

            position += 1
            url = link.get("href")
            title = link.get_text(strip=True)

            desc_el = li.find("p")
            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            display_url_el = li.select_one("div.b_adurl cite, div.b_attribution cite")
            displayed_url = display_url_el.get_text(strip=True) if display_url_el else url

            items.append(
                {
                    "title": title,
                    "url": url,
                    "displayedUrl": displayed_url,
                    "description": description,
                    "type": "ad",
                    "position": position,
                }
            )

        return items

    def _extract_people_also_ask(
        self, soup: BeautifulSoup
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        # People Also Ask ("PAA") often lives in b_expando or related containers
        paa_blocks = soup.select("#b_context .b_expando")
        for block in paa_blocks:
            question_el = block.find("div", class_="b_qa")
            question_text = ""
            answer_text = ""
            url = None

            if question_el:
                q_el = question_el.find("div", class_="b_q")
                question_text = q_el.get_text(" ", strip=True) if q_el else ""
                a_el = question_el.find("div", class_="b_a")
                answer_text = a_el.get_text(" ", strip=True) if a_el else ""

                link = question_el.find("a", href=True)
                url = link.get("href") if link else None

            if question_text:
                items.append(
                    {
                        "url": url,
                        "question": question_text,
                        "answer": answer_text or None,
                    }
                )

        return items

    def _extract_related_queries(
        self, soup: BeautifulSoup
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        related_section = soup.select("#b_context .b_rs, #b_context .b_rs ul li")
        if not related_section:
            return items

        # We support both the container (.b_rs) and list items.
        if related_section and "b_rs" in related_section[0].get("class", []):
            li_items = related_section[0].select("li")
        else:
            li_items = related_section

        for li in li_items:
            link = li.find("a", href=True)
            if not link:
                continue
            title = link.get_text(" ", strip=True)
            url = link.get("href")
            if title:
                items.append({"title": title, "url": url})

        return items