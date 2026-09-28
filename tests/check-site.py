#!/usr/bin/env python3
"""Check the built website for SEO basics before it is published:
title 30-60 chars, meta description 110-160 chars, exactly one <h1>, valid
JSON-LD, canonical + Open Graph image, every internal link and image resolves,
every sitemap URL has a page, and no @PLACEHOLDER@ is left.

    tests/check-site.py _site https://USER.github.io/REPO
"""
import json
import os
import re
import sys
from html.parser import HTMLParser


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.meta, self.ld, self.title, self.h1 = [], {}, [], "", 0
        self.canonical = None
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and "href" in a:
            self.links.append(a["href"])
        elif tag == "link":
            if a.get("rel") in ("stylesheet", "icon"):
                self.links.append(a["href"])
            if a.get("rel") == "canonical":
                self.canonical = a.get("href")
        elif tag == "img":
            self.links.append(a["src"])
        elif tag == "meta":
            self.meta[a.get("name") or a.get("property")] = a.get("content") or ""
        elif tag == "h1":
            self.h1 += 1
        if tag == "title" or (tag == "script" and a.get("type") == "application/ld+json"):
            self._in = tag
            if tag == "script":
                self.ld.append("")

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "script":
            self.ld[-1] += data


def main(out, url):
    url = url.rstrip("/")
    bad = 0

    def resolve(src_dir, link):
        link = link.split("#")[0]
        if link.startswith(url):
            target = os.path.join(out, link[len(url):].lstrip("/"))
        elif re.match(r"^[a-z]+:", link):
            return True                       # external (GitHub, etc.)
        else:
            target = os.path.normpath(os.path.join(src_dir, link))
        if os.path.isdir(target):
            target = os.path.join(target, "index.html")
        return os.path.exists(target)

    for root, _, files in os.walk(out):
        for name in sorted(files):
            if not name.endswith(".html"):
                continue
            path = os.path.join(root, name)
            html = open(path, encoding="utf-8").read()
            p = Page()
            p.feed(html)
            probs = []
            left = re.findall(r"@[A-Z]+@", html)
            if left:
                probs.append(f"placeholders left: {sorted(set(left))}")
            if not 30 <= len(p.title) <= 60:
                probs.append(f"title is {len(p.title)} chars (30-60)")
            desc = p.meta.get("description", "")
            if name != "404.html":
                if not 110 <= len(desc) <= 160:
                    probs.append(f"description is {len(desc)} chars (110-160)")
                if not p.canonical:
                    probs.append("no canonical link")
                if not p.meta.get("og:image"):
                    probs.append("no og:image")
            if p.h1 != 1:
                probs.append(f"{p.h1} <h1> elements")
            for block in p.ld:
                try:
                    json.loads(block)
                except ValueError as e:
                    probs.append(f"invalid JSON-LD: {e}")
            for link in p.links:
                if not resolve(os.path.dirname(path), link):
                    probs.append(f"broken link: {link}")
            rel = os.path.relpath(path, out)
            print(f"{'ok ' if not probs else 'BAD'}  {rel:32} title {len(p.title):>2}  description {len(desc):>3}"
                  + ("" if not probs else "  <- " + "; ".join(probs)))
            bad += bool(probs)

    for loc in re.findall(r"<loc>(.*?)</loc>", open(os.path.join(out, "sitemap.xml")).read()):
        if not resolve(out, loc):
            print(f"BAD  sitemap lists a missing page: {loc}")
            bad += 1
    print("site check:", "passed" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
