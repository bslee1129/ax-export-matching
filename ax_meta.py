# -*- coding: utf-8 -*-
"""공고 메타데이터 표준화 (규칙 기반)

공고 상세페이지 + 첨부 공고문 텍스트 → 공통 메타데이터
  - 지원분야(fields)      : 물류비 / 해외전시·박람회 / 바이어·상담회 / 통번역 / 인증·규격 / 관세·FTA / 해외거점·지사화 / 온라인·홍보마케팅 / 교육·컨설팅 / 금융·보험
  - 지원대상(target)      : 업종(농산·수산·식품·공산품), 기업유형(중소기업·해외운영사…), 지역, 제외조건, 필수조건
  - 지원금액(amount)      : 기업당 최대 지원액(만원), 지원비율(%)
  - 신청(apply)           : 온라인/이메일/문서24, 이메일·전화, 담당자
모든 항목은 근거 문장(evidence)을 함께 저장 → 화면·답변에서 원문 근거로 제시
"""
from __future__ import annotations

import re

# ── 지원분야 사전 (키워드: 가중치)
FIELD_KEYWORDS = {
    "물류비": {"물류비": 3, "운송": 1, "운임": 2, "특송": 3, "EMS": 3, "해운": 1, "창고보관": 2, "배송": 1},
    "해외전시·박람회": {"박람회": 3, "전시회": 3, "부스": 2, "엑스포": 2, "공동관": 2, "시장개척단": 3},
    "바이어·상담회": {"바이어": 3, "수출상담회": 3, "상담회": 2, "초청": 1, "매칭": 1},
    "통번역": {"통역": 3, "번역": 3, "통번역": 3, "통·번역": 3, "통․번역": 3},
    "인증·규격": {"인증": 2, "규격": 2, "할랄": 3, "FDA": 3, "CE인증": 3, "시험성적": 2},
    "관세·FTA": {"관세": 2, "FTA": 3, "원산지": 3, "환급": 2, "통관": 1},
    "해외거점·지사화": {"지사화": 3, "상설판매장": 3, "해외지사": 3, "거점": 2, "팝업스토어": 3, "유통망 입점": 3},
    "온라인·홍보마케팅": {"온라인": 1, "디지털 마케팅": 3, "홍보물": 2, "카탈로그": 2, "마케팅": 1, "판촉": 1, "홍보": 1},
    "교육·컨설팅": {"교육": 1, "컨설팅": 2, "멘토링": 2, "코칭": 2},
    "금융·보험": {"보험": 2, "보증": 2, "금융": 2, "대출": 3, "이차보전": 3},
}
FIELDS = list(FIELD_KEYWORDS)

INDUSTRY_KEYWORDS = {
    "농산": ["농산", "농수산", "농식품", "농업"],
    "수산": ["수산", "농수산", "수산물", "수산가공"],
    "식품": ["식품", "농수산식품", "가공식품", "K-푸드", "K-FOOD"],
    "공산품": ["공산품", "소비재", "산업재", "제조업체"],
}
REGION_KEYWORDS = {"전남": ["전남", "전라남도", "도내"], "광주": ["광주"]}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
# 금액: "최대 300만원", "150만원 한도", "60백만원", "3백만원", "1억원", "월 50만 원"
AMOUNT_RE = re.compile(r"(\d[\d,\.]*)\s*(억|천만|백만|만)\s*원")
RATE_RE = re.compile(r"(\d{1,3})\s*%\s*(?:이내|이하|지원|까지)?")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _lines(text: str) -> list[str]:
    return [_clean(l) for l in (text or "").splitlines() if _clean(l)]


def _to_manwon(num: str, unit: str) -> float:
    v = float(num.replace(",", ""))
    return v * {"억": 10000, "천만": 1000, "백만": 100, "만": 1}[unit]


def extract_fields(title: str, page_text: str, doc_text: str) -> list[dict]:
    out = []
    for field, kws in FIELD_KEYWORDS.items():
        score, ev = 0.0, []
        for kw, w in kws.items():
            t = title.count(kw)
            p = page_text.count(kw)
            d = min(doc_text.count(kw), 10)
            score += w * (4 * t + 2 * p + 0.5 * d)
            if (t or p) and len(ev) < 2:
                src = title if t else next((l for l in _lines(page_text) if kw in l), "")
                if src and src not in ev:
                    ev.append(src[:160])
        if score >= 6:
            out.append({"field": field, "score": round(score, 1), "evidence": ev})
    out.sort(key=lambda x: -x["score"])
    # 상위 분야 대비 너무 약한 분야는 제외 (예: 모든 공고에 흔한 '홍보')
    if out:
        top = out[0]["score"]
        out = [x for x in out if x["score"] >= top * 0.25]
    return out[:4]


def extract_target(title: str, target_text: str, page_text: str, doc_text: str) -> dict:
    tt = f"{title}\n{target_text}"
    lines_t = _lines(target_text)
    all_lines = _lines(page_text) + _lines(doc_text)

    industries = [k for k, kws in INDUSTRY_KEYWORDS.items() if any(kw in tt for kw in kws)]
    if "농수산" in tt and "식품" not in industries:
        industries.append("식품")

    company_types = []
    if re.search(r"해외\s*유통매장\s*운영사|현지\s*벤더|수입업체", tt):
        company_types.append("해외 유통매장 운영사")
    if "중소기업" in tt or "중소" in tt:
        company_types.append("중소기업")
    if not company_types:
        company_types.append("수출기업")

    regions = [k for k, kws in REGION_KEYWORDS.items() if any(kw in tt for kw in kws)]
    if "전남광주" in tt or "통합특별시" in tt:
        regions = ["전남", "광주"]

    excludes, requires, prefers, tiers = [], [], [], []
    for l in lines_t + [l for l in all_lines if re.search(r"제외|제한|불가", l)][:15]:
        if re.search(r"코스피|코스닥|상장", l) and not any("상장" in x["rule"] for x in excludes):
            excludes.append({"rule": "상장기업 제외", "evidence": l[:160]})
        if re.search(r"타시도\s*제품만\s*유통", l) and not any("타시도" in x["rule"] for x in excludes):
            excludes.append({"rule": "타시도 제품만 유통하는 기업 제외", "evidence": l[:160]})
        if re.search(r"휴\S*폐업|불량거래", l) and not any("휴·폐업" in x["rule"] for x in excludes):
            excludes.append({"rule": "휴·폐업/금융불량 기업 제외", "evidence": l[:160]})
    for l in lines_t:
        if re.search(r"직접\s*수출|직수출", l) and not requires:
            requires.append({"rule": "직수출 기업", "evidence": l[:160]})
        m1 = re.search(r"\(\s*우선\s*지원\s*\)\s*([^※(]+)", l)
        m2 = re.search(r"([^\s,:※]+(?:\s[^\s,:※]+){0,3})\s*우선\s*(?:지원|선정)", l)
        rule = _clean(m1.group(1)) if m1 else (_clean(m2.group(1)) if m2 else "")
        rule = re.sub(r"^[-※·\s]*(경합\s*시\s*)?", "", rule).strip(" -")
        if rule and not any(x["rule"] == rule[:60] for x in prefers):
            prefers.append({"rule": rule[:60], "evidence": l[:160]})
        if re.search(r"(\d+)\s*만\s*불\s*이상", l) and "%" in l:
            tiers.append({"rule": "수출실적별 차등지원", "evidence": l[:160]})
    if re.search(r"본사\s*(또는|·|및)\s*공장", tt):
        requires.append({"rule": "관내 본사 또는 공장 소재",
                         "evidence": next((l for l in lines_t if "본사" in l), "")[:160]})
    # 대상 국가: 제목 + 금액·특례 문장이 아닌 대상 문장에서만 (예: '미주 바이어 초청 시 최대 300만원'은 특례)
    plain = [l for l in lines_t if not re.search(r"만\s*원|최대|초청\s*시", l)]
    countries = sorted({c for c in COUNTRY_WORDS if c in title or any(c in l for l in plain)})
    return {"industries": industries, "company_types": company_types, "regions": regions,
            "excludes": excludes, "requires": requires, "prefers": prefers, "tiers": tiers,
            "countries": countries, "text": lines_t[:8]}


COUNTRY_WORDS = ["중동", "미국", "미주", "일본", "중국", "베트남", "동남아", "유럽", "러시아", "인도", "UAE",
                 "사우디", "대만", "홍콩", "태국", "인도네시아", "말레이시아", "호주", "캐나다", "멕시코", "아프리카", "나고야"]


def extract_amount(page_text: str, doc_text: str) -> dict:
    cand = []
    for src_name, text in (("상세페이지", page_text), ("공고문", doc_text[:20000])):
        for l in _lines(text):
            if not re.search(r"한도|최대|지원금액|지원기준|지원규모|이내", l):
                continue
            for m in AMOUNT_RE.finditer(l):
                v = _to_manwon(m.group(1), m.group(2))
                if 10 <= v <= 100000:
                    cand.append((v, l[:160], src_name))
        if cand:
            break
    rates = []
    for l in _lines(page_text) + _lines(doc_text[:8000]):
        if re.search(r"만\s*불|차등|할인", l):      # 실적 구간별 차등·할인율은 지원비율이 아님
            continue
        if re.search(r"지원|이내|보조", l):
            rates += [int(m.group(1)) for m in RATE_RE.finditer(l) if 10 <= int(m.group(1)) <= 100]
    if not cand:
        return {"max_manwon": None, "rate": max(set(rates), key=rates.count) if rates else None, "evidence": []}
    # 기업당 기본 한도 = '기업당' 문장 중 최소값이 있으면 우선, 없으면 최댓값
    per_company = [c for c in cand if "기업당" in c[1] or "개소당" in c[1] or "운영사" in c[1]]
    best = max(per_company or cand, key=lambda c: c[0])
    special = [c for c in cand if c[0] > best[0] and ("단," in c[1] or "※" in c[1] or "중동" in c[1] or "미주" in c[1])]
    sp_lines = [c[1] for c in special]
    special_countries = sorted({w for w in COUNTRY_WORDS for l in sp_lines if w in l})
    return {"max_manwon": best[0], "special_max_manwon": max(c[0] for c in special) if special else None,
            "special_countries": special_countries,
            "rate": max(set(rates), key=rates.count) if rates else None,
            "evidence": list(dict.fromkeys(c[1] for c in sorted(cand, key=lambda c: -c[0])))[:3]}


def extract_apply(method_text: str, detail: dict, doc_text: str) -> dict:
    lines = _lines(method_text)
    text = method_text + "\n" + doc_text[:15000]
    methods = []
    if re.search(r"온라인|로그인|지원사업신청", method_text):
        methods.append("수출e음 온라인 신청")
    if re.search(r"이메일|E-?mail|메일", method_text, re.I):
        methods.append("이메일 제출")
    if "문서24" in text:
        methods.append("문서24")
    if re.search(r"우편|방문", method_text):
        methods.append("우편/방문")
    emails = list(dict.fromkeys(EMAIL_RE.findall(method_text + " " + detail.get("이메일", ""))))
    if not emails:
        emails = list(dict.fromkeys(EMAIL_RE.findall(doc_text)))[:3]
    phones = list(dict.fromkeys(PHONE_RE.findall(method_text + " " + detail.get("전화번호", "") + " " + doc_text[:20000])))[:4]
    return {"methods": methods or ["공고문 참조"], "emails": emails, "phones": phones,
            "contact": {k: detail.get(k, "") for k in ("소속", "이름", "직위", "전화번호", "이메일")},
            "lines": lines[:8]}


def make_summary(title: str, fields: list, amount: dict, target: dict, receipt_end: str) -> str:
    parts = []
    if fields:
        parts.append("/".join(f["field"] for f in fields[:2]))
    if amount.get("max_manwon"):
        a = amount["max_manwon"]
        parts.append(f"최대 {a/100:.0f}백만원" if a >= 1000 else f"최대 {a:.0f}만원")
    if amount.get("rate"):
        parts.append(f"{amount['rate']}% 이내")
    if target.get("industries"):
        parts.append("대상:" + "·".join(target["industries"]))
    if receipt_end:
        parts.append(f"~{receipt_end}")
    return " | ".join(parts)


def make_chunks(sections: dict, docs: list[dict], max_len: int = 500) -> list[dict]:
    """RAG 검색용 조각: 상세페이지 섹션 + 첨부문서(제목 단위로 묶어 max_len 이내)"""
    out, seq = [], 0
    for k, v in (sections or {}).items():
        for part in _split(v, max_len):
            out.append({"source": "상세페이지", "seq": seq, "heading": k, "text": part}); seq += 1
    head_re = re.compile(r"^\s*(\d{1,2}\.|[가-하]\.|【|[󰊱-󰊹]|[ⅠⅡⅢⅣⅤ]\.)")
    for d in docs:
        heading, buf = "", []
        for line in d["text"].splitlines():
            line = line.rstrip()
            if not line.strip():
                continue
            if head_re.match(line) and len(line) < 60:
                if buf:
                    for part in _split("\n".join(buf), max_len):
                        out.append({"source": d["file_name"], "seq": seq, "heading": heading, "text": part}); seq += 1
                heading, buf = _clean(line), []
            else:
                buf.append(line)
        if buf:
            for part in _split("\n".join(buf), max_len):
                out.append({"source": d["file_name"], "seq": seq, "heading": heading, "text": part}); seq += 1
    return out


def _split(text: str, max_len: int) -> list[str]:
    lines, out, cur = [l for l in text.splitlines() if l.strip()], [], ""
    for l in lines:
        if len(cur) + len(l) + 1 > max_len and cur:
            out.append(cur); cur = ""
        cur = (cur + "\n" + l) if cur else l
        while len(cur) > max_len * 2:
            out.append(cur[:max_len]); cur = cur[max_len:]
    if cur:
        out.append(cur)
    return out
