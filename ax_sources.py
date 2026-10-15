# -*- coding: utf-8 -*-
"""수집 대상 사이트(출처)별 목록·상세·첨부 수집기

  jexport  수출e음(전남광주)               https://www.jexport.or.kr/user/reg_biz
  at       aT수출종합지원시스템 사업신청     https://global.at.or.kr/front/bizReq/brList.do
  kotra    KOTRA 무역투자24 사업신청         https://www.kotra.or.kr/subList/20000020753
  bizinfo  중기부 기업마당 지원사업 공고      https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do
           (지원분야 '수출', 전국 — 지자체 공고는 지역(region)을 표시해 매칭 때 지역 요건으로 사용)

각 수집기는 jexport_engine.Notice 를 돌려주며, 공고번호(project_no)는 출처 접두어를 붙여 구분합니다.
  (수출e음은 기존 DB 호환을 위해 접두어 없음: AT-8229, KOTRA-26EX03K, BIZ-PBLN_000000000127217)
"""
from __future__ import annotations

import html as _html
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import jexport_engine as eng

_clean = eng._clean


def _cells_kv(soup, strip_suffix: str = "") -> dict:
    """표의 th→td 쌍을 dict 로"""
    out = {}
    for tr in soup.select("tr"):
        cells = tr.find_all(["th", "td"])
        for i, c in enumerate(cells):
            if c.name == "th" and i + 1 < len(cells) and cells[i + 1].name == "td":
                k = _clean(c.get_text(" "))
                if strip_suffix and k.endswith(strip_suffix):
                    k = k[: -len(strip_suffix)].strip()
                out[k] = _clean(cells[i + 1].get_text(" "))
    return out


def _lines_text(node) -> str:
    txt = node.get_text("\n") if node is not None else ""
    return "\n".join(l.strip() for l in txt.splitlines() if l.strip())


def _norm_title(t: str) -> str:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|20\d{2}년?", "", t or "")
    return re.sub(r"[^가-힣A-Za-z0-9]", "", t).lower()


# 시·도 이름 → 짧은 이름 (지역 판단용)
SIDO = {"서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주", "대전": "대전", "울산": "울산",
        "세종": "세종", "경기": "경기", "강원": "강원", "충북": "충북", "충청북": "충북", "충남": "충남", "충청남": "충남",
        "전북": "전북", "전라북": "전북", "전북특별": "전북", "전남": "전남", "전라남": "전남", "경북": "경북",
        "경상북": "경북", "경남": "경남", "경상남": "경남", "제주": "제주"}
HOME_REGIONS = {"전남", "광주"}


def sido_of(text: str) -> str | None:
    t = (text or "").replace(" ", "")
    if "전남광주" in t or "통합특별시" in t:
        return "전남"
    for k, v in SIDO.items():
        if t.startswith(k):
            return v
    return None


def notice_region(title: str, agency: str = "") -> str | None:
    """제목 앞 [지역] 또는 소관 지자체로 지역 판단 (None = 전국 단위)"""
    m = re.match(r"\s*\[([^\]]+)\]", title or "")
    if m:
        r = sido_of(m.group(1))
        if r:
            return r
    return sido_of(agency) if re.search(r"(특별시|광역시|특별자치|도|시)$", (agency or "").strip()) else None


# ─────────────────────────────────────────────────────────────
class Source:
    key = ""
    name = ""
    home = ""
    online_method = ""        # 사이트 자체 온라인 신청 수단 이름
    max_pages = 3

    def list_open(self, sess, max_pages=None, log=print) -> list[eng.Notice]:
        raise NotImplementedError

    def fetch_detail(self, sess, n: eng.Notice) -> eng.Notice:
        raise NotImplementedError

    def download(self, sess, n: eng.Notice, outdir: Path) -> list[Path]:
        """attachments: [{name, url, method, data}] 공통 다운로드"""
        outdir.mkdir(parents=True, exist_ok=True)
        saved, seen = [], set()
        for att in n.attachments:
            key = (att.get("url"), str(att.get("data")))
            if key in seen:
                continue
            seen.add(key)
            try:
                if att.get("method") == "POST":
                    r = sess.post(att["url"], data=att.get("data"), timeout=90, headers={"Referer": n.detail_url})
                else:
                    r = sess.get(att["url"], timeout=90, headers={"Referer": n.detail_url})
                r.raise_for_status()
            except Exception as e:
                n.errors.append(f"다운로드 실패: {att.get('name')} ({type(e).__name__})")
                continue
            time.sleep(eng.REQUEST_DELAY)
            if "text/html" in r.headers.get("Content-Type", "") and len(r.content) < 20000:
                n.errors.append(f"다운로드 실패(HTML 응답): {att.get('name')}")
                continue
            nm = att.get("name") or ""
            if not re.search(r"\.\w{2,5}$", nm):
                nm = eng._filename_from_cd(r.headers.get("Content-Disposition", "")) or nm or f"{n.project_no}.bin"
            path = outdir / eng._safe_name(nm, 120)
            path.write_bytes(r.content)
            saved.append(path)
        return saved


# ── 수출e음 (기존 엔진 사용)
class Jexport(Source):
    key, name, home = "jexport", "수출e음", "https://www.jexport.or.kr/user/reg_biz"
    online_method = "수출e음 온라인 신청"

    def list_open(self, sess, max_pages=None, log=print):
        rows = []
        for page in range(1, (max_pages or self.max_pages) + 1):
            url = eng.LIST_URL if page == 1 else eng.LIST_PAGE_URL
            got = eng.parse_list_page(eng._get(sess, url, params={"page": page}).text)
            if not got:
                break
            rows += got
        for x in rows:
            x.detail_url = f"{eng.DETAIL_URL}?project_no={x.project_no}"
        return rows

    def fetch_detail(self, sess, n):
        eng.fetch_detail(sess, n)
        return n

    def download(self, sess, n, outdir):
        return eng.download_attachments(sess, n, outdir) if n.attachments else []


# ── aT 수출종합지원시스템
class AT(Source):
    key, name, home = "at", "aT수출종합지원시스템", "https://global.at.or.kr/front/bizReq/brList.do"
    online_method = "aT수출종합지원시스템 온라인 신청"
    BASE = "https://global.at.or.kr"
    max_pages = 5

    def list_open(self, sess, max_pages=None, log=print):
        out = []
        for page in range(1, (max_pages or self.max_pages) + 1):
            r = sess.post(self.BASE + "/front/bizReq/brList.do", data={"page": page}, timeout=30)
            r.raise_for_status()
            time.sleep(eng.REQUEST_DELAY)
            rows = parse_at_list(r.text)
            if not rows:
                break
            out += [x for x in rows if x.status == "접수중"]
            if not any(x.status == "접수중" for x in rows):      # 진행중 공고가 먼저 나오고 마감 공고가 뒤에 나옴
                break
        return out

    def fetch_detail(self, sess, n):
        r = eng._get(sess, n.detail_url)
        parse_at_detail(r.text, n)
        return n


def parse_at_list(html: str) -> list[eng.Notice]:
    soup = eng._soup(html)
    out = []
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        a = tr.find("a", href=re.compile(r"goViewPage")) or tr.find("a", onclick=re.compile(r"goViewPage"))
        if len(tds) < 5 or not a:
            continue
        m = re.search(r"goViewPage\s*\(\s*'(\d+)'\s*,\s*'(\d+)'", (a.get("href") or "") + (a.get("onclick") or ""))
        if not m:
            continue
        st = _clean(tds[4].get_text(" "))
        n = eng.Notice(project_no=f"AT-{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) != "0" else ""),
                       title=_clean(a.get_text(" ")) or _clean(tds[2].get_text(" ")),
                       region="전국", period=_clean(tds[3].get_text(" ")),
                       status="접수중" if "진행" in st else ("접수예정" if "예정" in st else "접수마감"))
        n.subtitle = _clean(tds[1].get_text(" "))
        n.detail_url = f"{AT.BASE}/front/bizReq/brView.do?proj_id={m.group(1)}&proj_detail_id={m.group(2)}"
        n.detail = {"접수기간": n.period, "이름": _clean(tds[5].get_text(" ")) if len(tds) > 5 else "",
                    "전화번호": _clean(tds[6].get_text(" ")) if len(tds) > 6 else ""}
        out.append(n)
    return out


def parse_at_detail(html: str, n: eng.Notice) -> eng.Notice:
    soup = eng._soup(html)
    kv = _cells_kv(soup, strip_suffix="필수")
    n.title = kv.get("사업명") or n.title
    if kv.get("접수기간"):
        n.period = kv["접수기간"]
    n.detail.update({"접수기간": n.period, "사업기간": kv.get("사업기간", ""), "소속": kv.get("담당부서", ""),
                     "이름": kv.get("사업담당자", n.detail.get("이름", "")),
                     "전화번호": kv.get("연락처", n.detail.get("전화번호", "")), "이메일": kv.get("이메일", ""),
                     "지원분야": kv.get("지원 분야", "")})
    sec = {}
    for th in soup.find_all("th"):
        k = _clean(th.get_text(" ")).replace("필수", "").strip()
        td = th.find_next_sibling("td")
        if k in ("사업개요", "지원대상", "내용") and td is not None:
            v = _lines_text(td)
            if v:
                sec["사업내용" if k == "내용" else k] = v
    sec["지원방법 및 신청방법"] = (f"aT수출종합지원시스템(global.at.or.kr) 온라인 사업신청\n"
                            f"담당: {kv.get('담당부서', '')} {kv.get('사업담당자', '')} {kv.get('연락처', '')} {kv.get('이메일', '')}").strip()
    n.sections = sec
    n.attachments = []
    for a in soup.find_all("a"):
        m = re.search(r"downloadFile\s*\(\s*'([^']*)'\s*,\s*'([^']*)'", (a.get("href") or "") + (a.get("onclick") or ""), re.S)
        if m:
            n.attachments.append({"name": _clean(a.get_text(" ")), "url": AT.BASE + "/attach/fileDownloadN.do",
                                  "method": "POST", "data": {"addfile_id": m.group(1), "addfile_nm": m.group(2).strip()}})
    return n


# ── KOTRA 무역투자24
class Kotra(Source):
    key, name, home = "kotra", "KOTRA 무역투자24", "https://www.kotra.or.kr/subList/20000020753"
    online_method = "KOTRA 무역투자24 온라인 신청"
    BASE = "https://www.kotra.or.kr"
    LIST = BASE + "/module/subhome/bizAply/selectBmBizAllListAjax.do"
    DETAIL = BASE + "/subList/20000020753/subhome/bizAply/selectBizMntInfoDetail.do"
    max_pages = 40

    def list_open(self, sess, max_pages=None, log=print):
        out, seen = [], set()
        for page in range(1, (max_pages or self.max_pages) + 1):
            data = {"pageNo": 1, "pageNo2": 1, "pageNoA": page, "pageSize": 10, "listCount": 10, "query": " ",
                    "collection": "business_application", "sch_biz_name": "", "schwrdVal": "",
                    "sch_event_start_dt": "", "sch_event_end_dt": "", "sch_nation_cd": "Y",
                    "startCount": (page - 1) * 10}
            r = sess.post(self.LIST, data=data, timeout=30,
                          headers={"X-Requested-With": "XMLHttpRequest", "Referer": self.home})
            r.raise_for_status()
            time.sleep(eng.REQUEST_DELAY)
            rows = [x for x in parse_kotra_list(r.text) if x.project_no not in seen]
            if not rows:
                break
            seen.update(x.project_no for x in rows)
            out += [x for x in rows if x.status == "접수중"]
        return out

    def fetch_detail(self, sess, n):
        r = eng._get(sess, n.detail_url)
        parse_kotra_detail(r.text, n)
        return n


def parse_kotra_list(html: str) -> list[eng.Notice]:
    soup = eng._soup(html)
    out = []
    for card in soup.select(".card-body"):
        raw = str(card)
        m = re.search(r"dtlBizMntNo=([A-Za-z0-9]+)", raw.replace("&amp;", "&"))
        a = card.select_one("a.card-tit") or card.find("a")
        if not m or a is None:
            continue
        kv = {}
        for dt_ in card.find_all("dt"):
            dd = dt_.find_next_sibling("dd")
            if dd is not None:
                kv[_clean(dt_.get_text(" "))] = _clean(dd.get_text(" "))
        st = " ".join(_clean(x.get_text(" ")) for x in card.select("dd.fw600, dd.txt-comm-sec, dd.txt-dan-pri"))
        status = ("접수중" if "신청가능" in st else "접수예정" if "예정" in st
                  else "접수마감" if re.search(r"마감|종료", st.replace("오늘마감", "")) else "접수중")
        badge = card.select_one(".card-badge")
        title = _clean(a.get_text(" "))
        n = eng.Notice(project_no=f"KOTRA-{m.group(1)}", title=title, region=notice_region(title) or "전국",
                       period=kv.get("신청기간", ""), status=status)
        n.subtitle = _clean(badge.get_text(" ")) if badge else ""
        n.detail_url = f"{Kotra.DETAIL}?dtlBizMntNo={m.group(1)}&cpbizYn=N"
        n.detail = {"접수기간": n.period, "소속": kv.get("주관부서", ""),
                    "전화번호": kv.get("사업문의 전화번호", ""), "이메일": kv.get("사업문의 이메일", "")}
        out.append(n)
    return out


def parse_kotra_detail(html: str, n: eng.Notice) -> eng.Notice:
    soup = eng._soup(html)
    tit = soup.select_one(".subCon h4.tit") or soup.select_one("h4.tit")
    if tit:
        n.title = _clean(tit.get_text(" ")) or n.title
    kv = _cells_kv(soup)
    if kv.get("신청기간"):
        n.period = kv["신청기간"]
    n.detail.update({"접수기간": n.period, "개최기간": kv.get("개최기간", ""), "사업유형": kv.get("사업유형", ""),
                     "소속": kv.get("주관부서", n.detail.get("소속", "")),
                     "전화번호": kv.get("사업문의 전화번호", n.detail.get("전화번호", "")),
                     "이메일": kv.get("사업문의 이메일", n.detail.get("이메일", ""))})
    sec = {}
    ta = soup.select_one(".nBizCont textarea") or soup.select_one(".nBizCont")
    if ta is not None:
        inner = _html.unescape(ta.get_text())
        body = _lines_text(eng._soup(inner)) if "<" in inner else "\n".join(l.strip() for l in inner.splitlines() if l.strip())
        if body:
            sec["사업개요"] = body
    info = " / ".join(f"{k} {v}" for k, v in kv.items() if k in ("사업유형", "모집회원구분", "개최기간", "사업진행장소") and v and v != "-")
    if info:
        sec["사업정보"] = info
    sec["지원방법 및 신청방법"] = (f"KOTRA 무역투자24 온라인 사업신청(일반회원 로그인 후 신청)\n"
                            f"문의: {kv.get('주관부서', '')} {kv.get('사업문의 전화번호', '')} {kv.get('사업문의 이메일', '')}").strip()
    n.sections = sec
    n.attachments = []
    for a in soup.find_all("a", href=re.compile(r"fileDown\.do")):
        nm = _clean(a.get_text(" "))
        if not nm or nm in ("다운로드", "내려받기"):
            row = a.find_parent(["tr", "li"])
            nm = _clean(row.get_text(" ")).replace("다운로드", "").strip() if row else ""
        n.attachments.append({"name": nm, "url": urljoin(Kotra.BASE, a["href"]), "method": "GET"})
    return n


# ── 중기부 기업마당 (지원분야: 수출)
class Bizinfo(Source):
    key, name, home = "bizinfo", "기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do"
    online_method = ""
    BASE = "https://www.bizinfo.go.kr"
    max_pages = 30

    def list_open(self, sess, max_pages=None, log=print):
        out, seen = [], set()
        for page in range(1, (max_pages or self.max_pages) + 1):
            r = eng._get(sess, self.home, params={"hashCode": "07", "cpage": page, "schEndAt": "N"})
            rows = [x for x in parse_bizinfo_list(r.text) if x.project_no not in seen]
            if not rows:
                break
            seen.update(x.project_no for x in rows)
            out += rows
        return out

    def fetch_detail(self, sess, n):
        r = eng._get(sess, n.detail_url)
        parse_bizinfo_detail(r.text, n)
        return n


def parse_bizinfo_list(html: str) -> list[eng.Notice]:
    soup = eng._soup(html)
    out = []
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        a = tr.find("a", href=re.compile(r"pblancId="))
        if len(tds) < 6 or a is None:
            continue
        pid = re.search(r"pblancId=([A-Za-z0-9_]+)", a["href"]).group(1)
        title = _clean(a.get_text(" "))
        agency, org = _clean(tds[4].get_text(" ")), _clean(tds[5].get_text(" "))
        reg = notice_region(title, agency) or "전국"
        n = eng.Notice(project_no=f"BIZ-{pid}", title=title, region=reg, period=_clean(tds[3].get_text(" ")), status="접수중")
        n.subtitle = " · ".join(x for x in (agency, org) if x)
        n.detail_url = f"{Bizinfo.BASE}/sii/siia/selectSIIA200Detail.do?pblancId={pid}"
        n.detail = {"접수기간": n.period, "소관부처": agency, "사업수행기관": org, "소속": org}
        out.append(n)
    return out


def parse_bizinfo_detail(html: str, n: eng.Notice) -> eng.Notice:
    soup = eng._soup(html)
    h2 = soup.select_one("h2.title")
    if h2:
        n.title = _clean(h2.get_text(" ")) or n.title
    kv = {}
    for sp in soup.select("li span.s_title"):
        box = sp.find_next_sibling("div")
        if box is not None:
            kv[_clean(sp.get_text(" "))] = _lines_text(box)
    if kv.get("신청기간"):
        n.period = _clean(kv["신청기간"])
    n.detail.update({"접수기간": n.period, "소관부처": kv.get("소관부처·지자체", n.detail.get("소관부처", "")),
                     "사업수행기관": kv.get("사업수행기관", n.detail.get("사업수행기관", ""))})
    n.detail["소속"] = n.detail["사업수행기관"]
    contact = kv.get("문의처", "")
    ph = eng.PHONE_RE.findall(contact)
    em = eng.EMAIL_RE.findall(contact + " " + kv.get("사업신청 방법", ""))
    n.detail["전화번호"] = ph[0] if ph else ""
    n.detail["이메일"] = em[0] if em else ""
    sec = {}
    if kv.get("사업개요"):
        sec["사업개요"] = kv["사업개요"]
    if kv.get("사업신청 방법"):
        sec["지원방법 및 신청방법"] = kv["사업신청 방법"]
    if contact:
        sec["문의처"] = contact
    n.sections = sec
    n.attachments, seen = [], set()
    box = soup.select_one("div.attached_file_list") or soup
    for li in box.find_all("li"):
        a = li.find("a", href=re.compile(r"fileDown\.do"))
        if a is None:
            continue
        fid = re.search(r"atchFileId=([A-Za-z0-9_]+)", a["href"].replace("&amp;", "&"))
        key = fid.group(1) if fid else a["href"]
        if key in seen:
            continue
        seen.add(key)
        fn = li.select_one(".file_name")
        nm = _clean(fn.get_text(" ")) if fn else ""
        n.attachments.append({"name": nm, "url": urljoin(Bizinfo.BASE, a["href"].replace("&amp;", "&")), "method": "GET"})
    return n


SOURCES = {s.key: s for s in (Jexport(), AT(), Kotra(), Bizinfo())}
ORDER = ["jexport", "at", "kotra", "bizinfo"]       # 중복 공고는 앞 출처 우선 (기업마당은 타기관 공고 재게시가 많음)


def source_of(project_no: str) -> str:
    p = str(project_no or "")
    return "at" if p.startswith("AT-") else "kotra" if p.startswith("KOTRA-") else "bizinfo" if p.startswith("BIZ-") else "jexport"
