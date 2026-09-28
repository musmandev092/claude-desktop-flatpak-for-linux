#!/usr/bin/env python3
"""Build the GitHub Pages site (SEO pages, sitemap, robots, llms.txt, IndexNow key).

    site/build.py --out _site --url https://USER.github.io/REPO --version 2.7032.0

Page bodies live in site/pages/*.html; this adds the <head> (title, description,
canonical, Open Graph, JSON-LD), the navigation and the footer. Optional search
engine verification tags come from the environment:
GOOGLE_SITE_VERIFICATION, BING_SITE_VERIFICATION, YANDEX_VERIFICATION.
"""
import argparse
import datetime
import html
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "https://github.com/musmandev092/claude-desktop-flatpak-for-linux"
APP_ID = "io.github.musmandev092.ClaudeDesktop"
# IndexNow key: public by design (search engines fetch it to confirm the pings are ours)
VERIFY_FILE = re.compile(r"google[0-9a-f]{16}\.html|BingSiteAuth\.xml|yandex_[0-9a-f]{16}\.html")
INDEXNOW_KEY = "5c3f0e9b8a7d46e1b2c4f6a8d0e2b4c6"  # gitleaks:allow (public by design)

# slug, nav label, <title>, meta description, H1
PAGES = [
    ("", "Home",
     "Claude Desktop for Linux – Flatpak for Fedora, Arch & more",
     "Install the official Claude Desktop app on Fedora, Silverblue, Arch or any Linux with one Flatpak "
     "command. Claude Code, MCP plugins, Cowork, auto-updates.",
     "Claude Desktop for Linux"),
    ("fedora", "Fedora",
     "Install Claude Desktop on Fedora 44 – Flatpak guide",
     "Install the official Claude Desktop app on Fedora Workstation or KDE with one Flatpak command. "
     "No dnf repos, no root. Claude Code and MCP work.",
     "Install Claude Desktop on Fedora"),
    ("fedora-silverblue", "Silverblue & atomic",
     "Claude Desktop on Silverblue, Kinoite, Bazzite & Bluefin",
     "Run Claude Desktop on Fedora Atomic (Silverblue, Kinoite, Bazzite, Bluefin) without rpm-ostree "
     "layering. Plugins use the tools in your toolbox.",
     "Claude Desktop on Silverblue, Kinoite, Bazzite & Bluefin"),
    ("arch-linux", "Arch",
     "Claude Desktop on Arch Linux, Manjaro & CachyOS – Flatpak",
     "Install the official Claude Desktop app on Arch, Manjaro, EndeavourOS or CachyOS as a signed "
     "Flatpak with auto-updates. Claude Code, MCP, Cowork.",
     "Claude Desktop on Arch Linux"),
    ("cowork-linux", "Cowork",
     "Claude Cowork on Linux – cloud VM or local KVM machine",
     "How Claude Cowork works on Linux: Anthropic's cloud VM by default, or a local KVM virtual machine. "
     "Setup, requirements, memory use, fixes.",
     "Claude Cowork on Linux"),
    ("mcp-plugins", "MCP & Claude Code",
     "MCP servers & Claude Code in the Claude Desktop Flatpak",
     "Use every local MCP server (npx, uvx, docker) and Claude Code with your real tools in the Claude "
     "Desktop Flatpak – on the host or in a toolbox.",
     "MCP servers and Claude Code in the Flatpak"),
    ("trust", "How releases are made",
     "How Claude Desktop Flatpak releases are made and verified",
     "Every release is built, tested, signed and published by GitHub Actions in public, with no human "
     "step. See the process and verify a release yourself.",
     "How releases are made – and how to verify them"),
]


def page(slug, label, title, desc, h1, body, url, version, today, verify, root=None):
    canonical = f"{url}/{slug + '/' if slug else ''}"
    if root is None:
        root = "../" if slug else ""
    nav = "".join(
        f'<li><a href="{root}{s + "/" if s else ""}"{" aria-current=\"page\"" if s == slug else ""}>{html.escape(l)}</a></li>'
        for s, l, *_ in PAGES) + f'<li><a href="{REPO}">GitHub</a></li>'
    if slug:
        ld = [{
            "@context": "https://schema.org", "@type": "TechArticle",
            "headline": h1, "description": desc, "url": canonical, "dateModified": today,
            "inLanguage": "en", "author": {"@type": "Person", "name": "Muhammad Usman", "url": "https://github.com/musmandev092"},
            "about": {"@type": "SoftwareApplication", "name": "Claude Desktop for Linux (unofficial Flatpak)"},
        }, {
            "@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Claude Desktop for Linux", "item": f"{url}/"},
                {"@type": "ListItem", "position": 2, "name": label, "item": canonical}],
        }]
        crumbs = f'<p class="crumbs"><a href="{root}">Claude Desktop for Linux</a> › {html.escape(label)}</p>'
        hero = f"<h1>{html.escape(h1)}</h1>"
    else:
        ld = [{
            "@context": "https://schema.org", "@type": "SoftwareApplication",
            "name": "Claude Desktop for Linux (unofficial Flatpak)",
            "alternateName": ["Claude Desktop Flatpak", "Claude for Linux"],
            "description": desc, "operatingSystem": "Linux (x86_64)",
            "applicationCategory": "DeveloperApplication", "softwareVersion": version,
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
            "url": canonical, "downloadUrl": f"{url}/claude-desktop.flatpakref",
            "installUrl": f"{url}/claude-desktop.flatpakref", "image": f"{url}/social.png",
            "license": "https://opensource.org/licenses/MIT", "isAccessibleForFree": True,
            "author": {"@type": "Person", "name": "Muhammad Usman", "url": "https://github.com/musmandev092"},
            "sameAs": [REPO], "dateModified": today,
        }]
        faq = [(q, a) for q, a in FAQ]
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]})
        crumbs = ""
        hero = (f'<header class="hero"><img src="icon.png" alt="Claude icon" width="64" height="64">'
                f'<div><h1>{html.escape(h1)}</h1><p class="tag">Unofficial Flatpak · Fedora, Silverblue, Arch, '
                f'openSUSE &amp; any distro · Claude {html.escape(version)}</p></div></header>')
    metas = "".join(
        f'<meta name="{n}" content="{html.escape(v)}">\n'
        for n, v in (("google-site-verification", verify.get("google")), ("msvalidate.01", verify.get("bing")),
                     ("yandex-verification", verify.get("yandex"))) if v and not slug)
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>\n' for x in ld)
    body = body.replace("@URL@", url).replace("@VERSION@", html.escape(version))
    body = body.replace("@FAQ@", "".join(
        f"<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>\n" for q, a in FAQ))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="strict-origin-when-cross-origin">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{canonical}">
<meta name="robots" content="index,follow,max-image-preview:large">
{metas}<link rel="icon" href="{root}icon.png" type="image/png">
<link rel="stylesheet" href="{root}style.css">
<link rel="alternate" type="text/plain" href="{url}/llms.txt" title="llms.txt">
<meta property="og:type" content="{"article" if slug else "website"}">
<meta property="og:site_name" content="Claude Desktop for Linux">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{url}/social.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Claude Desktop for Linux – Flatpak for every distro">
<meta name="twitter:card" content="summary_large_image">
{ld_html}</head>
<body>
<nav class="top" aria-label="Guides"><ul>{nav}</ul></nav>
<main>
{crumbs}
{hero}
{body}
<footer>
<p>This is an unofficial community project. It is not affiliated with, endorsed by, or supported by
Anthropic. “Claude” is a trademark of Anthropic, PBC. The Claude app is subject to Anthropic's terms.
Packaging built with the help of an AI assistant.</p>
<p><a href="{REPO}">Source code (MIT)</a> · <a href="{REPO}/issues">Report a problem</a> ·
<a href="{REPO}/releases">Releases</a> · Updated {today}</p>
</footer>
</main>
</body>
</html>
"""


FAQ = [
    ("Is Claude Desktop available for Linux?",
     "Anthropic publishes a Linux beta of Claude Desktop only as a .deb for Ubuntu and Debian. This unofficial "
     "Flatpak runs that same official build on Fedora, Fedora Silverblue, Arch, openSUSE and any other x86_64 "
     "distribution with Flatpak."),
    ("Is this the official Claude app?",
     "The app is Anthropic's official build: Flatpak downloads it from downloads.claude.ai when you install and "
     "checks its SHA-256 checksum. The packaging around it is an unofficial community project and is not "
     "affiliated with Anthropic."),
    ("Is the Claude app modified?",
     "Only for Cowork: two file paths are changed so Cowork finds its virtual machine tools inside the Flatpak. "
     "The original is kept, and setting COWORK=off runs Claude completely unmodified."),
    ("Do Claude Code and MCP plugins work?",
     "Yes. Claude Code and every local MCP server (npx, uvx, docker, podman, python) run with your real tools – "
     "on the host, or inside a toolbox on Silverblue, Kinoite or Bazzite."),
    ("Does Cowork work on Linux?",
     "Yes. By default Cowork uses Anthropic's cloud virtual machine. You can also run the Cowork VM locally with "
     "KVM by setting COWORK_LOCAL=on."),
    ("How do updates work?",
     "A GitHub Action checks Anthropic's repository every hour, builds and tests each new version, and publishes "
     "it to a GPG-signed Flatpak repository. You get it with flatpak update or GNOME Software / KDE Discover."),
    ("Which computers are supported?",
     "x86_64 Linux with Flatpak, on Wayland or X11. Cowork's local VM also needs hardware virtualisation (KVM)."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--gpgkey", default="")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    a = ap.parse_args()
    url = a.url.rstrip("/")
    verify = {"google": os.environ.get("GOOGLE_SITE_VERIFICATION", "").strip(),
              "bing": os.environ.get("BING_SITE_VERIFICATION", "").strip(),
              "yandex": os.environ.get("YANDEX_VERIFICATION", "").strip()}
    os.makedirs(a.out, exist_ok=True)

    for slug, label, title, desc, h1 in PAGES:
        with open(os.path.join(HERE, "pages", (slug or "index") + ".html"), encoding="utf-8") as f:
            body = f.read()
        out = os.path.join(a.out, slug) if slug else a.out
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
            f.write(page(slug, label, title, desc, h1, body, url, a.version, a.date, verify))

    with open(os.path.join(a.out, "404.html"), "w", encoding="utf-8") as f:
        f.write(page("404", "Not found", "Page not found – Claude Desktop for Linux",
                     "This page does not exist.", "Page not found",
                     f'<p>That page does not exist. Start at the <a href="{url}/">Claude Desktop for Linux</a> page.</p>',
                     url, a.version, a.date, {}, root=url + "/").replace('content="index,follow,max-image-preview:large"',
                                                         'content="noindex"'))

    urls = [f"{url}/{s + '/' if s else ''}" for s, *_ in PAGES]
    with open(os.path.join(a.out, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in urls:
            f.write(f"  <url><loc>{u}</loc><lastmod>{a.date}</lastmod></url>\n")
        f.write("</urlset>\n")
    # (search engines read robots.txt only at the domain root, so on a GitHub
    # project site this is informational; submit the sitemap in the consoles)
    with open(os.path.join(a.out, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nDisallow: /repo/\n\nSitemap: {url}/sitemap.xml\n")
    with open(os.path.join(a.out, f"{INDEXNOW_KEY}.txt"), "w") as f:
        f.write(INDEXNOW_KEY)
    with open(os.path.join(a.out, "indexnow-urls.txt"), "w") as f:     # read by the workflow
        f.write("\n".join(urls) + "\n")

    with open(os.path.join(a.out, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(f"""# Claude Desktop for Linux (unofficial Flatpak)

> An open-source Flatpak that installs Anthropic's official Claude Desktop app (Linux beta, shipped
> by Anthropic only as a .deb for Ubuntu/Debian) on Fedora, Fedora Silverblue/Kinoite/Bazzite/Bluefin,
> Arch, openSUSE and any x86_64 Linux. Claude Code, local MCP servers and Cowork work; updates are
> automatic. Not affiliated with Anthropic. Current Claude version: {a.version}.

Install: `flatpak install --user {url}/claude-desktop.flatpakref`
App ID: {APP_ID}
Source: {REPO} (MIT)

## Guides
""" + "".join(f"- [{t}]({u}): {d}\n" for (s, l, t, d, h), u in zip(PAGES, urls)) + """
## Key facts
""" + "".join(f"- {q} {ans}\n" for q, ans in FAQ))

    for name, text in (("claude-desktop.flatpakref", None), ("claude-desktop.flatpakrepo", None)):
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            text = f.read()
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            f.write(text.replace("@URL@", url).replace("@GPGKEY@", a.gpgkey))
    for static in ("style.css", "social.png"):
        shutil.copy(os.path.join(HERE, static), a.out)
    # search engine ownership files (Google, Bing, Yandex) go to the site root as they are
    for name in os.listdir(HERE):
        if VERIFY_FILE.fullmatch(name):
            shutil.copy(os.path.join(HERE, name), a.out)
    print(f"built {len(PAGES)} pages into {a.out}")


if __name__ == "__main__":
    main()
