# -*- coding: utf-8 -*-
"""사이트 간 같은 공고(재게시) 묶기

예) KOTRA '미국 관세정책 대응 심층컨설팅 지원' = 기업마당 '미국 관세정책 대응 심층컨설팅 지원사업 공고'
    → 첨부 안내문이 같고(hwpx·pdf 형식만 다름) 접수기간도 같음 → 한 건으로 추천

판단 근거 (서로 다른 사이트의 접수중 공고끼리만 비교)
  ① 첨부 공고문 본문이 거의 같음 (글자 3-gram 유사도)       ← 가장 강한 근거
  ② 첨부파일 이름(확장자 제외)이 같음
  ③ 제목이 거의 같음 (상투어 '모집 공고' 등 제거 후)
  + 접수 마감일이 같거나 한쪽이 비어 있음
대표 공고는 출처 우선순위(ax_sources.ORDER: 수출e음 → 전북 → aT → KOTRA → 기업마당)로 정하고,
나머지는 notices.dup_of 에 대표 공고번호를 기록합니다. 추천·알림은 대표 공고만 사용하고, 화면에는 '다른 게시처'로 함께 표시합니다.
"""
from __future__ import annotations

import json
import re

import ax_sources

DOC_SIM = 0.55        # 첨부 본문 유사도
TITLE_SIM = 0.86      # 제목 유사도 (첨부가 없을 때)
TITLE_DOC_SIM = (0.6, 0.3)


def _grams(s: str, n: int) -> set:
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def _dice(a: set, b: set) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _stem(name: str) -> str:
    s = re.sub(r"\.\w{2,5}$", "", name or "")
    s = re.sub(r"20\d{2}\s*년?", "", s)
    s = re.sub(r"[^가-힣A-Za-z0-9]", "", s.replace("+", " ")).lower()
    return s if len(s) >= 6 else ""


def fingerprint(con, n: dict) -> dict:
    rows = con.execute("SELECT file_name, text FROM documents WHERE project_no=?", (n["project_no"],)).fetchall()
    docs = [r[1] or "" for r in rows if not (r[0] or "").lower().endswith((".xlsx", ".xlsm", ".xls"))]
    body = re.sub(r"\s+", "", "\n".join(docs))[:4000]
    atts = json.loads(n.get("attachments_json") or "[]") if isinstance(n.get("attachments_json"), str) else (n.get("attachments") or [])
    names = {_stem(a.get("name", "")) for a in atts} | {_stem(r[0]) for r in rows}
    return {"pn": n["project_no"], "src": ax_sources.source_of(n["project_no"]), "end": (n.get("receipt_end") or "")[:10],
            "title": _grams(ax_sources._norm_title(n.get("title", "")), 2), "doc": _grams(body, 3) if len(body) >= 150 else set(),
            "att": {x for x in names if x}, "first": n.get("first_seen") or "",
            "regions": set((json.loads(n.get("target_json") or "{}") or {}).get("regions") or [])}


def same_notice(a: dict, b: dict) -> tuple[float, str]:
    """같은 공고로 볼 근거가 있으면 (확신도 0~1, 사유), 아니면 (0, '')"""
    if a["src"] == b["src"]:
        return 0, ""
    if a["end"] and b["end"] and a["end"] != b["end"]:
        return 0, ""
    if a["regions"] and b["regions"] and not (a["regions"] & b["regions"]):
        return 0, ""                                   # 지역이 다른 같은 이름 사업 (예: 강원형·경남형)
    ds, ts = _jac(a["doc"], b["doc"]), _dice(a["title"], b["title"])
    if ds >= DOC_SIM:
        return 0.5 + ds / 2, f"첨부 공고문 본문 일치({ds:.0%})"
    if a["att"] & b["att"] and ts >= 0.5:
        return 0.7 + ts / 4, "첨부파일 이름 일치"
    if bool(a["regions"]) != bool(b["regions"]):
        return 0, ""        # 본문 근거 없이 한쪽만 지역 사업이면 다른 공고 (예: [천안·아산] 설명회 ↔ 전북 설명회)
    if ts >= TITLE_SIM and (a["end"] or b["end"]):
        return 0.4 + ts / 2, f"제목 일치({ts:.0%})"
    if ts >= TITLE_DOC_SIM[0] and ds >= TITLE_DOC_SIM[1]:
        return 0.3 + (ts + ds) / 4, f"제목·본문 유사({ts:.0%}/{ds:.0%})"
    return 0, ""


def ensure_column(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(notices)")}
    if "dup_of" not in cols:
        con.execute("ALTER TABLE notices ADD COLUMN dup_of TEXT")
    if "dup_reason" not in cols:
        con.execute("ALTER TABLE notices ADD COLUMN dup_reason TEXT")


def mark_duplicates(con, log=None) -> list[tuple]:
    """접수중 공고 전체를 비교해 notices.dup_of 갱신. 반환: [(중복, 대표, 사유)]"""
    ensure_column(con)
    rows = [dict(r) for r in con.execute("SELECT * FROM notices WHERE status LIKE '%접수중%'")]
    order = {k: i for i, k in enumerate(ax_sources.ORDER)}
    fps = sorted((fingerprint(con, r) for r in rows), key=lambda f: (order.get(f["src"], 99), f["first"], f["pn"]))
    # 후보 쌍을 확신도 순으로 묶되, 한 대표 공고는 사이트마다 1건만 흡수 (한 사이트에 같은 공고가 두 번 올라오진 않음)
    cand = []
    for i, b in enumerate(fps):
        for a in fps[:i]:
            sc, why = same_notice(a, b)
            if sc:
                cand.append((sc, a["pn"], b["pn"], b["src"], why))
    cand.sort(key=lambda c: -c[0])
    rep, absorbed = {}, {}          # rep: 중복 pn -> (대표 pn, 사유) / absorbed: 대표 pn -> {출처}
    for sc, a, b, bsrc, why in cand:
        if b in rep or a in rep or b in absorbed or bsrc in absorbed.get(a, set()):
            continue
        rep[b] = (a, why)
        absorbed.setdefault(a, set()).add(bsrc)
    con.execute("UPDATE notices SET dup_of=NULL, dup_reason=NULL")
    for pn, (to, why) in rep.items():
        con.execute("UPDATE notices SET dup_of=?, dup_reason=? WHERE project_no=?", (to, why, pn))
    con.commit()
    out = [(pn, to, why) for pn, (to, why) in rep.items()]
    if log and out:
        log(f"  - 사이트 간 같은 공고 {len(out)}건을 대표 공고로 묶음")
    return out


if __name__ == "__main__":
    import sys
    import ax_db
    for s in (sys.stdout,):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    con = ax_db.connect()
    t = {r["project_no"]: r["title"] for r in con.execute("SELECT project_no, title FROM notices")}
    for pn, to, why in mark_duplicates(con):
        print(f"{why:24s} {pn} {t[pn][:40]}\n{'':24s} → {to} {t[to][:40]}")
