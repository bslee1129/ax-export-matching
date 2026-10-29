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

# ── 대상 업종 7분류 (기업 프로필 선택지와 같음)
INDUSTRIES = ["농수산", "식품", "화장품(뷰티)", "공예품", "생활용품(소비재)", "의료기기", "기타 공산품"]
MANUFACTURING = ["화장품(뷰티)", "공예품", "생활용품(소비재)", "의료기기", "기타 공산품"]
# (정규식, 해당 업종, 지원대상 본문에도 쓸지) — 제목은 모든 규칙, 본문은 오탐 적은 규칙만
INDUSTRY_RULES = [
    (r"농수산식품|농수축산|농축수산|농식품|수산식품|수산가공|농산가공|농수산", ["농수산", "식품"], True),
    (r"농산물|수산물|농축산|축산물|임산물|화훼|인삼|과일|과채|버섯|해조류?|수산업|수산|농산|김\s*수출|쌀\s*수출|농업인|어업인", ["농수산"], True),
    (r"식품|K-?푸드|K-?FOOD|\bFOOD\b|음료|주류|전통주|장류|김치|가공식품|간편식|HMR|제과|커피|할랄\s*식품", ["식품"], True),
    (r"화장품|코스메|뷰티|BEAUTY|Cosmoprof|코스모프로프", ["화장품(뷰티)"], True),
    (r"공예|한지|도자기|옻칠|칠기|문화상품|굿즈", ["공예품"], True),
    (r"생활용품|생활소비재|리빙|Lifestyle|라이프스타일|주방용품|유아용품|육아용품|완구|문구|패션|의류|잡화|가구|인테리어|홈데코|신발|반려동물|펫\s*용품|가전", ["생활용품(소비재)"], True),
    (r"소비재", ["식품", "화장품(뷰티)", "생활용품(소비재)", "공예품"], True),
    (r"의료기기|의료기|메디칼|메디컬|MEDICA|Expomed|Hospital|헬스케어|바이오헬스|디지털헬스|병원|치과|덴탈|Dental", ["의료기기"], True),
    # '공산품·제조기업'은 제조업 전체 (화장품·공예품·생활용품·의료기기 제조사도 해당)
    (r"공산품|제조기업|제조업체?|제조사|제조\s*중소기업", MANUFACTURING, True),
    # 산업재·기술 분야 → 기타 공산품 (본문에도 쓰는 단어 / 제목에서만 쓰는 단어)
    (r"산업재|기계|자동차|오토모티브|모빌리티|신소재|전기전자|전자부품|반도체|디스플레이|방산|방위산업|조선|철강|석유화학|"
     r"이차전지|배터리|수소|에너지|원전|플랜트|건자재|섬유|봉제|농기계|드론|로봇|ICT|정보통신|소프트웨어|스마트팜\s*기자재", ["기타 공산품"], True),
    (r"부품|세미콘|로보|자동차전장|해양플랜트|금속|화학|탄소|건설|스마트팜|방송장비|소방|광학|제약|\bIT\b|\bAI\b|스마트시티|"
     r"정보보안|사이버\s*보안|보안\s*전시|콘텐츠\s*(?:산업|기업|아메리카|마켓|쇼케이스)|게임|웹툰|애니메이션|에듀테크|핀테크", ["기타 공산품"], False),
]
# 예전 분류값 → 새 분류 (예전 기업 프로필·공고 데이터 호환)
OLD_INDUSTRY = {"농산": ["농수산"], "수산": ["농수산"], "식품": ["식품"], "공산품": MANUFACTURING,
                "기타": ["기타 공산품"], "화장품": ["화장품(뷰티)"], "뷰티": ["화장품(뷰티)"], "생활용품": ["생활용품(소비재)"],
                "소비재": ["생활용품(소비재)"], "공예": ["공예품"], "의료": ["의료기기"], "기타공산품": ["기타 공산품"]}


def normalize_industries(vals) -> list[str]:
    """기업 프로필·공고의 업종 값을 7분류로 (예전 값·줄임말 허용)"""
    if isinstance(vals, str):
        vals = [x for x in re.split(r"[,/·]", vals)]
    out = []
    for v in vals or []:
        v = str(v).strip()
        if not v:
            continue
        for x in ([v] if v in INDUSTRIES else OLD_INDUSTRY.get(v.replace(" ", ""), OLD_INDUSTRY.get(v, []))):
            if x not in out:
                out.append(x)
    return [x for x in INDUSTRIES if x in out]


def _rule_hits(text: str, body: bool = False) -> tuple[list[str], str]:
    out, ev = [], ""
    text = re.sub(r"식품\s*소비재", "식품", text or "")       # '식품소비재' = 식품
    text = re.sub(r"(?:생성형\s*)?AI\s*(?:활용|무역지원센터|기반|마케팅)", " ", text)   # 도구로서의 AI 는 업종 아님
    for rx, cats, use_body in INDUSTRY_RULES:
        if body and not use_body:
            continue
        m = re.search(rx, text or "", re.I)
        if m:
            ev = ev or m.group(0)
            for c in cats:
                if c not in out:
                    out.append(c)
    return [x for x in INDUSTRIES if x in out], ev


# 예전 이름 호환 (다른 모듈에서 참조)
INDUSTRY_KEYWORDS = {k: [] for k in INDUSTRIES}
REGION_KEYWORDS = {"전남": ["전남", "전라남도", "도내"], "광주": ["광주"]}

# ── 지역(시·도) 판단 — 제목·소관기관·지원대상 문장에서
SIDO_ALIASES = {"서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주", "대전": "대전",
                "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원", "충북": "충북", "충청북": "충북",
                "충남": "충남", "충청남": "충남", "전북": "전북", "전라북": "전북", "전남": "전남", "전라남": "전남",
                "경북": "경북", "경상북": "경북", "경남": "경남", "경상남": "경남", "제주": "제주"}
# 시·군 이름 → 시·도 (이름이 겹치는 고성·광주(경기) 등은 제외)
SIGUN = {
    "경기": "수원 성남 의정부 안양 부천 광명 평택 동두천 안산 고양 과천 구리 남양주 오산 시흥 군포 의왕 하남 용인 파주 이천 안성 김포 화성 양주 포천 여주 연천 가평 양평",
    "강원": "춘천 원주 강릉 동해 태백 속초 삼척 홍천 횡성 영월 평창 정선 철원 화천 양구 인제 양양",
    "충북": "청주 충주 제천 보은 옥천 영동 증평 진천 괴산 음성 단양",
    "충남": "천안 공주 보령 아산 서산 논산 계룡 당진 금산 부여 서천 청양 홍성 예산 태안",
    "전북": "전주 군산 익산 정읍 남원 김제 완주 진안 무주 장수 임실 순창 고창 부안",
    "전남": "목포 여수 순천 나주 광양 담양 곡성 구례 고흥 보성 화순 장흥 강진 해남 영암 무안 함평 영광 장성 완도 진도 신안",
    "경북": "포항 경주 김천 안동 구미 영주 영천 상주 문경 경산 의성 청송 영양 영덕 청도 고령 성주 칠곡 예천 봉화 울진 울릉",
    "경남": "창원 진주 통영 사천 김해 밀양 거제 양산 의령 함안 창녕 남해 하동 산청 함양 거창 합천",
    "제주": "서귀포",
}
SIGUN_TO_SIDO = {g: s for s, names in SIGUN.items() for g in names.split()}
_EVENT_RE = re.compile(r"세미나|설명회|포럼|웨비나|박람회|전시회|엑스포|EXPO|로드쇼|컨퍼런스|콘퍼런스|페어|상담회|사절단|센터")


def sido_of(text: str) -> str | None:
    """'전라남도…', '경기도', '김제시' 처럼 시·도/시·군 이름으로 시작하는 문자열 → 시·도"""
    t = (text or "").replace(" ", "")
    if "전남광주" in t or "통합특별시" in t:
        return "전남"
    for k, v in SIDO_ALIASES.items():
        if t.startswith(k):
            return v
    m = re.match(r"([가-힣]{1,3})(시|군)", t)
    if m and m.group(1) in SIGUN_TO_SIDO:
        return SIGUN_TO_SIDO[m.group(1)]
    return None


def title_region(title: str) -> tuple[str | None, str]:
    """제목으로 지역 요건 판단 → (시·도, 근거). 행사 개최지(예: '부산 국제 전시회')는 지역 요건으로 보지 않음.
      [경기] ○○ / 강원 글로벌 ○○ 지원사업 / 2026년 김제시 수출사다리 / 부산지역 중소기업 ○○ / 도내 기업"""
    t = title or ""
    m = re.match(r"\s*[\[(【<]\s*([^\])】>]+)[\])】>]", t)
    if m:
        r = sido_of(m.group(1))
        if not r:       # [천안·아산], [목포/신안] 처럼 시·군 이름만 있는 경우
            r = next((SIGUN_TO_SIDO[x] for x in re.split(r"[·ㆍ,/\s]+", m.group(1)) if x in SIGUN_TO_SIDO), None)
        if r:
            return r, t
    m = re.search(r"[\[(]\s*([^\])]{2,8})\s*[\])]\s*$", t)          # 끝의 '(전남광주)', '[충남]'
    if m and sido_of(m.group(1)) and len(re.sub(r"[^가-힣]", "", m.group(1))) <= 6:
        return sido_of(m.group(1)), t
    body = re.sub(r"^\s*(?:[\[(【<][^\])】>]*[\])】>]\s*)*(?:20\d{2}\s*년?(?:도)?\s*)?(?:(?:상|하)반기\s*)?", "", t)
    # ① 'OO시/OO군' — 지자체 사업명은 행사여도 지역 요건 (예: '김제시 수출사다리')
    m = re.search(r"([가-힣]{1,3})(시|군)(?=\s|$|[^가-힣])", body)
    if m and m.group(1) in SIGUN_TO_SIDO and not re.match(r"\s*(센터|지사|지원본부)", body[m.end():]):
        return SIGUN_TO_SIDO[m.group(1)], t
    # ② 'OO지역/OO 소재/OO 도내 기업'
    names = "|".join(sorted(list(SIDO_ALIASES) + list(SIGUN_TO_SIDO) + ["전남광주"], key=len, reverse=True))
    m = re.search(rf"({names})(?:특별자치도|특별자치시|광역시|특별시|도|시|군)?\s*(?:지역|소재|관내|도내)\s*(?:의\s*)?"
                  rf"(?:중소|수출|유망|청년|농식품|창업|강소|제조|기업|업체)", body)
    if m:
        return sido_of(m.group(1)), t
    # ③ 제목이 시·도 이름으로 시작 (행사·센터 이름이 아닐 때) — 예: '강원 글로벌 점프업 패키지'
    m = re.match(rf"\s*({names})(?:특별자치도|특별자치시|광역시|특별시|도)?(?:형)?\s", body)
    if m and not _EVENT_RE.search(body):
        return sido_of(m.group(1)), t
    return None, ""


def title_industries(title: str) -> list[str]:
    """제목의 업종 단어 → 7분류. 괄호 안 행사 영문명(예: Beauty World, MEDICA)도 사용"""
    t = re.sub(r"^\s*\[(?:1무1유|지방특화|지역특화|변경공고|재공고|연장)\]\s*", "", title or "")
    return _rule_hits(t)[0]


def target_region(text: str) -> tuple[str | None, str]:
    """지원대상 문장의 '○○ 소재 기업', '○○도 내 본사' 등 → (시·도, 근거 문장)"""
    names = "|".join(sorted(list(SIDO_ALIASES) + list(SIGUN_TO_SIDO), key=len, reverse=True))
    for l in _lines(text)[:40]:
        m = re.search(rf"({names})(?:특별자치도|특별자치시|광역시|특별시|도|시|군)?\s*(?:내\s*)?(?:에\s*)?"
                      rf"(?:소재|본사|주사무소|사업장|관내|지역\s*(?:중소|수출)?기업)", l)
        if m and not re.search(r"개최|장소|위치|센터|행사장", l[max(0, m.start() - 10): m.end() + 10]):
            return sido_of(m.group(1)), l[:160]
    return None, ""

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


def extract_target(title: str, target_text: str, page_text: str, doc_text: str, doc_target: str = "") -> dict:
    """지원대상 조건. 업종은 ① 제목 ② 상세페이지 지원대상 ③ 공고문(첨부) 신청자격·지원대상 순으로 판단."""
    if len(_clean(target_text)) < 20 and doc_target:      # 상세페이지에 대상이 없으면 공고문의 지원대상 사용
        target_text = (target_text + "\n" + doc_target).strip()
    tt = f"{title}\n{target_text}"
    lines_t = _lines(target_text)
    all_lines = _lines(page_text) + _lines(doc_text)

    basis = {}
    industries = title_industries(title)
    if industries:          # 제목에 업종이 드러나면 제목 우선 (본문의 예시·제외 문구에 흔들리지 않게)
        basis["industries"] = {"from": "제목", "evidence": title[:160]}
    else:
        # 지원대상 문장 중 업종을 말하는 문장만 ('○○ 분야 제외' 문장은 근거가 아님)
        for l in lines_t:
            if re.search(r"제외|불가|제한|우대|가점", l):
                continue
            hits, _ = _rule_hits(l, body=True)
            if hits:
                industries = [x for x in INDUSTRIES if x in set(industries) | set(hits)]
                basis.setdefault("industries", {"from": "지원대상", "evidence": l[:160]})

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
    tr, tev = title_region(title)
    if tr and tr not in ("전남", "광주"):      # 제목에 다른 지역이 명시되면 그 지역 (수출e음 외 사이트 대비)
        regions = [tr]
    if regions:
        basis["regions"] = {"from": "제목" if tr else "지원대상",
                            "evidence": tev or next((l for l in lines_t if any(k in l for k in ("전남", "광주", "도내"))), "")[:160]}

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
            "countries": countries, "text": lines_t[:8], "basis": basis}


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


def extract_apply(method_text: str, detail: dict, doc_text: str, online: str = "수출e음 온라인 신청") -> dict:
    lines = _lines(method_text)
    text = method_text + "\n" + doc_text[:15000]
    methods = []
    if re.search(r"온라인|로그인|지원사업신청|홈페이지", method_text):
        methods.append(online or "온라인 신청")
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


# ─────────────────────────────────────────────────────────────
# 공고문(한글파일) 본문 → 항목별 주요 내용
# ─────────────────────────────────────────────────────────────
DOC_CATEGORIES = [
    ("사업개요", r"개요|목적|배경|추진방향|사업\s*내용"),
    ("신청자격·지원대상", r"대상|자격|요건|제외"),
    ("지원내용·규모", r"지원\s*(내용|규모|한도|금액|기준|비율|항목|분야)|지원금|보조금"),
    ("신청방법·접수", r"신청|접수|제출\s*방법|참여\s*방법|절차"),
    ("제출서류", r"제출\s*서류|구비\s*서류|서류"),
    ("선정·평가", r"선정|평가|심사"),
    ("추진일정", r"일정|추진\s*계획|향후"),
    ("유의사항", r"유의|기타|준수|환수|정산"),
    ("문의처", r"문의|담당"),
]
_TOP_HEAD = re.compile(r"^\s*(?:(\d{1,2})\s*[.)]\s*(?=\S)|([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ])\s*\.?\s*|([󰊱-󰊹])\s*|□\s*)(.{1,40})$")
_STOP = re.compile(r"^\s*(【\s*(붙임|별첨|서식)|\[\s*(붙임|별첨|서식)|<\s*(붙임|별첨|서식)|(붙임|별첨)\s*\d|서식\s*\d)")


def doc_sections(text: str, max_chars: int = 1500) -> dict:
    """공고문 본문을 큰 제목 단위로 나눠 표준 항목(사업개요·신청자격·지원내용·신청방법…)으로 분류.
    붙임·별첨·서식(신청서 양식 등) 이후는 제외."""
    lines = [l.rstrip() for l in (text or "").splitlines()]
    blocks, cur_head, buf = [], "", []
    for l in lines:
        s = l.strip()
        if not s:
            continue
        if _STOP.match(s):
            break
        m = _TOP_HEAD.match(s)
        if m and len(s) <= 45 and not re.search(r"[:：]\s*\S", s):
            if buf or cur_head:
                blocks.append((cur_head, buf))
            cur_head, buf = _clean(m.group(4)), []
        else:
            buf.append(s)
    if buf or cur_head:
        blocks.append((cur_head, buf))

    out: dict = {}
    for head, body in blocks:
        if not body:
            continue
        cat = next((c for c, rx in DOC_CATEGORIES if head and re.search(rx, head)), None)
        if cat is None:
            cat = "공고 안내" if not head else "기타"
        txt = "\n".join(body)
        if head and cat not in ("공고 안내",):
            txt = f"[{head}]\n{txt}"
        prev = out.get(cat, "")
        if len(prev) < max_chars:
            out[cat] = (prev + "\n" + txt).strip()[:max_chars]
    # 표준 순서로 정렬
    order = ["공고 안내"] + [c for c, _ in DOC_CATEGORIES] + ["기타"]
    return {k: out[k] for k in order if k in out}


def enrich_apply(apply: dict, secs: dict, doc_text: str) -> dict:
    """상세페이지에 신청방법이 없거나 부족하면 공고문의 '신청방법·접수' 내용으로 보완"""
    a = dict(apply or {})
    src = "\n".join(secs.get(k, "") for k in ("신청방법·접수", "제출서류", "문의처"))
    if not src.strip():
        src = "\n".join(l for l in (doc_text or "").splitlines()[:400]
                        if re.search(r"신청|접수|제출|이메일|홈페이지|문의", l))
    methods = [m for m in a.get("methods", []) if m != "공고문 참조"]
    if re.search(r"(수출e음|수출정보망|jexport)[^\n]{0,40}(신청|로그인)|지원사업신청", src) and "수출e음 온라인 신청" not in methods:
        methods.append("수출e음 온라인 신청")
    if re.search(r"exportvoucher|수출바우처", src) and "수출바우처 홈페이지 신청" not in methods:
        methods.append("수출바우처 홈페이지 신청")
    if re.search(r"KOTRA\s*홈페이지|www\.kotra\.or\.kr", src, re.I) and "KOTRA 홈페이지 신청" not in methods:
        methods.append("KOTRA 홈페이지 신청")
    if re.search(r"이메일|E-?mail|메일\s*(접수|제출)|@", src, re.I) and "이메일 제출" not in methods:
        methods.append("이메일 제출")
    if "문서24" in src and "문서24" not in methods:
        methods.append("문서24")
    if re.search(r"우편|방문\s*(접수|제출)", src) and "우편/방문" not in methods:
        methods.append("우편/방문")
    a["methods"] = methods or ["공고문 참조"]
    emails = list(dict.fromkeys(list(a.get("emails", [])) + EMAIL_RE.findall(src)))
    a["emails"] = emails[:4]
    a["phones"] = list(dict.fromkeys(list(a.get("phones", [])) + PHONE_RE.findall(src)))[:4]
    # 신청 관련 핵심 문장 (공고문 기준)
    key = [l.strip() for l in secs.get("신청방법·접수", "").splitlines()
           if re.search(r"접수|신청|제출|기간|이메일|홈페이지|@", l) and not l.startswith("[") and l.count("|") < 2]
    a["doc_lines"] = [_clean(l)[:200] for l in key[:10]]
    return a
