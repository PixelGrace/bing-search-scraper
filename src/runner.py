thonimport argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure the src directory is on sys.path when running from project root
CURRENT_FILE = Path(__file__).resolve()
SRC_DIR = CURRENT_FILE.parent
PROJECT_ROOT = SRC_DIR.parent

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from extractors.bing_parser import BingSearchScraper  # type: ignore  # noqa: E402
from extractors.softblock_handler import SoftBlockHandler  # type: ignore  # noqa: E402
from outputs.exporters import export_all  # type: ignore  # noqa: E402

def configure_logging(verbosity: int) -> None:
    level = logging.WARNING
    if verbosity == 1:
        level = logging.INFO
    elif verbosity >= 2:
        level = logging.DEBUG

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_json_file(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bing Search Scraper - extract structured SERP data from Bing."
    )
    default_inputs = PROJECT_ROOT / "data" / "inputs.sample.json"
    default_settings = SRC_DIR / "config" / "settings.example.json"
    default_output_dir = PROJECT_ROOT / "data"

    parser.add_argument(
        "--inputs",
        type=str,
        default=str(default_inputs),
        help=f"Path to JSON file with input queries (default: {default_inputs})",
    )
    parser.add_argument(
        "--settings",
        type=str,
        default=str(default_settings),
        help=f"Path to JSON settings file (default: {default_settings})",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(default_output_dir),
        help=f"Directory to store output files (default: {default_output_dir})",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        help="Output formats to generate (overrides settings). "
        "Allowed: json csv excel xml",
    )
    parser.add_argument(
        "--include-html",
        action="store_true",
        help="Include raw HTML of SERP pages in the output.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v, -vv).",
    )
    return parser

def merge_query_with_settings(
    query: Dict[str, Any], settings: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge a single query definition with global defaults from settings."""
    defaults = {
        "resultsPerPage": settings.get("resultsPerPage", 10),
        "pages": settings.get("pages", 1),
        "marketCode": settings.get("marketCode", "en-US"),
        "languageCode": settings.get("languageCode", "en"),
    }
    merged = {**defaults, **query}
    return merged

def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    configure_logging(args.verbose)
    logger = logging.getLogger("runner")

    settings_path = Path(args.settings).resolve()
    inputs_path = Path(args.inputs).resolve()
    output_dir = Path(args.output_dir).resolve()

    logger.info("Loading settings from %s", settings_path)
    settings = load_json_file(settings_path)

    logger.info("Loading input queries from %s", inputs_path)
    inputs = load_json_file(inputs_path)

    queries: List[Dict[str, Any]] = inputs.get("queries", [])
    if not queries:
        logger.error("No queries defined in input file: %s", inputs_path)
        raise SystemExit(1)

    output_settings = settings.get("output", {})
    formats = args.formats or output_settings.get("formats", ["json"])
    formats = [fmt.lower() for fmt in formats]

    request_cfg = settings.get("request", {})
    timeout = request_cfg.get("timeout", 10)
    max_retries = request_cfg.get("maxRetries", 3)
    proxy = request_cfg.get("proxy")

    include_html = args.include_html or settings.get("includeHtml", False)

    softblock_handler = SoftBlockHandler(
        max_retries=max_retries,
        backoff_factor=request_cfg.get("backoffFactor", 1.5),
    )

    scraper = BingSearchScraper(
        market_code=settings.get("marketCode", "en-US"),
        language_code=settings.get("languageCode", "en"),
        results_per_page=settings.get("resultsPerPage", 10),
        include_html=include_html,
        softblock_handler=softblock_handler,
        request_timeout=timeout,
        proxy=proxy,
    )

    all_results: List[Dict[str, Any]] = []

    for q in queries:
        merged = merge_query_with_settings(q, settings)
        term = merged["term"]
        pages = int(merged.get("pages", 1))
        results_per_page = int(merged.get("resultsPerPage", scraper.results_per_page))
        market_code = merged.get("marketCode", scraper.market_code)
        language_code = merged.get("languageCode", scraper.language_code)

        logger.info(
            "Scraping term=%r pages=%d resultsPerPage=%d market=%s lang=%s",
            term,
            pages,
            results_per_page,
            market_code,
            language_code,
        )

        page_results = scraper.search(
            term=term,
            pages=pages,
            results_per_page=results_per_page,
            market_code=market_code,
            language_code=language_code,
        )

        logger.info(
            "Collected %d page-level result objects for term %r",
            len(page_results),
            term,
        )
        all_results.extend(page_results)

    if not all_results:
        logger.warning("No results collected. Nothing to export.")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Exporting results to %s with formats %s", output_dir, formats)

    export_all(
        results=all_results,
        output_dir=output_dir,
        formats=formats,
        base_filename="bing_results",
    )

    logger.info("Scraping and export completed successfully.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger("runner").warning("Interrupted by user.")
        raise SystemExit(1)