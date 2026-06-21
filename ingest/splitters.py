import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class RawSegment:
    text: str
    title: str | None = None
    section: str | None = None
    subsection: str | None = None
    page: int | None = None


def split_plain(text: str) -> list[RawSegment]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return [RawSegment(text=p) for p in parts] or [RawSegment(text=text)]


def split_markdown(text: str) -> list[RawSegment]:
    segments: list[RawSegment] = []
    title = section = subsection = None
    buf: list[str] = []
    for line in text.splitlines():
        m = _MD_HEADING.match(line)
        if m:
            if buf:
                segments.append(
                    RawSegment("\n".join(buf).strip(), title, section, subsection)
                )
                buf = []
            level = len(m.group(1))
            heading = m.group(2).strip()
            if level == 1:
                title, section, subsection = heading, None, None
            elif level == 2:
                section, subsection = heading, None
            else:
                subsection = heading
        else:
            buf.append(line)
    if buf:
        segments.append(RawSegment("\n".join(buf).strip(), title, section, subsection))
    return segments or [RawSegment(text=text)]


def split_html(html: str, page_title: str | None = None) -> list[RawSegment]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    title = page_title or (soup.title.string.strip() if soup.title and soup.title.string else None)
    segments: list[RawSegment] = []
    section = subsection = None
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code"]):
        name = el.name or ""
        text = el.get_text("\n", strip=True)
        if not text:
            continue
        if name.startswith("h"):
            level = int(name[1])
            if level == 1:
                section, subsection = text, None
            elif level == 2:
                subsection = text
            segments.append(RawSegment(text, title, section, subsection))
        elif name in ("pre", "code"):
            segments.append(RawSegment(text, title, section, subsection or "code"))
        else:
            segments.append(RawSegment(text, title, section, subsection))
    if not segments:
        body = soup.get_text("\n", strip=True)
        return split_plain(body) if body else [RawSegment(text="")]
    return segments


def split_pdf(file_path: str) -> list[RawSegment]:
    from pypdf import PdfReader

    segments: list[RawSegment] = []
    reader = PdfReader(file_path)
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            segments.append(RawSegment(text, page=i))
    return segments or [RawSegment(text="")]


_CODE_BOUNDARY = re.compile(r"^((?:async\s+)?def \w+|class \w+)", re.MULTILINE)


def split_code(text: str) -> list[RawSegment]:
    matches = list(_CODE_BOUNDARY.finditer(text))
    if not matches:
        return split_plain(text)
    segments: list[RawSegment] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        if block:
            name = match.group(1)
            segments.append(RawSegment(block, section=name, subsection="code"))
    return segments or [RawSegment(text=text)]
