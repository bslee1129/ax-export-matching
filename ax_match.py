# -*- coding: utf-8 -*-
"""③ 맞춤형 매칭 엔진 (규칙 기반 적합도 점수 0~100, 모든 판단에 근거 문장 첨부)

점수 구성
  지원분야 일치 40 · 업종 20 · 지역 10 · 희망국가 10 · 신청기한 10 · 수출단계/실적 10 (+우선지원 가점 5)
부적합(✗) 판정
  마감 / 지역 불일치 / 상장기업 제외 / 기업규모 불일치 / 업종 불일치 / 직수출 요건 미충족
"""
from __future__ import annotations

import datetime as dt
import re

import ax_meta

SIZES = ["소기업·소상공인", "중소기업", "중견기업", "대기업"]
INDUSTRY_COMPAT = {"농산": {"농산", "식품"}, "수산": {"수산", "식품"}, "식품": {"식품"},
                   "공산품": {"공산품"}, "기타": set()}
COUNTRY_GROUP = {
    "중동": ["중동", "UAE", "사우디", "카타르", "쿠웨이트", "이스라엘", "튀르키예", "터키", "이란", "이라크", "오만", "바레인", "요르단"],
    "동남아": ["동남아", "베트남", "태국", "인도네시아", "말레이시아", "필리핀", "싱가포르", "캄보디아", "미얀마"],
    "미주": ["미주", "미국", "캐나다", "멕시코", "브라질", "칠레"],
    "유럽": ["유럽", "독일", "프랑스", "영국", "네덜란드", "이탈리아", "스페인", "폴란드"],
    "중화권": ["중화권", "중국", "대만", "홍콩"],
    "일본": ["일본", "나고야", "도쿄", "오사카"],
}


def _country_groups(text: str) -> set:
    out = set()
    for g, words in COUNTRY_GROUP.items():
        if any(w in (text or "") for w in words):
            out.add(g)
    return out


def _dday(end: str | None, today: dt.date) -> int | None:
    if not end:
        return None
    try:
        return (dt.date.fromisoformat(end[:10]) - today).days
    except ValueError:
        return None


def _amount_text(a: dict) -> str:
    if not a or not a.get("max_manwon"):
        return "공고문 참조"
    v = a["max_manwon"]
    s = f"최대 {v/100:,.0f}백만원" if v >= 1000 else f"최대 {v:,.0f}만원"
    if a.get("special_max_manwon"):
        sv = a["special_max_manwon"]
        s += f" (특례 {sv/100:,.0f}백만원)" if sv >= 1000 else f" (특례 {sv:,.0f}만원)"
    if a.get("rate"):
        s += f" · {a['rate']}% 이내"
    return s


def score_notice(p: dict, n: dict, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    t = n.get("target") or {}
    fields = [f["field"] for f in (n.get("fields") or [])]
    reasons, fails, warns = [], [], []
    score = 0

    def plus(pts, text, ev=""):
        nonlocal score
        score += pts
        reasons.append({"type": "+", "points": pts, "text": text, "evidence": ev})

    # ── 부적합(하드 조건)
    d = _dday(n.get("receipt_end"), today)
    if "접수중" not in (n.get("status") or "") or (d is not None and d < 0):
        fails.append({"text": f"접수 마감 ({n.get('receipt_end') or n.get('status')})", "evidence": ""})
    regions = t.get("regions") or []
    if regions and p.get("region") and p["region"] not in regions:
        fails.append({"text": f"지역 요건 불일치 (공고: {'·'.join(regions)} / 기업: {p['region']})",
                      "evidence": next((r["evidence"] for r in t.get("requires", []) if "본사" in r["rule"]), "")})
    for ex in t.get("excludes", []):
        if "상장" in ex["rule"] and p.get("listed"):
            fails.append({"text": "상장기업은 지원 제외", "evidence": ex["evidence"]})
    distributor = "해외 유통매장 운영사" in (t.get("company_types") or [])
    if "중소기업" in (t.get("company_types") or []) and not distributor and p.get("size") in ("중견기업", "대기업"):
        fails.append({"text": f"중소기업 대상 사업 (기업규모: {p.get('size')})", "evidence": " / ".join(t.get("text", [])[:1])})
    for rq in t.get("requires", []):
        if "직수출" in rq["rule"] and p.get("direct_export") is False:
            fails.append({"text": "직수출 기업만 지원 (현재 간접수출)", "evidence": rq["evidence"]})
    n_ind = set(t.get("industries") or [])
    p_ind = set(p.get("industries") or [])
    if n_ind and p_ind:
        compat = set().union(*(INDUSTRY_COMPAT.get(x, {x}) for x in p_ind))
        if not (compat & n_ind):
            fails.append({"text": f"업종 불일치 (공고: {'·'.join(sorted(n_ind))} / 기업: {'·'.join(sorted(p_ind))})",
                          "evidence": " / ".join(t.get("text", [])[:1])})
    distributor_only = distributor
    if distributor_only and not p.get("is_overseas_distributor"):
        warns.append({"text": "직접 신청 대상은 '해외 유통매장 운영사' — 국내 수출기업은 컨소시엄(입점기업)으로 참여 검토",
                      "evidence": " / ".join(t.get("text", [])[:1])})

    # ── 적합도 점수
    needs = set(p.get("needs") or [])
    if needs:
        hit = [f for f in fields if f in needs]
        if hit and fields and hit[0] == fields[0]:
            plus(40, f"필요 분야 일치: {', '.join(hit)}", (n["fields"][0].get("evidence") or [""])[0])
        elif hit:
            plus(28, f"필요 분야 일부 일치: {', '.join(hit)}",
                 next((f.get("evidence", [""])[0] for f in n["fields"] if f["field"] in hit and f.get("evidence")), ""))
        else:
            reasons.append({"type": "-", "points": 0, "text": f"필요 분야와 다름 (공고 분야: {', '.join(fields) or '미분류'})", "evidence": ""})
    else:
        plus(20, "필요 분야 미입력 — 기본 점수", "")

    if n_ind and p_ind and not any("업종" in f["text"] for f in fails):
        plus(20, f"업종 일치: {'·'.join(sorted(n_ind))}", " / ".join(t.get("text", [])[:1]))
    elif not n_ind:
        plus(12, "업종 제한 없음", "")

    if regions and p.get("region") in regions:
        plus(10, f"지역 요건 충족 ({p['region']})", next((r["evidence"] for r in t.get("requires", []) if "본사" in r["rule"]), ""))
    elif not regions:
        plus(6, "지역 제한 명시 없음", "")

    p_groups = _country_groups(p.get("target_countries", ""))
    n_groups = _country_groups(" ".join(t.get("countries", [])) + " " + n.get("title", ""))
    if p_groups and n_groups and p_groups & n_groups:
        plus(10, f"희망 수출국 일치: {', '.join(sorted(p_groups & n_groups))}", n.get("title", ""))
    elif not n_groups:
        plus(5, "국가 제한 없음", "")
    else:
        reasons.append({"type": "-", "points": 0, "text": f"공고 대상 국가: {', '.join(sorted(n_groups))}", "evidence": ""})
    sp = _country_groups(" ".join((n.get("amount") or {}).get("special_countries", [])))
    if p_groups & sp:
        plus(5, f"희망국({', '.join(sorted(p_groups & sp))}) 특례 한도 적용 가능", " / ".join((n.get("amount") or {}).get("evidence", [])[:1]))
    for pf in t.get("prefers", []):
        if _country_groups(pf["rule"]) & p_groups:
            plus(5, f"우선지원 대상: {pf['rule']}", pf["evidence"])

    if d is not None and d >= 0:
        if d >= 7:
            plus(10, f"신청 가능 (D-{d})", "")
        else:
            plus(6, f"마감 임박 (D-{d}) — 서둘러 신청", "")
            warns.append({"text": f"마감 임박: D-{d}", "evidence": ""})
    if n.get("early_close"):
        warns.append({"text": "예산 소진 시 조기 마감 — 조기 신청 권장", "evidence": ""})

    usd = p.get("export_usd")
    if t.get("tiers") and usd is not None:
        rate = 100 if usd >= 50000 else 50 if usd >= 30000 else 30
        plus(10 if rate == 100 else 6, f"수출실적 {usd:,.0f}달러 → 지원비율 약 {rate}% 구간", t["tiers"][0]["evidence"])
    else:
        text_all = " ".join((n.get("sections") or {}).values())
        if p.get("export_stage", "").startswith("수출 준비") and re.search(r"소량|초보|첫\s*수출|내수", text_all + n.get("title", "")):
            plus(10, "수출초보·소량수출 기업 적합", "")
        else:
            plus(7, "수출단계 제한 없음", "")

    score = min(score, 100)
    if distributor_only and not p.get("is_overseas_distributor"):
        score = min(score, 45)
    eligible = not fails
    if not eligible:
        score = 0
    grade = ("부적합" if not eligible else "적극 추천" if score >= 80 else "추천" if score >= 60
             else "검토" if score >= 40 else "낮음")
    ap = n.get("apply") or {}
    return {
        "project_no": n["project_no"], "title": n["title"], "score": score, "grade": grade, "eligible": eligible,
        "d_day": d, "receipt_end": n.get("receipt_end"), "fields": fields, "amount": _amount_text(n.get("amount")),
        "reasons": reasons, "fails": fails, "warnings": warns, "summary": n.get("summary", ""),
        "apply_methods": ap.get("methods", []), "emails": ap.get("emails", []), "phones": ap.get("phones", []),
        "detail_url": n.get("detail_url"),
    }


def match(profile: dict, notices: list[dict], today: dt.date | None = None, include_ineligible=True) -> list[dict]:
    res = [score_notice(profile, n, today) for n in notices]
    res.sort(key=lambda r: (not r["eligible"], -r["score"], r["d_day"] if r["d_day"] is not None else 9999))
    return res if include_ineligible else [r for r in res if r["eligible"]]


# ── 민감정보 마스킹 (AI 전달·로그 저장 전)
MASKS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{5}\b"), "***-**-*****"),          # 사업자등록번호
    (re.compile(r"\b\d{6}-\d{7}\b"), "******-*******"),              # 법인/주민번호
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "010-****-****"),  # 휴대폰
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "***@***"),              # 이메일
]


def mask(text: str) -> str:
    for rx, rep in MASKS:
        text = rx.sub(rep, text or "")
    return text


def profile_brief(p: dict) -> str:
    """AI에 전달할 기업 요약 (식별정보 제외)"""
    parts = [f"소재지 {p.get('region','')}", f"규모 {p.get('size','')}",
             f"업종 {'·'.join(p.get('industries') or [])}", f"품목 {p.get('items','')}",
             f"희망국가 {p.get('target_countries','')}", f"수출단계 {p.get('export_stage','')}",
             f"전년 수출실적 {p.get('export_usd') or 0:,.0f}달러", f"직수출 {'예' if p.get('direct_export') else '아니오'}",
             f"필요분야 {', '.join(p.get('needs') or [])}"]
    return mask(" / ".join(parts))


FIELDS = ax_meta.FIELDS
