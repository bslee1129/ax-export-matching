# -*- coding: utf-8 -*-
"""① 데이터 수집 자동화: 수출e음 공고 수집 → 첨부 텍스트 추출 → 메타데이터 표준화 → DB 적재

사용
  python ax_collect.py                 # 목록 3페이지 확인, 접수중 공고 신규/변경분만 분석
  python ax_collect.py --force         # 접수중 공고 전부 다시 분석
  python ax_collect.py --insecure      # SSL 인증서 오류 시
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
    sec = n.sections or {}
    page_text = "\n".join(sec.values())
    target_text = sec.get("지원대상", "")
    method_text = next((v for k, v in sec.items() if "지원방법" in k or "제출서류" in k), "")
    doc_text = "\n".join(d["text"] for d in docs)
    start, end = eng._parse_period(n.detail.get("접수기간") or n.period)

    fields = ax_meta.extract_fields(n.title, page_text, doc_text)
    target = ax_meta.extract_target(n.title, target_text + "\n" + sec.get("사업개요", ""), page_text, doc_text)
    amount = ax_meta.extract_amount(page_text, doc_text)
    apply = ax_meta.extract_apply(method_text, n.detail, doc_text)
    main_doc = "\n".join(d["text"] for d in docs if not d["file_name"].lower().endswith((".xlsx", ".xlsm")))
    dsecs = ax_meta.doc_sections(main_doc)
    apply = ax_meta.enrich_apply(apply, dsecs, main_doc)
    return {
        "project_no": n.project_no, "source": source, "title": n.title, "subtitle": n.subtitle,
        "region": n.region, "status": n.status, "notice_period": n.detail.get("공고기간", ""),
        "receipt_start": start.isoformat() if start else None, "receipt_end": end.isoformat() if end else None,
        "early_close": int(bool(re.search(r"예산\s*소진", page_text + doc_text[:5000]))),
        "detail_url": f"{eng.DETAIL_URL}?project_no={n.project_no}",
        "fields": fields, "target": target, "amount": amount, "apply": apply, "sections": sec, "doc_sections": dsecs,
        "attachments": [{"name": a["name"], "files": [d["file_name"] for d in docs]} for a in n.attachments],
        "summary": ax_meta.make_summary(n.title, fields, amount, target, end.isoformat() if end else ""),
        "analyzed_at": _now(),
    }


def collect(max_pages: int = 3, force: bool = False, insecure: bool = False, ca_bundle: str | None = None,
            log=print, session=None, db_path=ax_db.DB_PATH) -> dict:
    started = _now()
    logs = []

    def L(msg):
        logs.append(msg)
        log(msg)

    sess = session or eng._session(insecure, ca_bundle)
    con = ax_db.connect(db_path)
    n_new = n_an = 0
    try:
        L(f"[1] 공고 목록 수집 (최대 {max_pages}페이지)")
        listing = []
        for page in range(1, max_pages + 1):
            url = eng.LIST_URL if page == 1 else eng.LIST_PAGE_URL
            rows = eng.parse_list_page(eng._get(sess, url, params={"page": page}).text)
            if not rows:
                break
            listing += rows
        open_ = [x for x in listing if "접수중" in x.status]
        L(f"  - 목록 {len(listing)}건 / 접수중 {len(open_)}건")

        # 상태 갱신 (DB에 있던 공고가 마감되었는지)
        known = {r["project_no"]: dict(r) for r in con.execute("SELECT project_no, status, attachments_json FROM notices")}
        now = _now()
        for x in listing:
            if x.project_no in known and known[x.project_no]["status"] != x.status:
                ax_db.update_status(con, x.project_no, x.status, x.period, now)
                L(f"  · 상태변경: {x.title[:30]} → {x.status}")
        seen = {x.project_no for x in listing}
        for pn, r in known.items():
            if pn not in seen and "접수중" in (r["status"] or ""):
                # 목록 범위 밖으로 밀려난 공고: 접수기간으로 판단
                end = con.execute("SELECT receipt_end FROM notices WHERE project_no=?", (pn,)).fetchone()[0]
                if end and end < dt.date.today().isoformat():
                    ax_db.update_status(con, pn, "접수마감(추정)", "", now)
        con.commit()

        L("[2] 접수중 공고 상세·첨부 분석")
        for i, n in enumerate(open_, 1):
            try:
                eng.fetch_detail(sess, n)
                att_names = [a["name"] for a in n.attachments]
                prev = known.get(n.project_no)
                prev_att = [a["name"] for a in (json.loads(prev["attachments_json"] or "[]") if prev else [])]
                if prev and not force and prev_att == att_names:
                    L(f"  ({i}/{len(open_)}) 변경없음: {n.title[:40]}")
                    continue
                L(f"  ({i}/{len(open_)}) 분석: {n.title[:40]}")
                ndir = ax_db.FILES_DIR / n.project_no
                raw = eng.download_attachments(sess, n, ndir) if n.attachments else []
                files = [p for p in eng.expand_files(raw) if p.suffix.lower() in eng.DOC_EXT]
                docs = []
                for f in files:
                    try:
                        d = eng.read_document(f)
                        if d.lines:
                            docs.append({"file_name": f.name, "file_path": str(f.relative_to(ax_db.DATA_DIR)),
                                         "text": doc_full_text(d), "n_tables": len(d.tables)})
                            L(f"      ✓ {f.name} (문단 {len(d.lines)} · 표 {len(d.tables)})")
                        else:
                            L(f"      ! {f.name}: 텍스트 없음(배포용/스캔 문서 가능)")
                    except Exception as e:
                        L(f"      ! {f.name}: {e}")
                rec = build_record(n, docs)
                is_new = ax_db.upsert_notice(con, rec, _now())
                ax_db.replace_documents(con, n.project_no, docs, ax_meta.make_chunks(n.sections, docs))
                con.commit()
                n_new += int(is_new); n_an += 1
                L(f"      → {rec['summary']}")
            except Exception as e:
                if eng._check_ssl_error(e):
                    raise
                L(f"      ! 오류: {type(e).__name__}: {e}")
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
                    (started, _now(), 0, n_new, n_an, "\n".join(logs)))
        con.commit()
        con.close()
    return {"new": n_new, "analyzed": n_an, "log": logs}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="수출e음 공고 수집·분석 → DB 적재")
    ap.add_argument("--max-pages", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="변경 여부와 관계없이 접수중 공고 전부 재분석")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--ca-bundle")
    a = ap.parse_args(argv)
    eng.REQUEST_DELAY = 0.5
    r = collect(a.max_pages, a.force, a.insecure, a.ca_bundle)
    print(f"\nDB: {ax_db.DB_PATH}")
    return 0 if r["analyzed"] or r["new"] or not any(l.startswith("!") for l in r["log"]) else 2


if __name__ == "__main__":
    sys.exit(main())
