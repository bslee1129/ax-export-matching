# -*- coding: utf-8 -*-
"""① 데이터 수집 자동화: 지원사업 공고 수집 → 첨부 텍스트 추출 → 메타데이터 표준화 → DB 적재

수집 사이트: 수출e음(jexport) · aT수출종합지원시스템(at) · KOTRA 무역투자24(kotra) · 기업마당 수출분야(bizinfo)

사용
  python ax_collect.py                          # 전체 사이트, 접수중 공고 신규/변경분만 분석
  python ax_collect.py --sources jexport,kotra  # 일부 사이트만
  python ax_collect.py --force                  # 접수중 공고 전부 다시 분석
  python ax_collect.py --insecure               # SSL 인증서 오류 시
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


def build_record(n, docs: list[dict], source: str = "jexport") -> dict:
    src = ax_sources.SOURCES.get(source)
    sec = n.sections or {}
    page_text = "\n".join(sec.values())
    target_text = sec.get("지원대상", "")
    method_text = next((v for k, v in sec.items() if "지원방법" in k or "제출서류" in k), "")
    doc_text = "\n".join(d["text"] for d in docs)
    start, end = eng._parse_period(n.detail.get("접수기간") or n.period)

    fields = ax_meta.extract_fields(n.title, page_text, doc_text)
    target = ax_meta.extract_target(n.title, target_text + "\n" + sec.get("사업개요", ""), page_text, doc_text)
    amount = ax_meta.extract_amount(page_text, doc_text)
    apply = ax_meta.extract_apply(method_text, n.detail, doc_text, online=src.online_method if src else "")
    main_doc = "\n".join(d["text"] for d in docs if not d["file_name"].lower().endswith((".xlsx", ".xlsm")))
    dsecs = ax_meta.doc_sections(main_doc)
    apply = ax_meta.enrich_apply(apply, dsecs, main_doc)
    if source != "jexport":
        # 전국 사이트: 지역 요건은 제목 [지역]·소관 지자체로만 판단 (본문에 '광주 개최' 등이 있어도 지역 제한 아님)
        target["regions"] = ([] if n.region in ("", "전국") else
                             ["전남", "광주"] if n.region in ax_sources.HOME_REGIONS else [n.region])
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
    taken = {}      # 정규화 제목 → project_no (사이트 간 중복 공고 제거)
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
            # 중복 제거 (기업마당 등에 재게시된 타기관 공고)
            uniq = []
            for x in open_:
                t = ax_sources._norm_title(x.title)
                dup = taken.get(t) if len(t) >= 8 else None
                if dup and dup != x.project_no:
                    continue
                taken.setdefault(t, x.project_no)
                uniq.append(x)
            if len(uniq) < len(open_):
                L(f"  - 다른 사이트와 중복된 공고 {len(open_) - len(uniq)}건 제외")
            open_ = uniq
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
    ap.add_argument("--sources", help="수집 사이트 (쉼표 구분): " + ",".join(ax_sources.ORDER))
    a = ap.parse_args(argv)
    eng.REQUEST_DELAY = 0.5
    srcs = [x.strip() for x in a.sources.split(",")] if a.sources else None
    r = collect(a.max_pages, a.force, a.insecure, a.ca_bundle, sources=srcs)
    print(f"\nDB: {ax_db.DB_PATH}")
    return 0 if r["analyzed"] or r["new"] or not any(l.startswith("!") for l in r["log"]) else 2


if __name__ == "__main__":
    sys.exit(main())
