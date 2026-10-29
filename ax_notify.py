# -*- coding: utf-8 -*-
"""맞춤 공고 메일 알림 — 공고 수집 후 구독 회원별로 '적합도 70점↑ 새 공고'를 메일로 보냅니다.

  python ax_notify.py              # 구독자 조건으로 매칭 → 새 공고가 있는 회원에게 메일
  python ax_notify.py --dry-run    # 보내지 않고 메일 내용을 notify_preview/ 에 HTML 로 저장
  python ax_notify.py --test       # 알림 서버(구글 Apps Script) 연결만 확인

필요한 설정 (GitHub Secrets 또는 환경변수)
  AX_NOTIFY_URL  구글 Apps Script 웹 앱 URL (gas/Code.gs 배포 주소)
  AX_NOTIFY_KEY  Apps Script setup 실행 시 나온 알림 키

동작
  - 공고: docs/data/notices.json 의 접수중 대표 공고(다른 사이트 중복 제외)
  - 회원 조건(소재지·업종·필요분야·희망국·키워드 등)으로 ax_match 적합도 계산 → min_score(기본 70)점 이상
  - 이미 보낸 공고는 data/notify_state.json 에 기록해 다시 보내지 않음 (이메일 대신 해시만 저장 — 공개 저장소 대비)
  - 처음 받는 회원에게는 '지금 신청 가능한 맞춤 공고'를 모아 한 번 보냄
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import os
import sys
from pathlib import Path

import ax_match

BASE = Path(__file__).resolve().parent
NOTICES = BASE / "docs" / "data" / "notices.json"
STATE = BASE / "data" / "notify_state.json"
SITE = os.environ.get("AX_SITE_URL", "https://bslee1129.github.io/ax-export-matching/")
SRCN = {"jexport": "수출e음", "jbexport": "전북 수출통합지원시스템", "at": "aT수출종합지원시스템",
        "kotra": "KOTRA 무역투자24", "bizinfo": "기업마당"}
MAX_ITEMS = 15


def _h(s) -> str:
    return html.escape(str(s if s is not None else ""))


def sub_key(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"subs": {}}


def save_state(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    # 마감 지난 공고 기록은 정리 (파일이 계속 커지지 않게)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def profile_from(cond: dict) -> dict:
    p = dict(cond or {})
    for k in ("industries", "needs", "keywords", "sources"):
        v = p.get(k)
        if isinstance(v, str):
            p[k] = [x.strip() for x in v.split(",") if x.strip()]
    p["industries"] = ax_match.ax_meta.normalize_industries(p.get("industries") or [])
    p["export_usd"] = float(p.get("export_usd") or 0)
    p["direct_export"] = bool(p.get("direct_export", True))
    p["listed"] = bool(p.get("listed", False))
    return p


def pick(cond: dict, notices: list[dict], today: dt.date) -> list[dict]:
    """회원 조건에 맞는 공고 (적합도 min_score↑, 키워드·출처 조건)"""
    p = profile_from(cond)
    min_score = max(ax_match.ALERT_MIN_SCORE, int(p.get("min_score") or ax_match.ALERT_MIN_SCORE))
    kws = [k.lower() for k in p.get("keywords") or []]
    srcs = set(p.get("sources") or [])
    by = {n["project_no"]: n for n in notices}
    out = []
    for r in ax_match.match(p, notices, today, include_ineligible=False):
        n = by[r["project_no"]]
        if r["score"] < min_score:
            continue
        if srcs and n.get("source") not in srcs:
            continue
        if kws:
            hay = " ".join([n.get("title", ""), n.get("summary", ""), " ".join(r["fields"]),
                            " ".join((n.get("sections") or {}).values())[:3000]]).lower()
            if not any(k in hay for k in kws):
                continue
        r["source"] = n.get("source")
        r["also"] = n.get("also") or []
        out.append(r)
    return out


def render(sub: dict, items: list[dict], first: bool, today: dt.date) -> tuple[str, str]:
    name = sub.get("name") or ""
    head = (f"지금 신청 가능한 맞춤 공고 {len(items)}건" if first else f"새 맞춤 공고 {len(items)}건")
    subject = f"[AX 수출지원] {head} ({today.isoformat()})"
    rows = []
    for r in items[:MAX_ITEMS]:
        dd = "" if r["d_day"] is None else (f"D-{r['d_day']}" if r["d_day"] > 0 else "오늘 마감")
        why = " · ".join(x["text"] for x in r["reasons"] if x["type"] == "+")[:220]
        warn = " · ".join(x["text"] for x in r["warnings"])
        also = " · ".join(f'<a href="{_h(a["detail_url"])}">{_h(SRCN.get(a["source"], a["source"]))}</a>' for a in r["also"])
        rows.append(f"""<tr><td style="padding:10px 8px;border-bottom:1px solid #e5e9f0;vertical-align:top;width:52px;text-align:center">
          <div style="font-size:20px;font-weight:800;color:#1f4e79">{r['score']}</div><div style="font-size:11px;color:#666">{_h(r['grade'])}</div></td>
          <td style="padding:10px 8px;border-bottom:1px solid #e5e9f0">
          <a href="{_h(r['detail_url'])}" style="font-weight:700;color:#1c2533;text-decoration:none">{_h(r['title'])}</a>
          <div style="font-size:12px;color:#555;margin-top:3px">{_h(SRCN.get(r.get('source'), ''))} · 마감 {_h(r['receipt_end'] or '상시')} <b style="color:#b3261e">{dd}</b> · {_h(r['amount'])} · {_h(', '.join(r['fields']))}</div>
          <div style="font-size:12px;color:#1e7b46;margin-top:3px">✓ {_h(why)}</div>
          {f'<div style="font-size:12px;color:#9a6700">⚠ {_h(warn)}</div>' if warn else ''}
          {f'<div style="font-size:12px;color:#666">같은 공고 다른 게시처: {also}</div>' if also else ''}
          <div style="margin-top:6px"><a href="{_h(r['detail_url'])}" style="font-size:12px;background:#1f4e79;color:#fff;padding:4px 10px;border-radius:5px;text-decoration:none">공고·신청 바로가기</a></div></td></tr>""")
    more = f"<p style='color:#666'>외 {len(items) - MAX_ITEMS}건은 웹페이지에서 확인하세요.</p>" if len(items) > MAX_ITEMS else ""
    body = f"""<div style="font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;max-width:680px;margin:0 auto;color:#1c2533">
      <div style="background:#1f4e79;color:#fff;padding:14px 18px;border-radius:8px 8px 0 0"><b>AX 수출지원사업 맞춤 알림</b><br>
      <span style="font-size:13px;opacity:.85">{_h(name + '님 · ' if name else '')}{head}</span></div>
      <table style="width:100%;border-collapse:collapse">{''.join(rows)}</table>{more}
      <p style="font-size:12px;color:#666;line-height:1.6;margin-top:14px">적합도는 등록하신 조건(소재지·업종·필요분야·희망국가 등)과 공고문을 규칙으로 비교한 참고 점수입니다.
      신청 전 반드시 공고문 원문의 자격요건을 확인하세요. <a href="{_h(SITE)}">웹페이지에서 전체 보기</a><br>
      더 이상 받지 않으려면 <a href="{_h(sub.get('unsubscribe_url', ''))}">알림 해지</a></p></div>"""
    return subject, body


def call(url: str, payload: dict) -> dict:
    import requests
    r = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "text/plain;charset=utf-8"}, timeout=120)
    r.raise_for_status()
    return r.json()


def run(dry_run: bool = False, today: dt.date | None = None, subscribers: list | None = None, log=print) -> dict:
    url, key = os.environ.get("AX_NOTIFY_URL", "").strip(), os.environ.get("AX_NOTIFY_KEY", "").strip()
    if subscribers is None and (not url or not key):
        log("알림 서버(AX_NOTIFY_URL·AX_NOTIFY_KEY) 미설정 — 메일 알림을 건너뜁니다. (README '메일 알림 설정' 참고)")
        return {"sent": 0, "skipped": True}
    today = today or (dt.datetime.utcnow() + dt.timedelta(hours=9)).date()
    notices = [n for n in json.loads(NOTICES.read_text(encoding="utf-8"))
               if "접수중" in (n.get("status") or "") and not n.get("dup_of")]
    if subscribers is None:
        res = call(url, {"action": "list", "key": key})
        if not res.get("ok"):
            log(f"! 구독자 목록 조회 실패: {res.get('error')}")
            return {"sent": 0, "error": res.get("error")}
        subscribers = res.get("subscribers") or []
        log(f"구독 회원 {len(subscribers)}명 · 오늘 남은 발송 한도 {res.get('quota')}")
    st = load_state()
    open_pn = {n["project_no"] for n in notices}
    msgs, plan = [], []
    for sub in subscribers:
        k = sub_key(sub["email"])
        rec = st["subs"].get(k)
        first = rec is None
        sent = set((rec or {}).get("sent", []))
        items = [r for r in pick(sub.get("conditions") or {}, notices, today) if r["project_no"] not in sent]
        if not items:
            continue
        subject, body = render(sub, items, first, today)
        msgs.append({"to": sub["email"], "subject": subject, "html": body})
        plan.append((k, [r["project_no"] for r in items]))
        log(f"  - 회원 {k[:6]}…: {'첫 알림 ' if first else ''}{len(items)}건 (최고 {items[0]['score']}점)")
    if dry_run:
        out = BASE / "notify_preview"
        out.mkdir(exist_ok=True)
        for i, m in enumerate(msgs, 1):
            (out / f"{i:02d}.html").write_text(f"<h3>{_h(m['to'])} — {_h(m['subject'])}</h3>{m['html']}", encoding="utf-8")
        log(f"[미리보기] 메일 {len(msgs)}통 → {out}")
        return {"sent": 0, "preview": len(msgs)}
    n_sent = 0
    ok_to = set()
    for i in range(0, len(msgs), 20):
        res = call(url, {"action": "send", "key": key, "messages": msgs[i:i + 20]})
        ok_to |= {x.lower() for x in res.get("sent", [])}
        for f in res.get("failed", []):
            log(f"  ! 발송 실패: {sub_key(f.get('to', ''))[:6]}… {f.get('error')}")
    for (k, pns), m in zip(plan, msgs):
        if m["to"].lower() in ok_to:
            rec = st["subs"].setdefault(k, {"sent": [], "since": today.isoformat()})
            rec["sent"] = sorted((set(rec["sent"]) & open_pn) | set(pns))     # 마감된 공고 기록은 정리
            rec["last"] = today.isoformat()
            n_sent += 1
    for sub in subscribers:          # 맞는 공고가 없어도 회원 기록은 시작 (다음부터 '새 공고'만)
        st["subs"].setdefault(sub_key(sub["email"]), {"sent": [], "since": today.isoformat()})
    save_state(st)
    log(f"[완료] 메일 {n_sent}통 발송")
    return {"sent": n_sent}


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="맞춤 공고 메일 알림")
    ap.add_argument("--dry-run", action="store_true", help="보내지 않고 notify_preview/ 에 미리보기 저장")
    ap.add_argument("--test", action="store_true", help="알림 서버 연결 확인")
    a = ap.parse_args(argv)
    if a.test:
        url, key = os.environ.get("AX_NOTIFY_URL", ""), os.environ.get("AX_NOTIFY_KEY", "")
        print(call(url, {"action": "test", "key": key}) if url and key else "AX_NOTIFY_URL·AX_NOTIFY_KEY 를 설정하세요")
        return 0
    run(a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
