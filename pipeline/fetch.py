"""글로벌 논문 일일 수집·선별·한국어 요약 파이프라인.

단계
 1) 수집 : OpenAlex(전 분야·전 언어 저널/프리프린트) + arXiv RSS + bioRxiv/medRxiv + Hugging Face Daily Papers
 2) 1차 선별 : Gemini 로 제목 일괄 평가 (섹터 분류 + 중요도 1~10)
 3) 2차 요약 : 섹터별 상위 N 편을 한국어 번역·개조식 요약
 4) 저장 : site/data/YYYY-MM-DD.json + site/data/index.json
환경 변수 : GEMINI_API_KEY (필수), OPENALEX_API_KEY (선택), PER_SECTOR (기본 8)
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "PaperWire/1.0 (mailto:a01092796847@gmail.com)"}

SECTORS = {
    "ai": "AI·컴퓨팅",
    "robotics": "로보틱스·자율주행",
    "semi": "반도체·전자",
    "energy": "에너지·배터리",
    "materials": "소재·화학",
    "mobility": "모빌리티·기계·제조",
    "bio": "바이오·제약",
    "medical": "의학·헬스케어",
    "physics": "물리·우주·양자",
    "climate": "기후·환경·농식품",
    "econ": "경제·금융",
    "social": "사회과학·정책",
    "math": "수학·통계",
}

ARXIV_CATS = [
    "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.RO", "cs.CR", "cs.AR", "cs.DC",
    "eess.SY", "eess.SP", "cond-mat.mtrl-sci", "physics.app-ph", "quant-ph",
    "astro-ph", "q-fin", "econ", "q-bio", "stat.ML", "math.OC",
]

PER_SECTOR = int(os.getenv("PER_SECTOR", "8"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "2400"))
GEMINI_MODELS = [m for m in os.getenv(
    "GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-2.5-flash-lite,gemini-flash-lite-latest").split(",") if m]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def get(url: str, timeout: int = 60, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (i + 1))
    raise last  # type: ignore[misc]


def clean(t: str | None) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    return re.sub(r"\s+", " ", t).strip()


def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", (t or "").lower())[:120]


# ───────────────────────── 1. 수집 ─────────────────────────

def from_openalex(day: dt.date) -> list[dict]:
    key = os.getenv("OPENALEX_API_KEY", "").strip()
    base = "https://api.openalex.org/works"
    start = (day - dt.timedelta(days=1)).isoformat()
    fields = json.loads(get(f"{base.replace('works', 'fields')}?per_page=50&select=id,display_name"
                            + (f"&api_key={key}" if key else "")))["results"]
    out = []
    for f in fields:
        fid = f["id"].rsplit("/", 1)[-1]
        common = (f"from_publication_date:{start},to_publication_date:{day.isoformat()},"
                  f"has_abstract:true,type:article|preprint|review,primary_topic.field.id:{fid}")
        rows = []
        # 우선 CWTS 핵심 학술지(is_core) 한정 → 결과가 적으면 전체로 확장
        for extra in (",primary_location.source.is_core:true", ""):
            params = {"filter": common + extra, "per_page": "60",
                      "select": "id,doi,title,abstract_inverted_index,language,publication_date,"
                                "primary_location,authorships,primary_topic,type,cited_by_count"}
            if key:
                params["api_key"] = key
            try:
                res = json.loads(get(base + "?" + urllib.parse.urlencode(params)))
                rows += res.get("results", [])
            except Exception as e:  # noqa: BLE001
                log("openalex 실패", fid, e)
                time.sleep(5)
                continue
            if len(rows) >= 30:
                break
        for w in rows:
            inv = w.get("abstract_inverted_index") or {}
            pos = sorted((p, word) for word, ps in inv.items() for p in ps)
            abstract = " ".join(word for _, word in pos)
            loc = w.get("primary_location") or {}
            src = (loc.get("source") or {})
            out.append({
                "id": w["id"].rsplit("/", 1)[-1],
                "title": clean(w.get("title")),
                "abstract": clean(abstract)[:2200],
                "lang": w.get("language") or "",
                "date": w.get("publication_date"),
                "venue": src.get("display_name") or "",
                "core": bool(src.get("is_core")),
                "authors": [a["author"]["display_name"] for a in (w.get("authorships") or [])[:6]],
                "url": w.get("doi") or loc.get("landing_page_url") or w["id"],
                "field_hint": f.get("display_name"),
                "source": "OpenAlex",
            })
        log(f"openalex {f['display_name']}: {len(rows)}")
        time.sleep(1)
    return out


def from_arxiv() -> list[dict]:
    out = []
    for cat in ARXIV_CATS:
        try:
            root = ET.fromstring(get(f"https://rss.arxiv.org/rss/{cat}"))
        except Exception as e:  # noqa: BLE001
            log("arxiv 실패", cat, e)
            continue
        n = 0
        for it in root.iter("item"):
            atype = it.findtext("{http://arxiv.org/schemas/atom}announce_type") or ""
            if atype not in ("new",):
                continue
            desc = it.findtext("description") or ""
            abstract = desc.split("Abstract:", 1)[-1]
            link = it.findtext("link") or ""
            out.append({
                "id": "arxiv:" + link.rsplit("/", 1)[-1],
                "title": clean(it.findtext("title")),
                "abstract": clean(abstract)[:2200],
                "lang": "en",
                "date": None,
                "venue": f"arXiv ({cat})",
                "core": False,
                "authors": [a.strip() for a in (it.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").split(",")][:6],
                "url": link,
                "field_hint": cat,
                "source": "arXiv",
            })
            n += 1
        log(f"arxiv {cat}: {n}")
        time.sleep(1)
    return out


def from_biorxiv(day: dt.date) -> list[dict]:
    out = []
    start = (day - dt.timedelta(days=1)).isoformat()
    for server in ("biorxiv", "medrxiv"):
        cursor = 0
        while cursor < 600:
            try:
                d = json.loads(get(f"https://api.biorxiv.org/details/{server}/{start}/{day.isoformat()}/{cursor}"))
            except Exception as e:  # noqa: BLE001
                log(server, "실패", e)
                break
            col = d.get("collection") or []
            for p in col:
                if str(p.get("version")) != "1":
                    continue
                out.append({
                    "id": f"{server}:{p['doi']}",
                    "title": clean(p.get("title")),
                    "abstract": clean(p.get("abstract"))[:2200],
                    "lang": "en",
                    "date": p.get("date"),
                    "venue": f"{server} ({p.get('category', '')})",
                    "core": False,
                    "authors": [a.strip() for a in (p.get("authors") or "").split(";")][:6],
                    "url": f"https://doi.org/{p['doi']}",
                    "field_hint": p.get("category"),
                    "source": server,
                })
            if len(col) < 100:
                break
            cursor += 100
        log(f"{server}: 누적 {len(out)}")
    return out


def hf_trending() -> dict[str, int]:
    try:
        d = json.loads(get("https://huggingface.co/api/daily_papers?limit=100"))
    except Exception as e:  # noqa: BLE001
        log("HF 실패", e)
        return {}
    return {p["paper"]["id"]: int(p["paper"].get("upvotes") or 0) for p in d}


# ───────────────────────── 2·3. Gemini ─────────────────────────

def gemini(prompt: str, schema: dict | None = None, temperature: float = 0.2) -> object:
    key = os.environ["GEMINI_API_KEY"].strip()
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    if schema:
        body["generationConfig"]["responseSchema"] = schema
    last = None
    for attempt in range(6):
        model = GEMINI_MODELS[min(attempt // 2, len(GEMINI_MODELS) - 1)]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            text = d["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        except urllib.error.HTTPError as e:
            last = f"{model} HTTP {e.code}: {e.read()[:200]!r}"
            time.sleep(20 if e.code == 429 else 5)
        except Exception as e:  # noqa: BLE001
            last = f"{model} {e}"
            time.sleep(5)
    raise RuntimeError(last)


SECTOR_KEYS = list(SECTORS)

TRIAGE_PROMPT = """너는 글로벌 연구 동향 편집장이다. 아래 논문 목록(번호|제목|출처)을 보고 각 논문을
(1) 섹터 1개로 분류하고 (2) 중요도를 1~10 정수로 평가하라.
섹터 코드: {sectors}
중요도 기준: 새로운 발견·기술 돌파(4점) + 산업·투자 파급력(3점) + 일반 독자 관심도(3점). 점진적 개선·사례 보고·지역 한정 연구는 낮게.
반드시 모든 번호를 빠짐없이 JSON 배열로 반환: [{{"i":번호,"s":"섹터코드","v":점수}}]

{items}"""

SUMMARY_PROMPT = """너는 한국 산업·투자 실무자를 위한 연구 동향 리포터다. 아래 논문 각각을 한국어로 정리하라.
원문 언어가 무엇이든(영어·중국어·일본어·독일어 등) 모두 한국어로 번역한다.
작성 규칙
- 공식 문어체 개조식, 명사형 종결(~함, ~임, ~확인). 구어체 금지.
- title_ko : 원제의 정확한 한국어 번역 (고유 명칭·모델명·약어는 원어 유지)
- headline : 무엇을 해서 무엇이 밝혀졌는지 1문장 (40자 내외, 투자 동향 기사 헤드라인처럼)
- points : 3개 [연구 배경·목적, 방법, 핵심 결과(수치가 있으면 반드시 포함)]
- impact : 산업·투자 관점 시사점 1문장. 근거가 없으면 과장 금지
- keywords : 한국어 핵심어 3개
- level : 실용화 단계 "기초연구" | "응용연구" | "실증·임상" 중 1개
초록에 없는 내용을 지어내지 말 것.
JSON 배열로 반환: [{{"i":번호,"title_ko":"","headline":"","points":["","",""],"impact":"","keywords":["","",""],"level":""}}]

{items}"""


def triage(cands: list[dict]) -> None:
    sect = ", ".join(f"{k}={v}" for k, v in SECTORS.items())
    B = 150
    for s in range(0, len(cands), B):
        chunk = cands[s:s + B]
        items = "\n".join(f"{s + j}|{c['title'][:200]}|{c['venue'][:40]}" for j, c in enumerate(chunk))
        try:
            res = gemini(TRIAGE_PROMPT.format(sectors=sect, items=items))
        except Exception as e:  # noqa: BLE001
            log("triage 실패", s, e)
            continue
        for r in res if isinstance(res, list) else []:
            try:
                i = int(r["i"])
                if 0 <= i < len(cands) and r.get("s") in SECTORS:
                    cands[i]["sector"] = r["s"]
                    cands[i]["score"] = int(r.get("v", 0))
            except Exception:  # noqa: BLE001
                pass
        log(f"triage {s + len(chunk)}/{len(cands)}")
        time.sleep(4)


def summarize(picks: list[dict]) -> None:
    B = 6
    for s in range(0, len(picks), B):
        chunk = picks[s:s + B]
        items = "\n\n".join(
            f"[{j}] 원제: {c['title']}\n출처: {c['venue']}\n초록: {c['abstract'][:1800]}"
            for j, c in enumerate(chunk))
        try:
            res = gemini(SUMMARY_PROMPT.format(items=items))
        except Exception as e:  # noqa: BLE001
            log("summary 실패", s, e)
            continue
        for r in res if isinstance(res, list) else []:
            try:
                c = chunk[int(r["i"])]
            except Exception:  # noqa: BLE001
                continue
            for k in ("title_ko", "headline", "points", "impact", "keywords", "level"):
                if r.get(k):
                    c[k] = r[k]
        log(f"summary {s + len(chunk)}/{len(picks)}")
        time.sleep(4)


# ───────────────────────── 4. 실행 ─────────────────────────

def main() -> None:
    day = dt.datetime.now(KST).date()
    if len(sys.argv) > 1:
        day = dt.date.fromisoformat(sys.argv[1])
    log("기준일", day)

    cands: list[dict] = []
    try:
        cands += from_openalex(day)
    except Exception as e:  # noqa: BLE001
        log("openalex 전체 실패", e)
    cands += from_biorxiv(day)
    cands += from_arxiv()

    # 이전 날짜에 이미 게재된 논문 제외
    seen = set()
    for f in sorted(DATA.glob("20*.json"))[-15:]:
        if f.stem == day.isoformat():
            continue  # 같은 날 재실행 시 당일 게재분은 제외 대상에서 뺌
        try:
            for p in json.loads(f.read_text("utf-8"))["papers"]:
                seen.add(norm_title(p["title"]))
        except Exception:  # noqa: BLE001
            pass
    uniq, keys = [], set()
    for c in cands:
        k = norm_title(c["title"])
        if not c["title"] or len(c["abstract"]) < 200 or k in keys or k in seen:
            continue
        keys.add(k)
        uniq.append(c)
    log(f"후보 {len(cands)} → 중복·초록 미비 제외 {len(uniq)}")

    hf = hf_trending()
    for c in uniq:
        aid = c["id"].split(":", 1)[-1].split("v")[0] if c["source"] == "arXiv" else ""
        c["hf_upvotes"] = hf.get(aid, 0)
    # 후보 과다 시 우선순위(HF 화제 > 핵심 학술지 > 비영어권 > 나머지) 유지하며 절단
    uniq.sort(key=lambda c: (-c["hf_upvotes"], not c["core"], c["lang"] == "en"))
    uniq = uniq[:MAX_CANDIDATES]

    triage(uniq)
    picks = []
    for sk in SECTORS:
        pool = [c for c in uniq if c.get("sector") == sk]
        pool.sort(key=lambda c: (-(c.get("score", 0) + min(c["hf_upvotes"], 50) / 10 + (1 if c["core"] else 0))))
        picks += pool[:PER_SECTOR]
    log(f"요약 대상 {len(picks)}")
    summarize(picks)
    picks = [p for p in picks if p.get("headline")]

    papers = []
    for p in picks:
        papers.append({k: p.get(k) for k in (
            "id", "title", "title_ko", "headline", "points", "impact", "keywords", "level",
            "sector", "score", "hf_upvotes", "venue", "core", "authors", "url", "lang", "source", "date")})
    DATA.mkdir(parents=True, exist_ok=True)
    out = {
        "date": day.isoformat(),
        "generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
        "stats": {"collected": len(cands), "screened": len(uniq), "published": len(papers),
                  "by_source": {s: sum(1 for c in cands if c["source"] == s) for s in {c["source"] for c in cands}}},
        "sectors": SECTORS,
        "papers": papers,
    }
    (DATA / f"{day.isoformat()}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    dates = sorted({f.stem for f in DATA.glob("20*.json")}, reverse=True)
    (DATA / "index.json").write_text(json.dumps({"dates": dates, "sectors": SECTORS}, ensure_ascii=False), "utf-8")
    log(f"완료 : {len(papers)}편 게재")
    if not papers:
        sys.exit(1)


if __name__ == "__main__":
    main()
