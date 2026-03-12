"""
Help documentation views.

Renders markdown documentation files from apps/help/docs/.
Supports multiple languages (en, fi).
"""

import re
from pathlib import Path

import markdown
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils.safestring import mark_safe
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.tables import TableExtension
from markdown.extensions.toc import TocExtension

DOCS_DIR = Path(__file__).parent / "docs"

# Supported languages
LANGUAGES = {
    "en": "English",
    "fi": "Suomi",
}

DEFAULT_LANGUAGE = "en"

# Available documentation pages per language
HELP_PAGES = {
    "en": {
        "index": {"title": "Documentation", "file": "index.md"},
        "tutorial": {"title": "Getting Started", "file": "tutorial.md"},
        "concepts": {"title": "Core Concepts", "file": "concepts.md"},
        "guides": {"title": "Guides", "file": "guides.md"},
        "recipes": {"title": "Recipes", "file": "recipes.md"},
        "mcp": {"title": "MCP & Agents", "file": "mcp.md"},
        "reference": {"title": "YAML Reference", "file": "reference.md"},
        "troubleshooting": {"title": "Troubleshooting", "file": "troubleshooting.md"},
        "faq": {"title": "FAQ", "file": "faq.md"},
        # Legacy pages (redirect to new structure)
        "systems": {"title": "Systems", "file": "concepts.md"},
    },
    "fi": {
        "index": {"title": "Dokumentaatio", "file": "index.md"},
        "tutorial": {"title": "Aloitusopas", "file": "tutorial.md"},
        "concepts": {"title": "Ydinkäsitteet", "file": "concepts.md"},
        "guides": {"title": "Käyttöoppaat", "file": "guides.md"},
        "recipes": {"title": "Reseptit", "file": "recipes.md"},
        "mcp": {"title": "MCP ja agentit", "file": "mcp.md"},
        "reference": {"title": "YAML-viite", "file": "reference.md"},
        "troubleshooting": {"title": "Vianmääritys", "file": "troubleshooting.md"},
        "faq": {"title": "UKK", "file": "faq.md"},
        # Legacy pages
        "systems": {"title": "Järjestelmät", "file": "concepts.md"},
    },
}

# Navigation labels per language
NAV_LABELS = {
    "en": {
        "getting_started": "Getting Started",
        "overview": "Overview",
        "learn": "Learn",
        "build": "Build",
        "reference": "Reference",
        "help": "Help",
    },
    "fi": {
        "getting_started": "Aloitus",
        "overview": "Yleiskatsaus",
        "learn": "Opettele",
        "build": "Rakenna",
        "reference": "Viite",
        "help": "Apua",
    },
}


def _render_markdown(content: str) -> tuple[str, list]:
    """
    Render markdown content to HTML with syntax highlighting.
    Returns (html, toc).
    """
    md = markdown.Markdown(
        extensions=[
            FencedCodeExtension(),
            CodeHiliteExtension(css_class="highlight", guess_lang=False),
            TableExtension(),
            TocExtension(permalink=True, toc_depth=3),
            "md_in_html",
        ]
    )
    html = md.convert(content)
    toc = getattr(md, "toc_tokens", [])
    return html, toc


def _get_page_content(page_slug: str, lang: str = "en") -> tuple[str, str, list]:
    """
    Load and render a documentation page.
    Returns (title, html_content, toc).
    """
    pages = HELP_PAGES.get(lang, HELP_PAGES["en"])
    page_info = pages.get(page_slug)
    if not page_info:
        raise Http404(f"Help page '{page_slug}' not found")

    # Determine file path based on language
    if lang == "en":
        file_path = DOCS_DIR / page_info["file"]
    else:
        file_path = DOCS_DIR / lang / page_info["file"]

    if not file_path.exists():
        # Fallback to English if translation doesn't exist
        file_path = DOCS_DIR / page_info["file"]
        if not file_path.exists():
            raise Http404(f"Documentation file not found: {page_info['file']}")

    content = file_path.read_text(encoding="utf-8")

    # Extract title from first H1 if present
    title = page_info["title"]
    title_match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        title = title_match.group(1)

    html, toc = _render_markdown(content)
    return title, html, toc


def help_index(request):
    """Display the main help documentation page (redirects to English)."""
    return redirect("help:lang_index", lang="en")


def help_page(request, page: str):
    """Display a specific help documentation page (redirects to English)."""
    return redirect("help:lang_page", lang="en", page=page)


def help_lang_index(request, lang: str):
    """Display the main help documentation page in specified language."""
    if lang not in LANGUAGES:
        return redirect("help:lang_index", lang="en")

    title, content, toc = _get_page_content("index", lang)

    return render(
        request,
        "help/page.html",
        {
            "title": title,
            "content": mark_safe(content),  # nosec: B308, B703
            "toc": toc,
            "pages": HELP_PAGES.get(lang, HELP_PAGES["en"]),
            "current_page": "index",
            "current_lang": lang,
            "languages": LANGUAGES,
            "nav_labels": NAV_LABELS.get(lang, NAV_LABELS["en"]),
        },
    )


def help_lang_page(request, lang: str, page: str):
    """Display a specific help documentation page in specified language."""
    if lang not in LANGUAGES:
        return redirect("help:lang_page", lang="en", page=page)

    title, content, toc = _get_page_content(page, lang)

    return render(
        request,
        "help/page.html",
        {
            "title": title,
            "content": mark_safe(content),  # nosec: B308, B703
            "toc": toc,
            "pages": HELP_PAGES.get(lang, HELP_PAGES["en"]),
            "current_page": page,
            "current_lang": lang,
            "languages": LANGUAGES,
            "nav_labels": NAV_LABELS.get(lang, NAV_LABELS["en"]),
        },
    )


def _get_raw_markdown(page_slug: str, lang: str = "en") -> tuple[str, str]:
    """
    Get raw markdown content for a page.
    Returns (filename, content).
    """
    pages = HELP_PAGES.get(lang, HELP_PAGES["en"])
    page_info = pages.get(page_slug)
    if not page_info:
        raise Http404(f"Help page '{page_slug}' not found")

    # Determine file path based on language
    if lang == "en":
        file_path = DOCS_DIR / page_info["file"]
    else:
        file_path = DOCS_DIR / lang / page_info["file"]

    if not file_path.exists():
        file_path = DOCS_DIR / page_info["file"]
        if not file_path.exists():
            raise Http404(f"Documentation file not found: {page_info['file']}")

    content = file_path.read_text(encoding="utf-8")
    filename = f"adapterly-{page_slug}-{lang}.md"
    return filename, content


def download_page(request, lang: str, page: str):
    """Download a single documentation page as markdown."""
    if lang not in LANGUAGES:
        lang = "en"

    filename, content = _get_raw_markdown(page, lang)

    response = HttpResponse(content, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def download_all(request, lang: str):
    """Download all documentation as a single markdown file."""
    if lang not in LANGUAGES:
        lang = "en"

    pages = HELP_PAGES.get(lang, HELP_PAGES["en"])

    # Combine all pages into one document
    combined = []
    combined.append(f"# Adapterly Documentation ({LANGUAGES[lang]})\n")
    combined.append(f"Downloaded from https://adapterly.ai/help/{lang}/\n")
    combined.append("=" * 60 + "\n\n")

    # Order: index first, then alphabetically
    page_order = ["index"] + sorted([p for p in pages.keys() if p != "index"])

    for page_slug in page_order:
        try:
            _, content = _get_raw_markdown(page_slug, lang)
            combined.append(content)
            combined.append("\n\n" + "-" * 60 + "\n\n")
        except Http404:
            continue

    full_content = "\n".join(combined)
    filename = f"adapterly-docs-{lang}.md"

    response = HttpResponse(full_content, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
