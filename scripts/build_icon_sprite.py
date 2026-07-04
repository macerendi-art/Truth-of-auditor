"""Bangun sprite Lucide → web/templates/web/_icon_sprite.html.

Jalankan manual saat menambah ikon; hasilnya di-commit — tidak ada build step
runtime. Nama ikon mengikuti https://lucide.dev.
"""
import re
import urllib.request

ICONS = [
    "layout-dashboard", "upload", "list", "git-compare", "users", "store",
    "check", "x", "flag", "chevron-right", "chevron-down", "log-out",
    "circle-alert", "receipt", "landmark", "wallet", "file-text",
    "file-spreadsheet", "file-archive", "download", "calendar-check",
    "sparkles", "rotate-cw", "trash-2", "lock", "search", "arrow-right",
    "folder-open", "triangle-alert", "activity",
]
VER = "0.469.0"

parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">']
for name in ICONS:
    url = f"https://unpkg.com/lucide-static@{VER}/icons/{name}.svg"
    svg = urllib.request.urlopen(url).read().decode()
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1).strip()
    parts.append(
        f'<symbol id="i-{name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{inner}</symbol>'
    )
parts.append("</svg>")
open("web/templates/web/_icon_sprite.html", "w").write("\n".join(parts) + "\n")
print(f"OK — {len(ICONS)} ikon")
