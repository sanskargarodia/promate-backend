"""Parse PartSelect HTML into structured ingestion records."""

from __future__ import annotations

import contextlib
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from ingestion.types import (
    CategoryDiscovery,
    RepairStory,
    ScrapedDocument,
    ScrapedModel,
    ScrapedPart,
)

BASE_URL = "https://www.partselect.com"
PS_LINK_RE = re.compile(r"/PS(\d+)[^\"'\s]*", re.I)
MODEL_LINK_RE = re.compile(r"/Models/([^/\"'\s]+)", re.I)
CATEGORY_PARTS_RE = re.compile(r"/([A-Za-z0-9-]+-Parts\.htm)", re.I)
REPAIR_HELP_RE = re.compile(
    r"/Repair/(?:Refrigerator|Dishwasher)(?:/[^\"'\s>]*)?", re.I)
OUT_OF_SCOPE_APPLIANCE_RE = re.compile(
    r"(?:dryer|washer|range|stove|oven|microwave|dehumidifier|air[- ]conditioner)",
    re.I,
)

INSTALL_TIME_MAP = {
    "less than 15 mins": 15,
    "15 - 30 mins": 22,
    "30 - 60 mins": 45,
    "more than 60 mins": 90,
}


def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return " ".join(el.stripped_strings)


def _parse_price_cents(soup: BeautifulSoup) -> int | None:
    price_el = soup.select_one("span.pd__price[itemprop=price]")
    if price_el and price_el.get("content"):
        try:
            return int(round(float(price_el["content"]) * 100))
        except ValueError:
            pass
    price_span = soup.select_one("span.js-partPrice")
    if price_span:
        try:
            return int(round(float(price_span.get_text(strip=True)) * 100))
        except ValueError:
            return None
    return None


def _parse_install_time(text: str) -> int | None:
    lowered = text.lower()
    for label, minutes in INSTALL_TIME_MAP.items():
        if label in lowered:
            return minutes
    return None


def _infer_appliance_type(text: str, url: str) -> str:
    blob = f"{text} {url}".lower()
    if "dishwasher" in blob:
        return "dishwasher"
    if "refrigerator" in blob or "fridge" in blob:
        return "refrigerator"
    return "refrigerator"


def extract_part_urls(html: str) -> list[str]:
    urls: set[str] = set()
    for match in PS_LINK_RE.finditer(html):
        urls.add(urljoin(BASE_URL, f"/PS{match.group(1)}.htm"))
    return sorted(urls)


def extract_model_urls(html: str) -> list[str]:
    urls: set[str] = set()
    for match in MODEL_LINK_RE.finditer(html):
        urls.add(urljoin(BASE_URL, f"/Models/{match.group(1)}/"))
    return sorted(urls)


def _in_scope_path(path: str) -> bool:
    if OUT_OF_SCOPE_APPLIANCE_RE.search(path):
        return False
    lowered = path.lower()
    return "refrigerator" in lowered or "dishwasher" in lowered or "fridge" in lowered


def extract_category_urls(html: str) -> list[str]:
    urls: set[str] = set()
    for match in CATEGORY_PARTS_RE.finditer(html):
        path = "/" + match.group(1)
        if _in_scope_path(path):
            urls.add(urljoin(BASE_URL, path))
    return sorted(urls)


def extract_repair_help_urls(html: str) -> list[str]:
    urls: set[str] = set()
    for match in REPAIR_HELP_RE.finditer(html):
        path = match.group(0).split('"')[0].split("'")[0]
        if _in_scope_path(path):
            urls.add(urljoin(BASE_URL, path if path.endswith("/") else path + "/"))
    for anchor in BeautifulSoup(html, "lxml").select('a[href*="/Repair/"]'):
        href = anchor.get("href")
        if not href:
            continue
        full = urljoin(BASE_URL, href)
        path = urlparse(full).path
        if "/Repair/" in path and _in_scope_path(path):
            urls.add(full if full.endswith("/") else full + "/")
    return sorted(urls)


def extract_pagination_urls(html: str, *, current_url: str) -> list[str]:
    base_path = urlparse(current_url).path
    urls: set[str] = set()
    for match in re.finditer(r'href="([^"]+)"', html):
        full = urljoin(BASE_URL, match.group(1))
        parsed = urlparse(full)
        if parsed.path == base_path and parsed.query:
            urls.add(full)
    return sorted(urls)


def discover_from_page(html: str, *, source_url: str) -> CategoryDiscovery:
    """Extract crawlable URLs from a category or repair-help listing page."""
    return CategoryDiscovery(
        part_urls=extract_part_urls(html),
        model_urls=extract_model_urls(html),
        category_urls=extract_category_urls(html),
        repair_help_urls=extract_repair_help_urls(html),
        pagination_urls=extract_pagination_urls(html, current_url=source_url),
    )


def parse_repair_help_page(html: str, *, source_url: str) -> list[ScrapedDocument]:
    """Parse a PartSelect repair-help article into troubleshooting documents."""
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one("h1") or soup.select_one(".title-lg")
    title = _text(title_el) or "Repair help article"

    appliance_type = _infer_appliance_type(title + source_url, source_url)

    blocks: list[str] = []
    main = soup.select_one("article") or soup.select_one(
        ".content") or soup.select_one("main")
    if main is not None:
        for el in main.select("p, li"):
            txt = el.get_text(" ", strip=True)
            if len(txt) > 40:
                blocks.append(txt)

    if not blocks:
        body_text = soup.get_text("\n", strip=True)
        blocks = [line for line in body_text.splitlines() if len(line)
                  > 60][:20]

    if not blocks:
        return []

    content = "\n\n".join(blocks[:12])
    linked_parts = [f"PS{m.group(1)}" for m in PS_LINK_RE.finditer(html)]
    metadata: dict[str, object] = {
        "appliance_type": appliance_type,
        "linked_ps_numbers": sorted(set(linked_parts))[:20],
    }

    return [
        ScrapedDocument(
            doc_type="troubleshooting",
            title=title,
            content=content,
            part_ps_number=None,
            source_url=source_url,
            metadata=metadata,
        )
    ]


def parse_part_page(html: str, *, source_url: str) -> ScrapedPart:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.select_one("h1[itemprop=name]") or soup.select_one("h1")
    title = _text(title_el) or "Unknown part"

    ps_el = soup.select_one("[itemprop=productID]")
    ps_text = _text(ps_el)
    ps_match = re.search(r"(PS\d+)", ps_text or source_url, re.I)
    if not ps_match:
        raise ValueError(f"Could not determine PS number for {source_url}")
    ps_str = ps_match.group(0).upper()

    canonical_el = soup.select_one('link[rel="canonical"]')
    if canonical_el and canonical_el.get("href"):
        source_url = urljoin(BASE_URL, canonical_el["href"])

    mpn_el = soup.select_one('[itemprop=mpn]')
    brand_el = soup.select_one('[itemprop=brand] [itemprop=name]')
    desc_el = soup.select_one('[itemprop=description]')

    in_stock = bool(soup.select_one(
        '[itemprop=availability][content=InStock]'))
    if not in_stock:
        in_stock = "in stock" in html.lower()

    difficulty = None
    for p in soup.select(".pd__repair-rating__container p.bold"):
        txt = p.get_text(strip=True)
        if any(k in txt.lower() for k in ("easy", "difficult")):
            difficulty = txt
            break

    duration_text = " ".join(
        p.get_text(strip=True) for p in soup.select(".pd__repair-rating__container p.bold")
    )
    install_minutes = _parse_install_time(duration_text)

    rating = None
    rating_count = None
    rating_block = soup.select_one(
        ".pd__cust-review__header__rating__chart--val")
    if rating_block and rating_block.get("data-rating"):
        with contextlib.suppress(ValueError):
            rating = float(rating_block["data-rating"])
    count_el = soup.select_one(".rating__count")
    if count_el:
        m = re.search(r"(\d+)", count_el.get_text())
        if m:
            rating_count = int(m.group(1))

    images: list[str] = []
    for img in soup.select(".pd__img img, img[itemprop=image]"):
        src = img.get("data-src") or img.get("src")
        if src and not src.startswith("data:"):
            images.append(urljoin(BASE_URL, src))

    video_url = None
    video_el = soup.select_one("[data-yt-init]")
    if video_el and video_el.get("data-yt-init"):
        video_url = f"https://www.youtube.com/watch?v={video_el['data-yt-init']}"

    symptoms: list[str] = []
    trouble = soup.select_one("#Troubleshooting")
    if trouble:
        section = trouble.find_parent(class_=re.compile("expanded|section"))
        if section:
            for li in section.select("li"):
                txt = li.get_text(" ", strip=True)
                if txt and "part fixes" not in txt.lower():
                    symptoms.append(txt)

    replaced: list[str] = []
    cross = soup.select_one("#ModelCrossReference") or soup.find(
        string=re.compile("replaces these", re.I)
    )
    if cross:
        container = cross if isinstance(cross, Tag) else cross.find_parent()
        if container:
            block = container.find_parent("div") or container
            text = block.get_text(" ", strip=True)
            replaced = re.findall(r"\b[A-Z]{1,3}\d{5,}[A-Z0-9]*\b", text)

    install_blocks: list[str] = []
    repair_stories: list[tuple[str, str]] = []
    repair = soup.select_one("#RepairStories")
    if repair:
        section = repair.find_parent(class_=re.compile("expanded|section"))
        container = section if section is not None else repair.find_parent(
            "div")
        if container:
            for idx, story in enumerate(container.select(".repair-story")[:5], start=1):
                title_el = story.select_one(".repair-story__title")
                story_title = _text(title_el) or f"Repair story {idx}"
                body = story.get_text("\n", strip=True)
                if body:
                    install_blocks.append(body)
                    repair_stories.append((story_title, body))
    install_instructions = "\n\n---\n\n".join(
        install_blocks) if install_blocks else None

    compatible_models: list[str] = []
    model_section = soup.select_one("#ModelCrossReference")
    if model_section:
        parent = model_section.find_parent(
            "div", class_=re.compile("expanded|section"))
        if parent:
            for row in parent.select("tr"):
                cells = [c.get_text(strip=True) for c in row.select("td")]
                if len(cells) >= 2 and re.match(r"^[A-Z0-9]{5,}$", cells[1]):
                    compatible_models.append(cells[1])

    appliance_type = _infer_appliance_type(title + _text(desc_el), source_url)

    return ScrapedPart(
        ps_number=ps_str,
        manufacturer_part_number=_text(mpn_el) or None,
        name=title,
        brand=_text(brand_el) or None,
        appliance_type=appliance_type,
        price_cents=_parse_price_cents(soup),
        in_stock=in_stock,
        image_urls=images[:5],
        install_difficulty=difficulty,
        install_time_minutes=install_minutes,
        install_instructions=install_instructions,
        repair_stories=[
            RepairStory(title=title, content=content) for title, content in repair_stories
        ],
        video_url=video_url,
        rating=rating,
        rating_count=rating_count,
        description=_text(desc_el) or None,
        replaced_part_numbers=sorted(set(replaced)),
        symptoms_fixed=symptoms,
        compatible_models=sorted(set(compatible_models)),
        source_url=source_url,
    )


def parse_model_page(html: str, *, source_url: str) -> ScrapedModel:
    soup = BeautifulSoup(html, "lxml")
    model_match = re.search(r"/Models/([^/]+)/?", source_url, re.I)
    if not model_match:
        raise ValueError(f"Not a model URL: {source_url}")
    model_number = model_match.group(1).upper()

    heading = soup.select_one("h1") or soup.select_one(".title-lg")
    title = _text(heading) or model_number
    brand = None
    brand_match = re.search(
        r"^([A-Za-z]+)\s+(?:Refrigerator|Dishwasher)", title, re.I
    )
    if brand_match:
        brand = brand_match.group(1).title()

    appliance_type = _infer_appliance_type(title, source_url)
    part_ps_numbers = [
        f"PS{m.group(1)}"
        for m in PS_LINK_RE.finditer(html)
    ]
    part_ps_numbers = sorted(set(part_ps_numbers))

    symptoms: list[str] = []
    symptoms_section = soup.find(string=re.compile("Common Symptoms", re.I))
    if symptoms_section:
        parent = symptoms_section.find_parent("div")
        if parent:
            for link in parent.select("a"):
                txt = link.get_text(strip=True)
                if txt:
                    symptoms.append(txt)

    return ScrapedModel(
        model_number=model_number,
        brand=brand,
        appliance_type=appliance_type,
        title=title,
        part_ps_numbers=part_ps_numbers,
        symptoms=symptoms,
        source_url=source_url,
    )


def part_to_documents(part: ScrapedPart) -> list[ScrapedDocument]:
    docs: list[ScrapedDocument] = []
    if part.description:
        docs.append(
            ScrapedDocument(
                doc_type="product_description",
                title=part.name,
                content=part.description,
                part_ps_number=part.ps_number,
                source_url=part.source_url,
            )
        )

    story_meta = {
        "difficulty": part.install_difficulty,
        "time_minutes": part.install_time_minutes,
        "video_url": part.video_url,
    }
    if part.repair_stories:
        for idx, story in enumerate(part.repair_stories, start=1):
            docs.append(
                ScrapedDocument(
                    doc_type="install_guide",
                    title=story.title,
                    content=story.content,
                    part_ps_number=part.ps_number,
                    source_url=part.source_url,
                    metadata={"story_index": idx, **story_meta},
                )
            )
    elif part.install_instructions:
        for idx, block in enumerate(
            [b.strip() for b in part.install_instructions.split(
                "\n\n---\n\n") if b.strip()],
            start=1,
        ):
            docs.append(
                ScrapedDocument(
                    doc_type="install_guide",
                    title=f"Repair story {idx} for {part.ps_number}",
                    content=block,
                    part_ps_number=part.ps_number,
                    source_url=part.source_url,
                    metadata={"story_index": idx, **story_meta},
                )
            )

    if part.symptoms_fixed:
        docs.append(
            ScrapedDocument(
                doc_type="troubleshooting",
                title=f"Troubleshooting for {part.ps_number}",
                content="\n".join(f"- {s}" for s in part.symptoms_fixed),
                part_ps_number=part.ps_number,
                source_url=part.source_url,
            )
        )
    return docs
