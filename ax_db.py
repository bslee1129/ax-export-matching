# -*- coding: utf-8 -*-
"""공고 DB (SQLite, 표준 라이브러리만 사용)

테이블
  notices   : 공고 1건 = 1행. 표준화된 메타데이터(분야·대상·금액·기한·신청방법)와 근거 문장 JSON
  documents : 첨부파일별 추출 텍스트
  chunks    : 검색(RAG)용 문단 조각 — 공고 원문 근거 인용에 사용
  profiles  : 기업 프로필
  runs      : 수집 실행 이력
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("AX_DATA_DIR") or (BASE_DIR / "data"))
DB_PATH = DATA_DIR / "ax_notices.db"
FILES_DIR = DATA_DIR / "files"

SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    project_no     TEXT PRIMARY KEY,
    source         TEXT,           -- 수집 출처 (jexport 등)
    title          TEXT,
    subtitle       TEXT,
    region         TEXT,
    status         TEXT,           -- 접수중 / 접수마감 / 사업종료 ...
    notice_period  TEXT,
    receipt_start  TEXT,
    receipt_end    TEXT,
    early_close    INTEGER DEFAULT 0,
    detail_url     TEXT,
    fields_json    TEXT,           -- 지원분야 [{field, score, evidence}]
    target_json    TEXT,           -- 지원대상 조건 {industries, company_types, regions, excludes, ...}
    amount_json    TEXT,           -- {max_manwon, rate, evidence}
    apply_json     TEXT,           -- {methods, emails, phones, contact, lines}
    sections_json  TEXT,           -- 상세페이지 원문 섹션
    summary        TEXT,
    attachments_json TEXT,
    first_seen     TEXT,
    last_seen      TEXT,
    analyzed_at    TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_no  TEXT,
    file_name   TEXT,
    file_path   TEXT,
    text        TEXT,
    n_tables    INTEGER,
    UNIQUE(project_no, file_name)
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_no  TEXT,
    source      TEXT,              -- '상세페이지' 또는 첨부파일명
    seq         INTEGER,
    heading     TEXT,
    text        TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_pn ON chunks(project_no);
CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT,
    data_json   TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT,
    finished_at TEXT,
    n_list      INTEGER,
    n_new       INTEGER,
    n_analyzed  INTEGER,
    log         TEXT
);
"""


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), check_same_thread=False, timeout=15)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


@contextmanager
def session(path: Path | str = DB_PATH):
    con = connect(path)
    try:
        yield con
        con.commit()
    finally:
        con.close()


JSON_COLS = ("fields_json", "target_json", "amount_json", "apply_json", "sections_json", "attachments_json")


def row_to_notice(r: sqlite3.Row) -> dict:
    d = dict(r)
    for c in JSON_COLS:
        d[c[:-5]] = json.loads(d.pop(c) or "null")
    return d


def get_notices(con, status: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM notices", []
    if status and status not in ("전체", "all"):
        q += " WHERE status LIKE ?"
        args.append(f"%{status}%")
    q += " ORDER BY (receipt_end IS NULL), receipt_end"
    out = [row_to_notice(r) for r in con.execute(q, args)]
    import ax_meta
    for n in out:   # 신청방법이 비어 있으면 공고문(한글파일) 내용으로 보완
        if (n.get("apply") or {}).get("methods", ["공고문 참조"]) == ["공고문 참조"]:
            docs = [r[0] or "" for r in con.execute(
                "SELECT text FROM documents WHERE project_no=? AND lower(file_name) NOT LIKE '%.xls%'", (n["project_no"],))]
            main_doc = "\n".join(docs)
            n["apply"] = ax_meta.enrich_apply(n.get("apply") or {}, ax_meta.doc_sections(main_doc), main_doc)
    return out


def get_notice(con, project_no: str) -> dict | None:
    r = con.execute("SELECT * FROM notices WHERE project_no=?", (project_no,)).fetchone()
    if not r:
        return None
    d = row_to_notice(r)
    rows = [dict(x) for x in con.execute(
        "SELECT id, file_name, file_path, n_tables, text FROM documents WHERE project_no=?", (project_no,))]
    d["documents"] = [{**{k: v for k, v in r.items() if k != "text"}, "n_chars": len(r["text"] or "")} for r in rows]
    # 공고문(한글파일) 항목별 주요 내용 + 신청방법 보완
    import ax_meta
    main_doc = "\n".join(r["text"] or "" for r in rows if not r["file_name"].lower().endswith((".xlsx", ".xlsm")))
    d["doc_sections"] = ax_meta.doc_sections(main_doc)
    d["apply"] = ax_meta.enrich_apply(d.get("apply") or {}, d["doc_sections"], main_doc)
    return d


def upsert_notice(con, n: dict, now: str):
    old = con.execute("SELECT first_seen FROM notices WHERE project_no=?", (n["project_no"],)).fetchone()
    first_seen = old["first_seen"] if old else now
    cols = ["project_no", "source", "title", "subtitle", "region", "status", "notice_period", "receipt_start",
            "receipt_end", "early_close", "detail_url", "summary", "analyzed_at"]
    vals = [n.get(c) for c in cols]
    for c in JSON_COLS:
        cols.append(c)
        vals.append(json.dumps(n.get(c[:-5]), ensure_ascii=False))
    cols += ["first_seen", "last_seen"]
    vals += [first_seen, now]
    ph = ",".join("?" * len(cols))
    upd = ",".join(f"{c}=excluded.{c}" for c in cols if c not in ("project_no", "first_seen"))
    con.execute(f"INSERT INTO notices ({','.join(cols)}) VALUES ({ph}) "
                f"ON CONFLICT(project_no) DO UPDATE SET {upd}", vals)
    return old is None


def update_status(con, project_no: str, status: str, period: str, now: str):
    con.execute("UPDATE notices SET status=?, last_seen=? WHERE project_no=?", (status, now, project_no))


def replace_documents(con, project_no: str, docs: list[dict], chunks: list[dict]):
    con.execute("DELETE FROM documents WHERE project_no=?", (project_no,))
    con.execute("DELETE FROM chunks WHERE project_no=?", (project_no,))
    con.executemany("INSERT INTO documents (project_no, file_name, file_path, text, n_tables) VALUES (?,?,?,?,?)",
                    [(project_no, d["file_name"], d["file_path"], d["text"], d["n_tables"]) for d in docs])
    con.executemany("INSERT INTO chunks (project_no, source, seq, heading, text) VALUES (?,?,?,?,?)",
                    [(project_no, c["source"], c["seq"], c["heading"], c["text"]) for c in chunks])


def all_chunks(con, project_no: str | None = None) -> list[dict]:
    if project_no:
        rows = con.execute("SELECT * FROM chunks WHERE project_no=? ORDER BY seq", (project_no,))
    else:
        rows = con.execute("SELECT * FROM chunks")
    return [dict(r) for r in rows]


# ── 기업 프로필
def list_profiles(con) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM profiles ORDER BY id"):
        d = json.loads(r["data_json"])
        d["id"], d["updated_at"] = r["id"], r["updated_at"]
        out.append(d)
    return out


def save_profile(con, p: dict, now: str) -> int:
    data = {k: v for k, v in p.items() if k not in ("id", "updated_at")}
    if p.get("id"):
        con.execute("UPDATE profiles SET name=?, data_json=?, updated_at=? WHERE id=?",
                    (p.get("name", ""), json.dumps(data, ensure_ascii=False), now, int(p["id"])))
        return int(p["id"])
    cur = con.execute("INSERT INTO profiles (name, data_json, updated_at) VALUES (?,?,?)",
                      (p.get("name", ""), json.dumps(data, ensure_ascii=False), now))
    return cur.lastrowid


def delete_profile(con, pid: int):
    con.execute("DELETE FROM profiles WHERE id=?", (pid,))


def last_run(con) -> dict | None:
    r = con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None
