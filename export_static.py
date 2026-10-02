# -*- coding: utf-8 -*-
"""공고 DB(SQLite) → 정적 웹페이지용 JSON (docs/data/)

  python export_static.py          # data/ax_notices.db → docs/data/*.json

GitHub Actions(.github/workflows/collect.yml)가 매일 수집 후 실행합니다.
웹페이지에는 공개 공고 정보만 들어가며, 기업 프로필은 각 사용자의 브라우저에만 저장됩니다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import ax_db
import ax_meta

OUT = Path(__file__).resolve().parent / "docs" / "data"

KEEP = ["project_no", "source", "title", "subtitle", "region", "status", "notice_period", "receipt_start",
        "receipt_end", "early_close", "detail_url", "summary", "first_seen", "last_seen", "analyzed_at",
        "fields", "target", "amount", "apply", "sections", "attachments"]


def export(db_path=ax_db.DB_PATH, out: Path = OUT, include_closed_days: int = 60) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    con = ax_db.connect(db_path)
    today = dt.date.today()
    cutoff = (today - dt.timedelta(days=include_closed_days)).isoformat()
    notices = []
    for n in ax_db.get_notices(con):
        # 접수중 + 최근 마감(기본 60일) 공고만 게시
        if "접수중" not in (n.get("status") or "") and (n.get("receipt_end") or "") < cutoff:
            continue
        d = {k: n.get(k) for k in KEEP}
        rows = list(con.execute("SELECT file_name, n_tables, text FROM documents WHERE project_no=?", (n["project_no"],)))
        d["documents"] = [dict(file_name=r["file_name"], n_tables=r["n_tables"], n_chars=len(r["text"] or "")) for r in rows]
        # 공고문(한글파일) 본문 → 항목별 주요 내용 + 신청방법 보완 (기존 DB도 재수집 없이 반영)
        main_doc = "\n".join(r["text"] or "" for r in rows if not r["file_name"].lower().endswith((".xlsx", ".xlsm")))
        d["doc_sections"] = ax_meta.doc_sections(main_doc)
        d["apply"] = ax_meta.enrich_apply(d.get("apply") or {}, d["doc_sections"], main_doc)
        notices.append(d)
    keep_pn = {n["project_no"] for n in notices}
    chunks = [{"p": c["project_no"], "s": c["source"], "h": c["heading"], "t": c["text"]}
              for c in ax_db.all_chunks(con) if c["project_no"] in keep_pn]
    run = ax_db.last_run(con) or {}
    meta = {
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "last_run": {k: run.get(k) for k in ("started_at", "finished_at", "n_new", "n_analyzed")},
        "count_open": sum("접수중" in (n["status"] or "") for n in notices),
        "count_total": len(notices),
        "fields": ax_meta.FIELDS,
        "source": "수출e음 (https://www.jexport.or.kr/user/reg_biz)",
        "repo": os.environ.get("GITHUB_REPOSITORY", ""),
    }
    con.close()
    (out / "notices.json").write_text(json.dumps(notices, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"notices": len(notices), "chunks": len(chunks), "open": meta["count_open"]}


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    r = export()
    print(f"docs/data 갱신: 공고 {r['notices']}건(접수중 {r['open']}) · 검색조각 {r['chunks']}개")
