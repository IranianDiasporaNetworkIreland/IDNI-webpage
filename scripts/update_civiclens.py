#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_HTML_PATH = REPO_ROOT / "index.html"
CIVICLENS_HTML_PATH = REPO_ROOT / "civic-lens" / "index.html"
DEFAULT_SOURCE_URL = os.environ.get(
    "MEDIA_DASHBOARD_SOURCE_URL",
    "https://raw.githubusercontent.com/IranianDiasporaNetworkIreland/media-dashboard/main/index.html",
)
FETCH_TIMEOUT = int(os.environ.get("CIVICLENS_FETCH_TIMEOUT", "30"))

TOPIC_LABELS = {
    "hr": "Human Rights",
    "diplomacy": "Diplomacy",
    "protest": "Protest",
    "sanctions": "Sanctions",
    "diaspora": "Diaspora",
    "other": "Other",
}

PREVIEW_THEMES = {
    "hr": {"icon": "&#9878;", "bg": "rgba(232,184,75,.08)", "bg2": "rgba(232,184,75,.02)", "border": "rgba(232,184,75,.2)", "hover": "rgba(232,184,75,.5)", "shadow": "rgba(232,184,75,.1)"},
    "diplomacy": {"icon": "&#127760;", "bg": "rgba(59,130,246,.08)", "bg2": "rgba(59,130,246,.02)", "border": "rgba(59,130,246,.2)", "hover": "rgba(59,130,246,.5)", "shadow": "rgba(59,130,246,.1)"},
    "protest": {"icon": "&#128227;", "bg": "rgba(244,114,182,.08)", "bg2": "rgba(244,114,182,.02)", "border": "rgba(244,114,182,.2)", "hover": "rgba(244,114,182,.5)", "shadow": "rgba(244,114,182,.1)"},
    "sanctions": {"icon": "&#129517;", "bg": "rgba(34,197,94,.08)", "bg2": "rgba(34,197,94,.02)", "border": "rgba(34,197,94,.2)", "hover": "rgba(34,197,94,.5)", "shadow": "rgba(34,197,94,.1)"},
    "diaspora": {"icon": "&#128101;", "bg": "rgba(168,85,247,.08)", "bg2": "rgba(168,85,247,.02)", "border": "rgba(168,85,247,.2)", "hover": "rgba(168,85,247,.5)", "shadow": "rgba(168,85,247,.1)"},
    "other": {"icon": "&#128240;", "bg": "rgba(148,163,184,.08)", "bg2": "rgba(148,163,184,.02)", "border": "rgba(148,163,184,.2)", "hover": "rgba(148,163,184,.5)", "shadow": "rgba(148,163,184,.1)"},
}

ARTICLE_PATTERN = re.compile(
    r'\{\s*headline:\s*"(?P<headline>(?:\\.|[^"\\])*)",\s*'
    r'url:\s*"(?P<url>(?:\\.|[^"\\])*)",\s*'
    r'outlet:\s*"(?P<outlet>(?:\\.|[^"\\])*)",\s*'
    r'date:\s*"(?P<date>(?:\\.|[^"\\])*)",\s*'
    r'topic:\s*"(?P<topic>(?:\\.|[^"\\])*)",\s*'
    r'excerpt:\s*"(?P<excerpt>(?:\\.|[^"\\])*)",\s*'
    r'experienced:\s*(?P<experienced>\d+),\s*'
    r'groundNews:\s*(?P<groundNews>\d+),\s*'
    r'regimeNarrative:\s*(?P<regimeNarrative>\d+),\s*'
    r'trustScore:\s*(?P<trustScore>\d+)\s*\}',
    re.DOTALL,
)


@dataclass
class SourceArticle:
    article_id: str
    date: str
    outlet: str
    journalist: str
    headline: str
    url: str
    article_type: str
    framing: str
    relevant: str
    notes: str
    ie_flag: str


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (CivicLens updater)"})
    with urlopen(request, timeout=FETCH_TIMEOUT) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="ignore")


def extract_bracket_block(text: str, anchor: str) -> str:
    anchor_index = text.find(anchor)
    if anchor_index == -1:
        raise ValueError(f"Could not find anchor: {anchor}")
    start = text.find("[", anchor_index)
    if start == -1:
        raise ValueError(f"Could not find opening bracket after {anchor}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    raise ValueError(f"Could not find matching closing bracket for {anchor}")


def parse_source_articles(source_html: str) -> list[SourceArticle]:
    rows = json.loads(extract_bracket_block(source_html, "articles:"))
    articles: list[SourceArticle] = []
    for row in rows:
        if len(row) < 11:
            continue
        articles.append(
            SourceArticle(
                article_id=row[0],
                date=row[1],
                outlet=row[2],
                journalist=row[3],
                headline=row[4],
                url=row[5],
                article_type=row[6],
                framing=row[7],
                relevant=row[8],
                notes=row[9],
                ie_flag=row[10],
            )
        )
    return articles


def parse_existing_articles(civiclens_html: str) -> list[dict]:
    match = re.search(r"const SAMPLE_ARTICLES = \[(?P<body>.*?)\n\];", civiclens_html, re.DOTALL)
    if not match:
        raise ValueError("Could not locate SAMPLE_ARTICLES block")
    articles: list[dict] = []
    for found in ARTICLE_PATTERN.finditer(match.group("body")):
        articles.append(
            {
                "headline": json.loads(f'"{found.group("headline")}"'),
                "url": json.loads(f'"{found.group("url")}"'),
                "outlet": json.loads(f'"{found.group("outlet")}"'),
                "date": json.loads(f'"{found.group("date")}"'),
                "topic": json.loads(f'"{found.group("topic")}"'),
                "excerpt": json.loads(f'"{found.group("excerpt")}"'),
                "experienced": int(found.group("experienced")),
                "groundNews": int(found.group("groundNews")),
                "regimeNarrative": int(found.group("regimeNarrative")),
                "trustScore": int(found.group("trustScore")),
            }
        )
    return articles


def normalize_headline(text: str) -> str:
    text = re.sub(r"\s+-\s+[^-]+$", "", text or "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def article_key(article: dict) -> tuple[str, str]:
    return normalize_headline(article.get("headline", "")), (article.get("outlet", "") or "").strip().casefold()


def source_key(article: SourceArticle) -> tuple[str, str]:
    return normalize_headline(article.headline), article.outlet.strip().casefold()


def sort_articles_for_display(articles: list[dict]) -> list[dict]:
    return sorted(
        articles,
        key=lambda article: (article.get("date", ""), calc_overall(article), article.get("headline", "")),
        reverse=True,
    )


def calc_overall(article: dict) -> int:
    return round((article["experienced"] + article["groundNews"] + article["regimeNarrative"] + article["trustScore"]) / 4)


def select_new_articles(source_articles: list[SourceArticle], existing_articles: list[dict], limit: int) -> list[SourceArticle]:
    existing_keys = {article_key(article) for article in existing_articles}
    existing_urls = {article.get("url", "") for article in existing_articles}
    chosen: list[SourceArticle] = []
    seen_keys: set[tuple[str, str]] = set()
    for candidate in sorted(source_articles, key=lambda article: (article.date, article.article_id), reverse=True):
        key = source_key(candidate)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if key in existing_keys or candidate.url in existing_urls:
            continue
        chosen.append(candidate)
        if len(chosen) >= limit:
            break
    return chosen


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_page_context(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (CivicLens updater)"})
    with urlopen(request, timeout=FETCH_TIMEOUT) as response:
        resolved_url = response.geturl()
        charset = response.headers.get_content_charset() or "utf-8"
        raw_html = response.read().decode(charset, errors="ignore")
    page_title = ""
    title_match = re.search(r"<title>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    if title_match:
        page_title = clean_text(html.unescape(title_match.group(1)))
    description = ""
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\'](.*?)["\'][^>]+property=["\']og:description["\']',
    ):
        match = re.search(pattern, raw_html, re.IGNORECASE | re.DOTALL)
        if match:
            description = clean_text(html.unescape(match.group(1)))
            break
    readable = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL)
    readable = re.sub(r"<style\b[^>]*>.*?</style>", " ", readable, flags=re.IGNORECASE | re.DOTALL)
    readable = re.sub(r"<noscript\b[^>]*>.*?</noscript>", " ", readable, flags=re.IGNORECASE | re.DOTALL)
    readable = re.sub(r"<[^>]+>", " ", readable)
    readable = clean_text(html.unescape(readable))[:12000]
    return {
        "resolved_url": resolved_url,
        "title": page_title,
        "description": description,
        "text": readable,
    }


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM response did not contain a JSON object")
    return json.loads(text[start:end + 1])


def call_llm(prompt: str) -> dict:
    provider = os.environ.get("CIVICLENS_LLM_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        base_url = os.environ.get("CIVICLENS_GROQ_URL", "https://api.groq.com/openai/v1/chat/completions")
        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("CIVICLENS_GROQ_MODEL", "llama-3.1-8b-instant")
    elif provider == "openrouter":
        base_url = os.environ.get("CIVICLENS_OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        model = os.environ.get("CIVICLENS_OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
    elif provider == "openai":
        base_url = os.environ.get("CIVICLENS_OPENAI_URL", "https://api.openai.com/v1/chat/completions")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("CIVICLENS_OPENAI_MODEL", "gpt-4o-mini")
    else:
        raise RuntimeError(f"Unsupported CIVICLENS_LLM_PROVIDER: {provider}")

    if not api_key:
        raise RuntimeError(f"Missing API key for provider: {provider}")

    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You score media coverage of Iran for the CivicLens dashboard. "
                    "Return strict JSON with keys topic, excerpt, experienced, groundNews, regimeNarrative, trustScore. "
                    "topic must be one of hr, diplomacy, protest, sanctions, diaspora, other. "
                    "All numeric scores must be integers from 0 to 100. "
                    "excerpt must be one sentence under 170 characters."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    request = Request(
        base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "CivicLens Updater",
        },
    )
    with urlopen(request, timeout=FETCH_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    raw_content = body["choices"][0]["message"]["content"]
    result = extract_json_object(raw_content)
    result["topic"] = result.get("topic", "other") if result.get("topic") in TOPIC_LABELS else "other"
    result["excerpt"] = clean_text(result.get("excerpt", ""))[:170]
    for field in ("experienced", "groundNews", "regimeNarrative", "trustScore"):
        result[field] = max(0, min(100, int(result[field])))
    return result


def heuristic_judge(article: SourceArticle, context: dict) -> dict:
    combined = clean_text(" ".join([article.headline, article.notes, context.get("description", ""), context.get("title", "")])).casefold()
    topic = "diplomacy"
    if any(token in combined for token in ("rights", "execution", "woman", "dead", "deport", "asylum")):
        topic = "hr"
    elif any(token in combined for token in ("protest", "demonstration", "march")):
        topic = "protest"
    elif any(token in combined for token in ("sanction", "settlement", "ban")):
        topic = "sanctions"
    elif any(token in combined for token in ("diaspora", "community", "embassy support")):
        topic = "diaspora"
    experienced = 82 if topic == "hr" else 55
    ground_news = 80 if article.ie_flag.upper() == "IE" else 68
    regime = 90 if any(token in combined for token in ("wana", "mehr", "tehran applauds", "hails ireland")) else 35
    trust = 78 if any(token in article.outlet.casefold() for token in ("irish", "journal", "mirror", "bay", "examiner", "times")) else 58
    excerpt = clean_text(article.notes or context.get("description") or article.headline)[:170]
    return {
        "topic": topic,
        "excerpt": excerpt,
        "experienced": experienced,
        "groundNews": ground_news,
        "regimeNarrative": regime,
        "trustScore": trust,
    }


def judge_article(article: SourceArticle, context: dict, skip_llm: bool) -> dict:
    prompt = json.dumps(
        {
            "headline": article.headline,
            "outlet": article.outlet,
            "date": article.date,
            "article_type": article.article_type,
            "framing": article.framing,
            "notes": article.notes,
            "source_url": article.url,
            "resolved_url": context.get("resolved_url", article.url),
            "page_title": context.get("title", ""),
            "meta_description": context.get("description", ""),
            "article_text": context.get("text", "")[:8000],
        },
        ensure_ascii=False,
    )
    return heuristic_judge(article, context) if skip_llm else call_llm(prompt)


def strip_outlet_suffix(headline: str, outlet: str) -> str:
    return re.sub(rf"\s+-\s+{re.escape(outlet)}$", "", headline).strip()


def build_article_entry(article: SourceArticle, judged: dict) -> dict:
    return {
        "headline": strip_outlet_suffix(article.headline, article.outlet),
        "url": article.url,
        "outlet": article.outlet,
        "date": article.date,
        "topic": judged["topic"],
        "excerpt": judged["excerpt"],
        "experienced": judged["experienced"],
        "groundNews": judged["groundNews"],
        "regimeNarrative": judged["regimeNarrative"],
        "trustScore": judged["trustScore"],
    }


def serialize_sample_articles(articles: list[dict]) -> str:
    lines = ["const SAMPLE_ARTICLES = ["]
    for article in articles:
        lines.append(
            "  { headline: %s, url: %s, outlet: %s, date: %s, topic: %s, excerpt: %s, experienced: %d, groundNews: %d, regimeNarrative: %d, trustScore: %d },"
            % (
                json.dumps(article["headline"], ensure_ascii=False),
                json.dumps(article["url"], ensure_ascii=False),
                json.dumps(article["outlet"], ensure_ascii=False),
                json.dumps(article["date"], ensure_ascii=False),
                json.dumps(article["topic"], ensure_ascii=False),
                json.dumps(article["excerpt"], ensure_ascii=False),
                int(article["experienced"]),
                int(article["groundNews"]),
                int(article["regimeNarrative"]),
                int(article["trustScore"]),
            )
        )
    lines.append("];")
    return "\n".join(lines)


def format_preview_date(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d").replace(" 0", " ")


def render_preview_grid(articles: list[dict]) -> str:
    cards = []
    for index, article in enumerate(sort_articles_for_display(articles)[:3], start=1):
        theme = PREVIEW_THEMES.get(article["topic"], PREVIEW_THEMES["other"])
        delay = 50 + index * 50
        overall = calc_overall(article)
        headline = html.escape(article["headline"])
        meta = html.escape(f"{article['outlet']} • {format_preview_date(article['date'])}")
        excerpt = html.escape(article["excerpt"])
        url = html.escape(article["url"], quote=True)
        experienced = int(article["experienced"])
        ground_news = int(article["groundNews"])
        trust_score = int(article["trustScore"])
        cards.extend(
            [
                f"        <!-- Article {index}: {headline} -->",
                f"            <a class=\"fade-up cl-preview-card\" href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\" style=\"--card-start: {theme['bg']}; --card-end: {theme['bg2']}; --card-border: {theme['border']}; --card-hover: {theme['hover']}; --card-shadow: {theme['shadow']}; animation-delay: {delay}ms;\">",
                "              <div class=\"cl-preview-card-top\">",
                f"                <div class=\"cl-preview-icon\">{theme['icon']}</div>",
                f"                <div class=\"cl-preview-score\">{overall}</div>",
                "              </div>",
                f"              <div class=\"cl-preview-meta\">{meta}</div>",
                f"              <div class=\"cl-preview-title\">{headline}</div>",
                f"              <div class=\"cl-preview-excerpt\">{excerpt}</div>",
                "              <div class=\"cl-preview-bars\">",
                f"                <div class=\"cl-preview-bar-row\"><div class=\"cl-preview-bar-label\">Voices</div><div class=\"cl-preview-track\"><div class=\"cl-preview-fill voices\" style=\"--fill-width:{experienced}%;--delay:{delay + 80}ms;\"></div></div><div class=\"cl-preview-bar-value\">{experienced}</div></div>",
                f"                <div class=\"cl-preview-bar-row\"><div class=\"cl-preview-bar-label\">Ground</div><div class=\"cl-preview-track\"><div class=\"cl-preview-fill ground\" style=\"--fill-width:{ground_news}%;--delay:{delay + 140}ms;\"></div></div><div class=\"cl-preview-bar-value\">{ground_news}</div></div>",
                f"                <div class=\"cl-preview-bar-row\"><div class=\"cl-preview-bar-label\">Trust</div><div class=\"cl-preview-track\"><div class=\"cl-preview-fill trust\" style=\"--fill-width:{trust_score}%;--delay:{delay + 200}ms;\"></div></div><div class=\"cl-preview-bar-value\">{trust_score}</div></div>",
                "              </div>",
                "            </a>",
            ]
        )
    inner_html = "\n".join(cards)
    return (
        "          <div class=\"cl-preview-grid\">\n"
        f"{inner_html}\n"
        "          </div>"
    )


def replace_sample_articles_block(civiclens_html: str, articles: list[dict]) -> str:
    updated, count = re.subn(
        r"const SAMPLE_ARTICLES = \[(?P<body>.*?)\n\];",
        serialize_sample_articles(articles),
        civiclens_html,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Failed to replace SAMPLE_ARTICLES block")
    return updated


def replace_preview_block(main_html: str, articles: list[dict]) -> str:
    replacement = "<!-- CIVICLENS_PREVIEW_START -->\n" + render_preview_grid(articles) + "\n      <!-- CIVICLENS_PREVIEW_END -->"
    updated, count = re.subn(
        r"<!-- CIVICLENS_PREVIEW_START -->(?P<body>.*?)<!-- CIVICLENS_PREVIEW_END -->",
        replacement,
        main_html,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("Failed to replace CivicLens preview block")
    return updated


def write_text_preserving_newlines(path: Path, content: str, reference_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    newline = "\r\n" if "\r\n" in reference_text else "\n"
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)
    path.write_text(normalized, encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update CivicLens from the Media Dashboard article tab")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("CIVICLENS_NEW_ARTICLE_LIMIT", "10")))
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--source-file")
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_html = Path(args.source_file).read_text(encoding="utf-8") if args.source_file else fetch_text(args.source_url)
    civic_html = CIVICLENS_HTML_PATH.read_text(encoding="utf-8")
    main_html = MAIN_HTML_PATH.read_text(encoding="utf-8")

    source_articles = parse_source_articles(source_html)
    existing_articles = parse_existing_articles(civic_html)
    candidates = select_new_articles(source_articles, existing_articles, args.limit)
    print(f"Found {len(candidates)} new source candidates.")
    if not candidates:
        return 0

    added_articles: list[dict] = []
    for candidate in candidates:
        print(f"Evaluating {candidate.headline}")
        try:
            context = extract_page_context(candidate.url)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"Skipping inaccessible link: {candidate.url} ({exc})")
            continue
        judged = judge_article(candidate, context, args.skip_llm)
        added_articles.append(build_article_entry(candidate, judged))

    if not added_articles:
        print("No accessible new articles to add.")
        return 0

    updated_articles = sort_articles_for_display(existing_articles + added_articles)
    new_civic_html = replace_sample_articles_block(civic_html, updated_articles)
    new_main_html = replace_preview_block(main_html, updated_articles)

    if args.dry_run:
        print(f"Dry run complete. Would add {len(added_articles)} articles.")
        return 0

    write_text_preserving_newlines(CIVICLENS_HTML_PATH, new_civic_html, civic_html)
    write_text_preserving_newlines(MAIN_HTML_PATH, new_main_html, main_html)
    print(f"Added {len(added_articles)} new CivicLens articles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
