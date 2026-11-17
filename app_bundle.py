#!/usr/bin/env python3
"""Package the built Nexus page (index.html) for the iOS app.

Usage:  python3 app_bundle.py                    write www/ from index.html
        python3 app_bundle.py --page=PATH        bundle a different built page
        python3 app_bundle.py --cytoscape=PATH   use this cytoscape.min.js instead of node_modules

The web version loads Cytoscape and its fonts from CDNs. The app should open with no network
and make no third-party requests (that keeps the App Store privacy label at "Data Not
Collected"), so this script copies everything into www/:

  www/index.html          the page, with Cytoscape and the fonts pointed at local copies
  www/cytoscape.min.js    from node_modules (npm install), or downloaded from cdnjs
  www/fonts/              the Google Fonts the page uses, downloaded once here
  www/icons/, manifest    copied as-is

It also points the PROJECT520 header link at https://projectfivetwenty.com/ (the app has no
"/" to go to; Capacitor opens outside links in Safari), and, once `npx cap add ios` has created
the Xcode project, copies icons/icon-1024.png in as the app icon.

Run it after every `python3 build.py`, then `npx cap sync ios` (npm run app:sync does both).
"""
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
WWW = ROOT / "www"
SITE = "https://projectfivetwenty.com/"
CDN_CYTOSCAPE = re.compile(r'<script src="(https://cdnjs\.cloudflare\.com/ajax/libs/cytoscape/[^"]+/cytoscape\.min\.js)"></script>')
FONT_LINK = re.compile(r'<link rel="stylesheet" href="(https://fonts\.googleapis\.com/css2\?[^"]+)">')
PRECONNECT = re.compile(r'<link rel="preconnect" href="https://fonts\.(googleapis|gstatic)\.com"( crossorigin)?>\n?')
# Google serves woff2 only to browsers it recognises.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
APPICON_DIR = ROOT / "ios" / "App" / "App" / "Assets.xcassets" / "AppIcon.appiconset"


def arg_value(name):
    for a in sys.argv[1:]:
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def bundle_cytoscape(html, warnings):
    m = CDN_CYTOSCAPE.search(html)
    if not m:
        warnings.append("no cdnjs Cytoscape <script> found; left the page's script tag alone")
        return html
    dest = WWW / "cytoscape.min.js"
    local = Path(arg_value("--cytoscape") or ROOT / "node_modules" / "cytoscape" / "dist" / "cytoscape.min.js")
    if local.exists():
        shutil.copyfile(local, dest)
    else:
        try:
            dest.write_bytes(fetch(m.group(1)))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"could not get Cytoscape ({e}); run `npm install` and try again. The app will need a network connection until then.")
            return html
    return html.replace(m.group(0), '<script src="cytoscape.min.js"></script>')


def bundle_fonts(html, warnings):
    m = FONT_LINK.search(html)
    if not m:
        return html
    try:
        css = fetch(m.group(1).replace("&amp;", "&")).decode("utf-8")
        fonts = WWW / "fonts"
        fonts.mkdir(exist_ok=True)
        urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css)))
        for i, url in enumerate(urls):
            name = f"f{i:02d}{Path(url.split('?')[0]).suffix or '.woff2'}"
            (fonts / name).write_bytes(fetch(url))
            css = css.replace(url, name)
        (fonts / "fonts.css").write_text(css, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"could not download the fonts ({e}); the app will use Google Fonts online and system fonts offline.")
        return html
    html = PRECONNECT.sub("", html)
    return html.replace(m.group(0), '<link rel="stylesheet" href="fonts/fonts.css">')


def install_app_icon(warnings):
    src = ROOT / "icons" / "icon-1024.png"
    contents = APPICON_DIR / "Contents.json"
    if not contents.exists():
        return "skipped (run `npx cap add ios` first, then run this again)"
    try:
        meta = json.loads(contents.read_text(encoding="utf-8"))
        names = [img.get("filename") for img in meta.get("images", []) if img.get("size") == "1024x1024" and img.get("filename")]
    except ValueError:
        names = []
    if not names:
        warnings.append(f"could not find the 1024x1024 slot in {contents}; set the app icon in Xcode by hand")
        return "skipped"
    for n in names:
        shutil.copyfile(src, APPICON_DIR / n)
    return f"installed as {', '.join(names)}"


def main():
    page = Path(arg_value("--page") or ROOT / "index.html")
    if not page.exists():
        sys.exit(f"{page} not found. Build the page first: python3 build.py --out=index.html")
    html = page.read_text(encoding="utf-8")
    if 'name="viewport"' not in html:
        sys.exit(f"{page} has no viewport tag; it was built from an old template. Rebuild it with python3 build.py.")

    if WWW.exists():
        shutil.rmtree(WWW)
    WWW.mkdir()
    warnings = []

    html = bundle_cytoscape(html, warnings)
    html = bundle_fonts(html, warnings)
    html = html.replace('<a href="/" title="Project 520 home">', f'<a href="{SITE}" title="Project 520 home">')

    (WWW / "index.html").write_text(html, encoding="utf-8")
    shutil.copytree(ROOT / "icons", WWW / "icons")
    shutil.copyfile(ROOT / "manifest.webmanifest", WWW / "manifest.webmanifest")
    icon = install_app_icon(warnings)

    size = sum(f.stat().st_size for f in WWW.rglob("*") if f.is_file())
    print(f"wrote {WWW.relative_to(ROOT)}/ ({size / 1e6:.1f} MB); app icon: {icon}")
    for w in warnings:
        print("warning:", w)


if __name__ == "__main__":
    main()
