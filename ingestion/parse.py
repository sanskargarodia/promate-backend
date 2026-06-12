"""Parse PartSelect HTML into structured ingestion records."""

from __future__ import annotations

import contextlib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ingestion.types import ScrapedDocument, ScrapedModel, ScrapedPart

BASE_URL = "https://www.partselect.com"
PS_LINK_RE = re.compile(r"/PS(\d+)[^\"'\\s]*", re.I)
MODEL_LINK_RE = re.compile(r"/Models/([^/\"'\\s]+)", re.I)

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

    mpn_el = soup.select_one('[itemprop=mpn]')
    brand_el = soup.select_one('[itemprop=brand] [itemprop=name]')
    desc_el = soup.select_one('[itemprop=description]')

    in_stock = bool(soup.select_one('[itemprop=availability][content=InStock]'))
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
    rating_block = soup.select_one(".pd__cust-review__header__rating__chart--val")
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

    install_steps: list[str] = []
    repair = soup.select_one("#RepairStories")
    if repair:
        section = repair.find_parent(class_=re.compile("expanded|section"))
        if section:
            for story in section.select(".pd__repair-story, .repair-story, article"):
                body = story.get_text("\n", strip=True)
                if body:
                    install_steps.append(body)
    install_instructions = "\n\n---\n\n".join(install_steps[:5]) if install_steps else None

    compatible_models: list[str] = []
    model_section = soup.select_one("#ModelCrossReference")
    if model_section:
        parent = model_section.find_parent("div", class_=re.compile("expanded|section"))
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
    if part.install_instructions:
        docs.append(
            ScrapedDocument(
                doc_type="install_guide",
                title=f"Installation instructions for {part.ps_number}",
                content=part.install_instructions,
                part_ps_number=part.ps_number,
                source_url=part.source_url,
                metadata={
                    "difficulty": part.install_difficulty,
                    "time_minutes": part.install_time_minutes,
                    "video_url": part.video_url,
                },
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
