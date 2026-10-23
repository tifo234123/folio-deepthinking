"""Full-page extraction, provenance, conservative document outline detection."""
import re
import pymupdf


def read_pdf(path, progress=lambda done, total: None, cancelled=lambda: False):
    try:
        doc = pymupdf.open(path)
    except Exception:
        raise ValueError("This file is not a readable PDF") from None
    with doc:
        if doc.needs_pass:
            raise ValueError("This PDF is encrypted. Import an unlocked copy.")
        if not doc.is_pdf or not len(doc):
            raise ValueError("This file contains no PDF pages")
        metadata = doc.metadata or {}
        pages, headings = [], []
        for i, page in enumerate(doc):
            if cancelled():
                raise InterruptedError("Preparation cancelled")
            blocks = page.get_text("blocks", sort=True)
            blocks = [b for b in blocks if len(b) < 7 or b[6] == 0]
            text = page.get_text("text", sort=True)
            warnings = []
            if len(text.strip()) < 30:
                warnings.append("Little or no readable text: OCR or manual review needed")
            if page.get_images() and not text.strip():
                warnings.append("Image-only page; OCR is not enabled")
            # Columns need several substantial blocks on each side sharing vertical space.
            width = page.rect.width
            prose = [b for b in blocks if len(b[4].split()) >= 8]
            left = [b for b in prose if b[2] < width * .55]
            right = [b for b in prose if b[0] > width * .45]
            if len(left) >= 2 and len(right) >= 2 and any(l[1] < r[3] and r[1] < l[3] for l in left for r in right):
                warnings.append("Possible columns; verify reading order in original page")
            if re.search(r"[=∑∫√]|\bTable\s+\d", text):
                warnings.append("Formula or table present; verify notation and layout in original page")
            if "\ufffd" in text:
                warnings.append("Unrecognized characters in extracted text")
            passages = []
            for b in blocks:
                # Keep all text, including repeated margins.
                content = b[4].strip()
                if not content:
                    continue
                # Bounded complete chunks even for a single enormous PDF text block.
                for start in range(0, len(content), 2400):
                    passages.append({"text": content[start:start + 2400], "bbox": list(b[:4])})
            if not passages and text.strip():
                passages = [{"text": text[n:n + 2400], "bbox": None} for n in range(0, len(text), 2400)]
            for line in text.splitlines()[:24]:
                if re.match(r"^(?:Chapter\s+\d+|\d+(?:\.\d+)*[.)]?\s+\S)", line, re.I) and len(line) < 140:
                    prefix = re.match(r"^(\d+(?:\.\d+)*)", line)
                    level = min(4, prefix[1].count(".") + 1) if prefix else 1
                    headings.append((level, line.strip(), i + 1))
            pages.append({"page": i + 1, "label": page.get_label() or str(i + 1),
                          "text": text, "passages": passages, "warnings": warnings})
            progress(i + 1, len(doc))
        toc = [(max(1, int(level)), str(title), int(page)) for level, title, page in doc.get_toc()
               if 1 <= page <= len(doc)]
        origin = "PDF outline"
        if not toc:
            toc = list(dict.fromkeys(headings))
            origin = "Inferred numbered headings (review boundaries)"
        if not toc:
            toc = [(1, f"Pages {p}–{min(p + 9, len(doc))}", p) for p in range(1, len(doc) + 1, 10)]
            origin = "Page-range fallback"
        # Preserve a front matter range when the first detected chapter starts later.
        toc.sort(key=lambda item: item[2])
        if toc[0][2] > 1:
            toc.insert(0, (1, "Front matter", 1))
        # Running headers/footers stay in the passages; the deep-reading prompt classifies them.
        # They are not flagged per page, where they would mark every page of most books.
        sections, parents = [], {}
        for index, (level, title, start) in enumerate(toc):
            end = len(doc)
            for following_level, _, following_page in toc[index + 1:]:
                if following_level <= level:
                    end = max(start, following_page - 1)
                    break
            parent = next((parents[n] for n in range(level - 1, 0, -1) if n in parents), None)
            parents = {k: v for k, v in parents.items() if k < level}
            parents[level] = index
            sections.append({"title": title, "start": start, "end": end, "parent": parent, "origin": origin})
        return {"title": metadata.get("title", "").strip(), "author": metadata.get("author", "").strip(),
                "pages": pages, "sections": sections}

