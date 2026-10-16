"""검색엔진 노출용 정적 산출물 생성.

- site/archive/YYYY-MM-DD.html : 날짜별 정적 기사 페이지 (JS 없이 전문 노출)
- site/index.html             : <!--SSR:START-->~<!--SSR:END--> 구간에 최신 호 요약 사전 렌더링,
                                <!--ARCH:START-->~<!--ARCH:END--> 구간에 지난 호 링크
- site/sitemap.xml, site/rss.xml
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data"
BASE = "https://leetaeyun27.github.io/paperwire/"
NAME = "페이퍼와이어"
KST = dt.timezone(dt.timedelta(hours=9))
COLORS = {"ai": "#2340ff", "robotics": "#ff4a1c", "semi": "#7a3cff", "energy": "#f2a900", "materials": "#00a07a",
          "mobility": "#0b7fd1", "bio": "#d6266b", "medical": "#e8573f", "physics": "#3a2d8c", "climate": "#4f9a2b",
          "econ": "#b07a16", "social": "#8a5a44", "math": "#4a4a4a"}
LABEL = ["배경", "방법", "결과"]

e = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731


def strip(t: str) -> str:
    return re.sub(r"^\s*(연구\s*)?(배경|목적|배경·목적|방법|핵심\s*결과|결과)[^:：]{0,8}[:：]\s*", "", t or "")


def anchor(pid: str) -> str:
    return "p-" + re.sub(r"[^a-zA-Z0-9]+", "-", pid).strip("-").lower()


def kdate(d: str) -> str:
    y, m, dd = d.split("-")
    wd = "월화수목금토일"[dt.date.fromisoformat(d).weekday()]
    return f"{y}. {int(m)}. {int(dd)}. ({wd})"


def load_days() -> list[dict]:
    days = []
    for f in sorted(DATA.glob("20*.json"), reverse=True):
        try:
            days.append(json.loads(f.read_text("utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return days


def describe(day: dict) -> str:
    tops = sorted(day["papers"], key=lambda p: -(p.get("score") or 0))[:3]
    return (f"{kdate(day['date'])} 전 세계 신규 논문 {day['stats'].get('collected', 0):,}편 중 "
            f"{len(day['papers'])}편 한국어 요약. " + " / ".join(p.get("headline", "") for p in tops))[:300]


ARCH_CSS = """
:root{--paper:#f4f1ea;--ink:#121212;--ink2:#3d3a35;--mute:#8b857a;--hair:rgba(18,18,18,.14);--blue:#2340ff;--hot:#ff4a1c}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Noto Sans KR",system-ui,sans-serif;line-height:1.7;word-break:keep-all;overflow-wrap:break-word}
a{color:inherit}.w{max-width:980px;margin:0 auto;padding:0 20px}
header{border-bottom:6px double var(--ink);padding:22px 0 12px}
.logo{font-family:Anton,sans-serif;font-size:clamp(44px,8vw,84px);line-height:.9;text-decoration:none;letter-spacing:-.01em}.logo b{color:var(--blue);font-weight:400}
.meta{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin-top:8px}
h1{font-family:"Noto Serif KR",serif;font-weight:900;font-size:clamp(24px,3.4vw,36px);line-height:1.3;margin:28px 0 6px;text-wrap:balance}
.lede{color:var(--ink2);margin:0 0 10px}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:16px 0 0;padding:0;list-style:none}.toc a{display:inline-block;border:1.5px solid var(--ink);padding:2px 10px;font-size:13px;font-weight:700;text-decoration:none}
.toc a:hover{background:var(--ink);color:var(--paper)}
h2{font-family:"Noto Serif KR",serif;font-weight:900;font-size:26px;margin:44px 0 0;padding-bottom:8px;border-bottom:2px solid var(--ink);display:flex;align-items:center;gap:10px}
h2 i{width:34px;height:8px;display:inline-block}
article{padding:18px 0;border-bottom:1px solid var(--hair)}
article h3{font-family:"Noto Serif KR",serif;font-weight:900;font-size:20px;line-height:1.4;margin:4px 0 4px;text-wrap:balance}
.tag{font-family:"JetBrains Mono",monospace;font-size:11px;color:var(--mute);letter-spacing:.05em}
.ko{margin:0;color:var(--ink2)}.orig{margin:2px 0 0;font-size:13px;font-style:italic;color:var(--mute)}
article ul{margin:10px 0 0;padding:0;list-style:none}article li{display:grid;grid-template-columns:42px 1fr;gap:6px;font-size:14px;margin:4px 0}
article li b{font-size:11px;text-align:center;border:1.5px solid var(--ink);height:22px;line-height:19px}
.imp{margin:10px 0 0;padding:10px 14px;background:var(--ink);color:var(--paper);font-size:14px}
.kw{font-size:12px;color:var(--ink2);margin:8px 0 0}.src{font-size:13px;margin:8px 0 0}.src a{color:var(--blue);font-weight:700}
.nav{display:flex;justify-content:space-between;gap:10px;margin:36px 0;font-weight:700}
.cta{display:inline-block;margin-top:14px;background:var(--blue);color:#fff;text-decoration:none;padding:10px 16px;font-weight:700;box-shadow:4px 4px 0 var(--ink)}
footer{font-size:12px;color:var(--mute);padding:20px 0 60px;border-top:1px solid var(--ink)}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=Anton&family=Noto+Sans+KR:wght@400;700&'
         'family=Noto+Serif+KR:wght@900&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">')


def archive_page(day: dict, prev_d: str | None, next_d: str | None, verify: str) -> str:
    d, S = day["date"], day["sectors"]
    url = f"{BASE}archive/{d}.html"
    title = f"{kdate(d)} 세계 논문 브리핑 — {NAME}"
    desc = describe(day)
    keys = [k for k in S if any(p["sector"] == k for p in day["papers"])]
    items = []
    for i, p in enumerate(day["papers"]):
        items.append({"@type": "ListItem", "position": i + 1, "url": f"{url}#{anchor(p['id'])}",
                      "item": {"@type": "ScholarlyArticle", "headline": p.get("title"), "name": p.get("title_ko"),
                               "abstract": p.get("headline"), "url": p.get("url"),
                               "author": [{"@type": "Person", "name": a} for a in (p.get("authors") or [])[:3] if a]}})
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "description": desc, "url": url,
          "inLanguage": "ko", "datePublished": d, "isPartOf": {"@type": "WebSite", "name": NAME, "url": BASE},
          "mainEntity": {"@type": "ItemList", "itemListElement": items}}
    body = []
    for k in keys:
        ps = sorted([p for p in day["papers"] if p["sector"] == k], key=lambda p: -(p.get("score") or 0))
        body.append(f'<section id="{k}"><h2><i style="background:{COLORS.get(k, "#111")}"></i>{e(S[k])}</h2>')
        for p in ps:
            pts = "".join(f"<li><b>{LABEL[j] if j < 3 else '·'}</b><span>{e(strip(t))}</span></li>"
                          for j, t in enumerate(p.get("points") or []))
            body.append(
                f'<article id="{anchor(p["id"])}"><div class="tag">{e(p.get("venue"))} · {e(p.get("level"))} · AI 중요도 {p.get("score", "-")}/10</div>'
                f'<h3>{e(p.get("headline"))}</h3><p class="ko">{e(p.get("title_ko"))}</p><p class="orig">{e(p.get("title"))}</p>'
                f'<ul>{pts}</ul>' + (f'<p class="imp">시사점 — {e(p.get("impact"))}</p>' if p.get("impact") else "") +
                f'<p class="kw">{" ".join("#" + e(x) for x in (p.get("keywords") or []))}</p>'
                f'<p class="src">저자 {e(", ".join([a for a in (p.get("authors") or [])[:4] if a]))} · '
                f'<a href="{e(p.get("url"))}" rel="noopener" target="_blank">원문 보기</a></p></article>')
        body.append("</section>")
    nav = '<div class="nav">' + (f'<a href="{prev_d}.html">← {kdate(prev_d)} 호</a>' if prev_d else "<span></span>") + \
          (f'<a href="{next_d}.html">{kdate(next_d)} 호 →</a>' if next_d else "<span></span>") + "</div>"
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">{verify}
<meta property="og:type" content="article"><meta property="og:site_name" content="{NAME}"><meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{url}"><meta property="og:image" content="{BASE}og.png">
<meta property="og:locale" content="ko_KR"><meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="{NAME}" href="{BASE}rss.xml">
{FONTS}<style>{ARCH_CSS}</style>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head>
<body><header class="w"><a class="logo" href="../">PAPER<b>WIRE</b></a>
<div class="meta"><span>{NAME} · 세계의 새 논문을 한국어로, 매일 아침</span><span>{kdate(d)} 호</span></div></header>
<main class="w"><h1>{kdate(d)} 오늘의 세계 연구 — 신규 논문 {len(day['papers'])}편 한국어 요약</h1>
<p class="lede">전 세계 신규 논문 {day['stats'].get('collected', 0):,}편을 수집해 AI 1차 검토 {day['stats'].get('screened', 0):,}편 중 섹터별 주요 연구를 선별·번역함.</p>
<ul class="toc">{"".join(f'<li><a href="#{k}">{e(S[k])}</a></li>' for k in keys)}</ul>
<a class="cta" href="../">인터랙티브 1면으로 보기 →</a>
{"".join(body)}{nav}</main>
<footer class="w">수집원 OpenAlex · arXiv · bioRxiv · medRxiv · Hugging Face Daily Papers. 선별·번역·요약은 AI 자동 생성 — 인용 시 원문 확인 필요.</footer>
</body></html>"""


def ssr_block(day: dict) -> str:
    S = day["sectors"]
    out = [f'<div class="ssr wrap"><h2>{kdate(day["date"])} 세계 논문 브리핑</h2><p>{e(describe(day))}</p>']
    for k in S:
        ps = [p for p in day["papers"] if p["sector"] == k]
        if not ps:
            continue
        out.append(f"<h3>{e(S[k])}</h3><ul>")
        for p in ps:
            out.append(f'<li><a href="archive/{day["date"]}.html#{anchor(p["id"])}">{e(p.get("headline"))}</a> — {e(p.get("title_ko"))}</li>')
        out.append("</ul>")
    out.append("</div>")
    return "".join(out)


def main() -> None:
    days = load_days()
    if not days:
        return
    verify_path = ROOT / "pipeline" / "verify.html"
    verify = verify_path.read_text("utf-8").strip() if verify_path.exists() else ""
    (SITE / "archive").mkdir(exist_ok=True)
    dates = [d["date"] for d in days]
    for i, day in enumerate(days):
        prev_d = dates[i + 1] if i + 1 < len(dates) else None
        next_d = dates[i - 1] if i > 0 else None
        (SITE / "archive" / f"{day['date']}.html").write_text(archive_page(day, prev_d, next_d, verify), "utf-8")

    # index.html 사전 렌더링 구간 교체
    idx = SITE / "index.html"
    s = idx.read_text("utf-8")
    s = re.sub(r"<!--SSR:START-->.*?<!--SSR:END-->", "<!--SSR:START-->" + ssr_block(days[0]) + "<!--SSR:END-->", s, flags=re.S)
    arch = "".join(f'<a href="archive/{d}.html">{kdate(d)} 호</a>' for d in dates[:60])
    s = re.sub(r"<!--ARCH:START-->.*?<!--ARCH:END-->", "<!--ARCH:START-->" + arch + "<!--ARCH:END-->", s, flags=re.S)
    s = re.sub(r"<!--VERIFY:START-->.*?<!--VERIFY:END-->", "<!--VERIFY:START-->" + verify + "<!--VERIFY:END-->", s, flags=re.S)
    s = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + e(describe(days[0])) + m.group(2), s, count=1)
    idx.write_text(s, "utf-8")

    # sitemap
    now = dt.datetime.now(KST).date().isoformat()
    urls = [f"<url><loc>{BASE}</loc><lastmod>{dates[0]}</lastmod><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    urls += [f"<url><loc>{BASE}archive/{d}.html</loc><lastmod>{d}</lastmod><changefreq>monthly</changefreq><priority>0.8</priority></url>"
             for d in dates]
    (SITE / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                      + "".join(urls) + "</urlset>\n", "utf-8")

    # RSS (최근 3일, 최대 150건)
    items = []
    for day in days[:3]:
        pub = dt.datetime.fromisoformat(day["date"] + "T10:00:00+09:00").strftime("%a, %d %b %Y %H:%M:%S +0900")
        for p in day["papers"]:
            link = f"{BASE}archive/{day['date']}.html#{anchor(p['id'])}"
            desc = f"[{day['sectors'].get(p['sector'], '')}] {p.get('title_ko', '')} — {p.get('impact', '')}"
            items.append(f"<item><title>{e(p.get('headline'))}</title><link>{e(link)}</link><guid isPermaLink=\"true\">{e(link)}</guid>"
                         f"<description>{e(desc)}</description><category>{e(day['sectors'].get(p['sector'], ''))}</category><pubDate>{pub}</pubDate></item>")
    (SITE / "rss.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{NAME} — 세계 논문 한국어 브리핑</title><link>{BASE}</link>"
        "<description>전 세계 신규 연구 논문을 매일 수집해 한국어로 번역·요약하는 연구 동향 일간지</description>"
        f"<language>ko</language><lastBuildDate>{dt.datetime.now(KST).strftime('%a, %d %b %Y %H:%M:%S +0900')}</lastBuildDate>"
        + "".join(items[:150]) + "</channel></rss>\n", "utf-8")
    print(f"정적 산출물 생성 : 아카이브 {len(dates)}개, 사이트맵·RSS 갱신 ({now})")


if __name__ == "__main__":
    main()
