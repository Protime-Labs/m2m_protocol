"""
Build a self-contained single-file version of the dashboard for publishing as a
Claude Artifact (data inlined; no <!doctype>/<html>/<head>/<body> wrapper, which
the Artifact host supplies).

    python build_artifact.py      # writes dashboard/aata-dashboard.html
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "dashboard")

html = open(os.path.join(DASH, "index.html"), encoding="utf-8").read()
data = open(os.path.join(DASH, "data.js"), encoding="utf-8").read()

style = re.search(r"<style>.*?</style>", html, re.S).group(0)
body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)

# split body markup from the trailing app <script>
cut = body.rfind("<script>")
markup = body[:cut].strip()
app = re.search(r"<script>(.*)</script>", body[cut:], re.S).group(1)

out = (
    "<title>AATA Trust Overlay Console</title>\n" +
    style + "\n" +
    markup + "\n" +
    "<script>\n" + data + "</script>\n" +
    "<script>\n" + app + "\n</script>\n"
)

dst = os.path.join(DASH, "aata-dashboard.html")
open(dst, "w", encoding="utf-8").write(out)
print(f"wrote {dst} ({len(out):,} bytes)")
