thonimport csv
import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
from xml.etree.ElementTree import Element, SubElement, ElementTree

logger = logging.getLogger(__name__)

def _flatten_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Flatten page-level results into row-level records suitable for CSV/Excel.
    Each row corresponds to an individual result (organic, paid, PAA, related).
    """
    rows: List[Dict[str, Any]] = []

    for page_obj in results:
        meta = page_obj.get("searchQuery", {})
        term = meta.get("term")
        page = meta.get("page")
        mkt = meta.get("marketCode")
        lang = meta.get("languageCode")

        # Organic
        for item in page_obj.get("organicResults", []):
            rows.append(
                {
                    "searchTerm": term,
                    "page": page,
                    "marketCode": mkt,
                    "languageCode": lang,
                    "resultType": "organic",
                    "position": item.get("position"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "displayedUrl": item.get("displayedUrl"),
                    "description": item.get("description"),
                    "iconUrl": item.get("iconUrl"),
                    "emphasizedKeywords": ", ".join(
                        item.get("emphasizedKeywords", []) or []
                    ),
                }
            )

        # Paid ads
        for item in page_obj.get("paidResults", []):
            rows.append(
                {
                    "searchTerm": term,
                    "page": page,
                    "marketCode": mkt,
                    "languageCode": lang,
                    "resultType": "ad",
                    "position": item.get("position"),
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "displayedUrl": item.get("displayedUrl"),
                    "description": item.get("description"),
                    "iconUrl": None,
                    "emphasizedKeywords": None,
                }
            )

        # People also ask
        for idx, item in enumerate(page_obj.get("peopleAlsoAsk", []), start=1):
            rows.append(
                {
                    "searchTerm": term,
                    "page": page,
                    "marketCode": mkt,
                    "languageCode": lang,
                    "resultType": "people_also_ask",
                    "position": idx,
                    "title": item.get("question"),
                    "url": item.get("url"),
                    "displayedUrl": None,
                    "description": item.get("answer"),
                    "iconUrl": None,
                    "emphasizedKeywords": None,
                }
            )

        # Related queries
        for idx, item in enumerate(page_obj.get("relatedQueries", []), start=1):
            rows.append(
                {
                    "searchTerm": term,
                    "page": page,
                    "marketCode": mkt,
                    "languageCode": lang,
                    "resultType": "related_query",
                    "position": idx,
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "displayedUrl": None,
                    "description": None,
                    "iconUrl": None,
                    "emphasizedKeywords": None,
                }
            )

    return rows

def export_json(results: List[Dict[str, Any]], output_path: Path) -> None:
    logger.info("Writing JSON output to %s", output_path)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

def export_csv(results: List[Dict[str, Any]], output_path: Path) -> None:
    logger.info("Writing CSV output to %s", output_path)
    rows = _flatten_results(results)
    if not rows:
        logger.warning("No rows to export to CSV.")
        return

    fieldnames = list(rows[0].keys())

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

def export_excel(results: List[Dict[str, Any]], output_path: Path) -> None:
    logger.info("Writing Excel output to %s", output_path)
    rows = _flatten_results(results)
    if not rows:
        logger.warning("No rows to export to Excel.")
        return
    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False)

def export_xml(results: List[Dict[str, Any]], output_path: Path) -> None:
    logger.info("Writing XML output to %s", output_path)
    root = Element("searchResults")

    for page_obj in results:
        page_el = SubElement(root, "page")
        meta = page_obj.get("searchQuery", {})

        for key in ["term", "resultsPerPage", "page", "url", "marketCode", "languageCode"]:
            value = meta.get(key)
            if value is not None:
                child = SubElement(page_el, key)
                child.text = str(value)

        def add_items(tag_name: str, items: Iterable[Dict[str, Any]]) -> None:
            container = SubElement(page_el, tag_name)
            for item in items:
                item_el = SubElement(container, "item")
                for k, v in item.items():
                    el = SubElement(item_el, k)
                    el.text = "" if v is None else str(v)

        add_items("organicResults", page_obj.get("organicResults", []))
        add_items("paidResults", page_obj.get("paidResults", []))
        add_items("peopleAlsoAsk", page_obj.get("peopleAlsoAsk", []))
        add_items("relatedQueries", page_obj.get("relatedQueries", []))

    tree = ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)

def export_all(
    results: List[Dict[str, Any]],
    output_dir: Path,
    formats: List[str],
    base_filename: str = "results",
) -> None:
    """
    Export results in all requested formats. Unknown formats are ignored with a warning.
    """
    format_set = {fmt.lower() for fmt in formats}

    if "json" in format_set:
        export_json(results, output_dir / f"{base_filename}.json")

    if "csv" in format_set:
        export_csv(results, output_dir / f"{base_filename}.csv")

    if "excel" in format_set or "xlsx" in format_set:
        export_excel(results, output_dir / f"{base_filename}.xlsx")

    if "xml" in format_set:
        export_xml(results, output_dir / f"{base_filename}.xml")

    unknown = format_set - {"json", "csv", "excel", "xlsx", "xml"}
    for fmt in unknown:
        logger.warning("Unknown output format requested and ignored: %s", fmt)