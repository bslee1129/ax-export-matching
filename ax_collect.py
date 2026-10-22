# -*- coding: utf-8 -*-
"""① 데이터 수집 자동화: 지원사업 공고 수집 → 첨부 텍스트 추출 → 메타데이터 표준화 → DB 적재

수집 사이트: 수출e음(jexport) · 전북 수출통합지원시스템(jbexport) · aT수출종합지원시스템(at) · KOTRA 무역투자24(kotra) · 기업마당 수출분야(bizinfo)

사용
  python ax_collect.py                          # 전체 사이트, 접수중 공고 신규/변경분만 분석
  python ax_collect.py --sources jexport,kotra  # 일부 사이트만
  python ax_collect.py --force                  # 접수중 공고 전부 다시 분석
  python ax_collect.py --insecure               # SSL 인증서 오류 시
  python ax_collect.py --reanalyze              # 수집 없이 기존 공고의 업종·지역 판단·중복 묶음만 다시 계산
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import traceback
from pathlib import Path

import ax_db
import ax_dedup
import ax_meta
import ax_sources
import jexport_engine as eng


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def doc_full_text(doc) -> str:
    """표 자리표시([표 n])를 표 내용(행 단위 ' | ' 연결)으로 치환한 전체 텍스트"""
    txt = doc.text
    for t in doc.tables:
        rows = []
        for r in t.rows:
            uniq = []
            for c in r:
                if not uniq or uniq[-1] != c:
                    uniq.append(c)
            if any(uniq):
                rows.append(" | ".join(x.replace("\n", " ") for x in uniq))
        txt = txt.replace(f"[표 {t.index}]", "\n".join(rows), 1)
    return txt


def apply_region(n, target: dict, sec: dict, dsecs: dict, source: str):
    """전국 사이트의 지역 요건: ① 제목(·소관 지자체) ② 지원대상의 '○○ 소재 기업' ③ 전북 사이트는 '도내' 문구
    (본문에 '광주 개최' 같은 행사 장소가 있어도 지역 제한으로 보지 않음)"""
    agency = (n.detail or {}).get("소관부처", "") or (n.subtitle or "").split(" · ")[0]
    reg = ax_sources.notice_region(n.title, agency)
    basis = {"from": "제목", "evidence": n.title} if reg else None
    if not reg:
        tgt = "\n".join([sec.get("지원대상", ""), dsecs.get("신청자격·지원대상", "")])
        reg, ev = ax_meta.target_region(tgt)
        if reg:
            basis = {"from": "지원대상", "evidence": ev}
    if not reg and source == "jbexport" and re.search(r"전북|전라북도", n.title or ""):
        reg, basis = "전북", {"from": "제목", "evidence": n.title}     # 전북 사이트 + 제목에 전북 (예: 전북 해외통상거점센터 사업)
    if not reg and source == "jbexport":
        txt = "\n".join(list(sec.values()) + [dsecs.get("신청자격·지원대상", ""), dsecs.get("공고 안내", "")])
        m = re.search(r"[^\n]{0,40}(도내|전북\s*(?:특별자치도)?\s*(?:내\s*)?소재|전라북도\s*소재)[^\n]{0,40}", txt)
        if m:
            reg, basis = "전북", {"from": "지원대상", "evidence": m.group(0).strip()[:160]}
    n.region = reg or "전국"
    target["regions"] = [] if not reg else (["전남", "광주"] if reg in ax_sources.HOME_REGIONS else [reg])
    target.setdefault("basis", {})
    if reg:
        target["basis"]["regions"] = basis
    else:
        target["basis"].pop("regions", None)


def build_record(n, docs: list[dict], source: str = "jexport") -> dict:
    src = ax_sources.SOURCES.get(source)
    sec = n.sections or {}
    page_text = "\n".join(sec.values())
    target_text = sec.get("지원대상", "")
    method_text = next((v for k, v in sec.items() if "지원방법" in k or "제출서류" in k), "")
    doc_text = "\n".join(d["text"] for d in docs)
    start, end = eng._parse_period(n.detail.get("접수기간") or n.period)

    main_doc = "\n".join(d["text"] for d in docs if not d["file_name"].lower().endswith((".xlsx", ".xlsm")))
    dsecs = ax_meta.doc_sections(main_doc)
    fields = ax_meta.extract_fields(n.title, page_text, doc_text)
    target = ax_meta.extract_target(n.title, target_text + "\n" + sec.get("사업개요", ""), page_text, doc_text,
                                    doc_target=dsecs.get("신청자격·지원대상", ""))
    amount = ax_meta.extract_amount(page_text, doc_text)
    apply = ax_meta.extract_apply(method_text, n.detail, doc_text, online=src.online_method if src else "")
    apply = ax_meta.enrich_apply(apply, dsecs, main_doc)
    if source != "jexport":
        apply_region(n, target, sec, dsecs, source)
    return {
        "project_no": n.project_no, "source": source, "title": n.title, "subtitle": n.subtitle,
        "region": n.region, "status": n.status, "notice_period": n.detail.get("공고기간", ""),
        "receipt_start": start.isoformat() if start else None, "receipt_end": end.isoformat() if end else None,
        "early_close": int(bool(re.search(r"예산\s*소진", page_text + doc_text[:5000]))),
        "detail_url": getattr(n, "detail_url", "") or f"{eng.DETAIL_URL}?project_no={n.project_no}",
        "fields": fields, "target": target, "amount": amount, "apply": apply, "sections": sec, "doc_sections": dsecs,
        "attachments": [{"name": a["name"], "files": [d["file_name"] for d in docs]} for a in n.attachments],
        "summary": ax_meta.make_summary(n.title, fields, amount, target, end.isoformat() if end else ""),
        "analyzed_at": _now(),
    }


def collect(max_pages: int = 3, force: bool = False, insecure: bool = False, ca_bundle: str | None = None,
            log=print, session=None, db_path=ax_db.DB_PATH, sources=None) -> dict:
    started = _now()
    logs = []

    def L(msg):
        logs.append(msg)
        log(msg)

    sess = session or eng._session(insecure, ca_bundle)
    con = ax_db.connect(db_path)
    n_new = n_an = n_list = 0
    keys = [k for k in ax_sources.ORDER if not sources or k in sources]
    known = {r["project_no"]: dict(r) for r in con.execute("SELECT project_no, title, status, attachments_json FROM notices")}
    try:
        for si, key in enumerate(keys, 1):
            src = ax_sources.SOURCES[key]
            L(f"[{si}/{len(keys)}] {src.name} 공고 수집")
            try:
                open_ = src.list_open(sess, max_pages if key == "jexport" else None, log=L)
            except Exception as e:
                if eng._check_ssl_error(e):
                    raise
                L(f"  ! {src.name} 목록 수집 실패: {type(e).__name__}: {str(e)[:200]} — 다음 사이트로 넘어갑니다")
                continue
            n_list += len(open_)
            open_ = [x for x in open_ if "접수중" in x.status]
            # 다른 사이트와 같은 공고도 모두 저장하고, 수집이 끝난 뒤 ax_dedup 이 대표 1건으로 묶음
            # (여기서 건너뛰면 목록에서 '사라진 공고'로 오인돼 접수마감 처리되고 다른 게시처 링크도 잃음)
            L(f"  - 접수중 {len(open_)}건")

            # 이 사이트에서 사라진(마감된) 공고 상태 갱신
            now = _now()
            seen = {x.project_no for x in open_}
            for pn, r in known.items():
                if ax_sources.source_of(pn) != key or pn in seen or "접수중" not in (r["status"] or ""):
                    continue
                ax_db.update_status(con, pn, "접수마감", "", now)     # 목록 전체를 확인했으므로 사라진 공고 = 마감
            con.commit()

            for i, n in enumerate(open_, 1):
                try:
                    src.fetch_detail(sess, n)
                    att_names = [a["name"] for a in n.attachments]
                    prev = known.get(n.project_no)
                    prev_att = [a["name"] for a in (json.loads(prev["attachments_json"] or "[]") if prev else [])]
                    if prev and not force and prev_att == att_names:
                        if "접수중" not in (prev["status"] or ""):
                            ax_db.update_status(con, n.project_no, "접수중", "", _now())
                        continue
                    L(f"  ({i}/{len(open_)}) 분석: {n.title[:40]}")
                    ndir = ax_db.FILES_DIR / n.project_no
                    raw = src.download(sess, n, ndir) if n.attachments else []
                    files = [p for p in eng.expand_files(raw) if p.suffix.lower() in eng.DOC_EXT]
                    docs = []
                    for f in files:
                        try:
                            d = eng.read_document(f)
                            if d.lines:
                                docs.append({"file_name": f.name, "file_path": str(f.relative_to(ax_db.DATA_DIR)),
                                             "text": doc_full_text(d), "n_tables": len(d.tables)})
                            else:
                                L(f"      ! {f.name}: 텍스트 없음(배포용/스캔 문서 가능)")
                        except Exception as e:
                            L(f"      ! {f.name}: {e}")
                    for e in n.errors:
                        L(f"      ! {e}")
                    rec = build_record(n, docs, source=key)
                    is_new = ax_db.upsert_notice(con, rec, _now())
                    ax_db.replace_documents(con, n.project_no, docs, ax_meta.make_chunks(n.sections, docs))
                    con.commit()
                    n_new += int(is_new); n_an += 1
                    L(f"      → {rec['summary']}")
                except Exception as e:
                    if eng._check_ssl_error(e):
                        raise
                    L(f"      ! 오류: {type(e).__name__}: {str(e)[:200]}")
        ax_dedup.mark_duplicates(con, log=L)
        L(f"[완료] 신규 {n_new}건 · 분석 {n_an}건")
    except Exception as e:
        if eng._check_ssl_error(e):
            L("! SSL 인증서 오류 — 'python -m pip install truststore' 설치 후 다시 실행하거나 --insecure 옵션을 사용하세요.")
        elif type(e).__name__ in ("ConnectionError", "ProxyError", "ConnectTimeout", "ReadTimeout", "Timeout"):
            L(f"! 사이트 접속 실패 — 인터넷 연결·방화벽·프록시 설정을 확인하세요. ({type(e).__name__})")
        else:
            L(f"! 수집 실패: {type(e).__name__}: {str(e)[:300]}")
            L("".join(traceback.format_exception_only(type(e), e))[:500])
    finally:
        con.execute("INSERT INTO runs (started_at, finished_at, n_list, n_new, n_analyzed, log) VALUES (?,?,?,?,?,?)",
                    (started, _now(), n_list, n_new, n_an, "\n".join(logs)))
        con.commit()
        con.close()
    return {"new": n_new, "analyzed": n_an, "log": logs}


def reanalyze(db_path=ax_db.DB_PATH, log=print) -> int:
    """다시 내려받지 않고 DB에 저장된 제목·상세페이지·첨부 텍스트로 지원대상(업종·지역)·요약을 다시 계산
    (판단 규칙을 고친 뒤 기존 공고에 바로 반영할 때)"""
    con = ax_db.connect(db_path)
    k = 0
    for r in con.execute("SELECT * FROM notices").fetchall():
        d = ax_db.row_to_notice(r)
        docs = [{"file_name": x["file_name"], "text": x["text"] or ""} for x in
                con.execute("SELECT file_name, text FROM documents WHERE project_no=?", (d["project_no"],))]
        src = d.get("source") or ax_sources.source_of(d["project_no"])
        n = eng.Notice(project_no=d["project_no"], title=d["title"] or "", region=d.get("region") or "",
                       status=d.get("status") or "", subtitle=d.get("subtitle") or "")
        n.sections = d.get("sections") or {}
        sec = n.sections
        main_doc = "\n".join(x["text"] for x in docs if not x["file_name"].lower().endswith((".xlsx", ".xlsm")))
        dsecs = ax_meta.doc_sections(main_doc)
        page_text = "\n".join(sec.values())
        doc_text = "\n".join(x["text"] for x in docs)
        target = ax_meta.extract_target(n.title, sec.get("지원대상", "") + "\n" + sec.get("사업개요", ""), page_text, doc_text,
                                        doc_target=dsecs.get("신청자격·지원대상", ""))
        if src != "jexport":
            apply_region(n, target, sec, dsecs, src)
        summary = ax_meta.make_summary(n.title, d.get("fields") or [], d.get("amount") or {}, target, d.get("receipt_end") or "")
        con.execute("UPDATE notices SET target_json=?, region=?, summary=? WHERE project_no=?",
                    (json.dumps(target, ensure_ascii=False), n.region or d.get("region"), summary, d["project_no"]))
        k += 1
    con.commit()
    ax_dedup.mark_duplicates(con, log=log)
    con.close()
    log(f"재분석 {k}건 (업종·지역·요약) 완료")
    return k


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="지원사업 공고 수집·분석 → DB 적재")
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="변경 여부와 관계없이 접수중 공고 전부 재분석")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--ca-bundle")
    ap.add_argument("--reanalyze", action="store_true", help="수집 없이 DB에 있는 공고의 업종·지역 판단만 다시 계산")
    ap.add_argument("--sources", help="수집 사이트 (쉼표 구분): " + ",".join(ax_sources.ORDER))
    a = ap.parse_args(argv)
    if a.reanalyze:
        reanalyze()
        return 0
    eng.REQUEST_DELAY = 0.5
    srcs = [x.strip() for x in a.sources.split(",")] if a.sources else None
    r = collect(a.max_pages, a.force, a.insecure, a.ca_bundle, sources=srcs)
    print(f"\nDB: {ax_db.DB_PATH}")
    return 0 if r["analyzed"] or r["new"] or not any(l.startswith("!") for l in r["log"]) else 2


if __name__ == "__main__":
    sys.exit(main())
