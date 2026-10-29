# -*- coding: utf-8 -*-
"""PC에서 공고 수집 → GitHub 웹페이지에 올리기 (Git 프로그램 없이 GitHub API 사용)

기업마당·KOTRA 는 해외(GitHub 서버) 접속을 막는 경우가 있어 한국 PC에서 수집해 올립니다.

  python pc_sync.py                     # 최신 DB 받기 → 5개 사이트 수집 → 웹 데이터 생성 → GitHub 업로드 → 구독 회원 메일 발송 결과 확인
  python pc_sync.py --sources bizinfo   # 일부 사이트만
  python pc_sync.py --no-upload         # 업로드 없이 PC에서만 수집

  python pc_sync.py --upload-only       # 수집은 끝났고 업로드만 다시 할 때
  python pc_sync.py --update-only       # 프로그램(코드)만 GitHub 최신으로 업데이트

실행할 때마다 먼저 GitHub 의 최신 프로그램(코드)으로 자동 업데이트합니다 (data/·토큰 파일은 건드리지 않음).

GitHub 토큰(처음 한 번 입력, 이 PC의 github_token.txt 에만 저장 — 저장소에는 올라가지 않음)
  https://github.com/settings/personal-access-tokens/new
  → Repository access: Only select repositories → ax-export-matching
  → Permissions → Repository permissions → Contents: Read and write → Generate token
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = "bslee1129/ax-export-matching"
BRANCH = "main"
API = "https://api.github.com"
TOKEN_FILE = BASE / "github_token.txt"
UPLOAD = ["data/ax_notices.db", "docs/data/notices.json", "docs/data/chunks.json", "docs/data/meta.json"]


def _session(insecure: bool):
    if not insecure:
        try:
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass
    import requests
    s = requests.Session()
    s.headers.update({"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                      "User-Agent": "ax-export-matching-pc-sync"})
    if insecure:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        s.verify = False
    return s


def check_token(s, t: str) -> str:
    """토큰으로 저장소에 쓰기 권한이 있는지 확인. 문제 있으면 이유 문자열, 정상이면 ''"""
    if not t.startswith(("github_pat_", "ghp_")):
        return "토큰 형식이 아닙니다 (github_pat_ 또는 ghp_ 로 시작해야 함)"
    r = s.get(f"{API}/repos/{REPO}", headers={"Authorization": f"Bearer {t}"}, timeout=30)
    if r.status_code == 401:
        return "GitHub 이 토큰을 인식하지 못합니다 (복사가 잘못됐거나 만료·삭제된 토큰)"
    if r.status_code == 404:
        return "이 토큰으로 ax-export-matching 저장소에 접근할 수 없습니다 (Repository access 에서 저장소 선택 필요)"
    r.raise_for_status()
    # 세분화 토큰은 저장소 정보에 사용자 권한이 나오므로, 실제 쓰기는 작은 blob 생성으로 확인 (커밋되지 않음)
    w = s.post(f"{API}/repos/{REPO}/git/blobs", headers={"Authorization": f"Bearer {t}"},
               json={"content": "token-check", "encoding": "utf-8"}, timeout=30)
    if w.status_code in (403, 404):
        return ("토큰에 쓰기 권한이 없습니다 — GitHub 토큰 설정에서 Repository permissions → "
                "Contents 를 'Read and write' 로 바꾸고 Update 하세요 (토큰 문자열은 그대로 사용 가능)")
    w.raise_for_status()
    return ""


def _token(s) -> str:
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if not t and TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
    if t:
        why = check_token(s, t)
        if not why:
            return t
        print(f"\n[!] 저장된 토큰 문제: {why}")
    print("\n[GitHub 토큰 입력] 처음 한 번만 합니다. 만드는 방법은 README 참고.")
    print("  https://github.com/settings/personal-access-tokens/new")
    print("  (붙여넣기: 이 창에서 마우스 오른쪽 클릭 또는 Ctrl+V)")
    for _ in range(3):
        t = input("  토큰 붙여넣고 Enter: ").strip().strip('"').strip("'")
        why = check_token(s, t) if t else "입력이 비어 있습니다"
        if not why:
            TOKEN_FILE.write_text(t, encoding="utf-8")
            print(f"  ✓ 토큰 확인 완료 — {TOKEN_FILE.name} 에 저장했습니다 (이 PC에만 보관)")
            return t
        print(f"  [!] {why}. 다시 입력하세요.")
    return ""


# 자동 업데이트에서 건드리지 않는 것: 공고 데이터·웹 데이터·토큰·실행 중인 .bat
KEEP_LOCAL = ("data/", "docs/data/", "github_token.txt", "notify_preview/", ".git/")
ALL_SOURCES = "jexport,jbexport,at,kotra,bizinfo"
OLD_DEFAULT_SOURCES = {"jexport,at,kotra,bizinfo"}       # 예전 .bat 이 넘기던 값 → 전체 사이트로 처리


def update_code(s) -> list[str]:
    """GitHub main 의 최신 프로그램 파일로 이 폴더를 업데이트. 바뀐 파일 목록을 돌려줌"""
    r = s.get(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}", timeout=180)
    r.raise_for_status()
    changed = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            if not rel or rel.startswith(KEEP_LOCAL):
                continue
            if rel.lower().endswith(".bat"):       # 실행 중인 배치파일을 덮어쓰면 창이 오작동 → 내용이 다를 때만 .new 로 저장
                dst = BASE / rel
                data = z.read(info)
                if dst.exists() and dst.read_bytes() != data:
                    (BASE / (rel + ".new")).write_bytes(data)
                continue
            data = z.read(info)
            dst = BASE / rel
            if dst.exists() and dst.read_bytes() == data:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            changed.append(rel)
    return changed


def download_db(s):
    """GitHub 의 최신 공고 DB 받기 (매일 자동 수집 결과와 합치기 위해)"""
    url = f"https://github.com/{REPO}/raw/{BRANCH}/data/ax_notices.db"
    r = s.get(url, timeout=120)
    r.raise_for_status()
    p = BASE / "data" / "ax_notices.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.content)
    print(f"  ✓ 최신 DB 받음 ({len(r.content) / 1e6:.1f} MB)")


class TokenError(Exception):
    pass


def upload_with_retry(s, token: str, message: str):
    """업로드 중 토큰 만료·권한 오류가 나면 그 자리에서 새 토큰을 받아 다시 올림 (수집 결과는 그대로 사용)"""
    for _ in range(2):
        try:
            return upload(s, token, message)
        except TokenError as e:
            print(f"\n[!] {e}")
            print("    토큰이 만료됐거나(유효기간 지남) 삭제·권한 변경된 것 같습니다. 새 토큰을 입력하면 수집한 데이터를 바로 올립니다.")
            print("    ※ 토큰 만들 때 Expiration 을 길게(예: 1년, Custom) 하면 자주 바꾸지 않아도 됩니다.")
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()
            os.environ.pop("GITHUB_TOKEN", None)
            token = _token(s)
            if not token:
                break
    raise SystemExit("[!] 업로드하지 못했습니다. 새 토큰을 만든 뒤 'PC업로드만.bat' 을 실행하면 수집한 데이터를 올립니다 (다시 수집할 필요 없음).")


NOTIFY_WF = "notify.yml"


def _last_notify(s, token: str) -> dict:
    """GitHub 의 data/notify_last.json (최근 메일 발송 결과 — 건수만)"""
    r = s.get(f"{API}/repos/{REPO}/contents/data/notify_last.json", params={"ref": BRANCH},
              headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if not r.ok:
        return {}
    import json
    return json.loads(base64.b64decode(r.json().get("content", "")).decode("utf-8"))


def wait_notify(s, token: str, sha: str | None, timeout: int = 480):
    """업로드 뒤 GitHub 이 구독 회원에게 메일을 보내는 작업(맞춤 공고 메일 알림)이 끝날 때까지 기다렸다가 결과 표시"""
    print("[5/5] 구독 회원 메일 알림 (GitHub 에서 자동 발송 — 결과 확인 중, 보통 1~2분)")
    if not sha:
        print("  - 새로 올린 데이터가 없어 이번에는 알림 메일이 없습니다.")
        return
    t0, run, shown = time.time(), None, None
    while time.time() - t0 < timeout:
        time.sleep(15)
        try:
            r = s.get(f"{API}/repos/{REPO}/actions/workflows/{NOTIFY_WF}/runs",
                      params={"head_sha": sha, "per_page": 5}, timeout=30)
            if r.status_code in (401, 403, 429):
                r = s.get(r.url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            runs = r.json().get("workflow_runs", []) if r.ok else []
        except Exception:
            runs = []
        if not runs:
            continue
        run = runs[0]
        if run.get("status") != "completed":
            if run.get("status") != shown:
                shown = run.get("status")
                print("  - " + {"queued": "대기 중 (자동 수집이 돌고 있으면 그게 끝난 뒤 바로 발송합니다)",
                                "waiting": "대기 중", "pending": "대기 중",
                                "in_progress": "발송 작업 진행 중…"}.get(shown, shown))
            continue
        if run.get("conclusion") != "success":
            print(f"  [!] 메일 알림 작업이 실패했습니다 — {run.get('html_url')} 화면을 캡처해 Claude 에게 보여 주세요.")
            return
        time.sleep(3)
        d = {}
        try:
            d = _last_notify(s, token)
        except Exception:
            pass
        if not d or d.get("data_commit") != sha[:7]:
            print(f"  ✓ 메일 알림 작업 완료 — 결과: {run.get('html_url')}")
        elif d.get("error"):
            print(f"  [!] 알림 서버 오류: {d['error']} — 구글 Apps Script 배포 상태를 확인하세요.")
        elif d.get("skipped"):
            print("  [!] 알림 서버가 설정되지 않아 메일을 보내지 않았습니다 (GitHub Secrets AX_NOTIFY_URL·AX_NOTIFY_KEY).")
        elif d.get("sent"):
            print(f"  ✓ 구독 회원 {d.get('subscribers')}명 중 {d['sent']}명에게 새 맞춤 공고 메일을 보냈습니다 (공고 {d.get('new_items')}건).")
        else:
            print(f"  ✓ 구독 회원 {d.get('subscribers')}명 — 새로 알릴 맞춤 공고(적합도 70점↑)가 없어 이번엔 메일이 없습니다.")
        return
    url = run.get("html_url") if run else f"https://github.com/{REPO}/actions"
    print(f"  - 아직 끝나지 않았습니다. 창을 닫아도 GitHub 에서 계속 진행되어 메일이 발송됩니다 (진행 상황: {url})")


def upload(s, token: str, message: str):
    """변경 파일들을 커밋 1개로 업로드 (Git Data API)"""
    h = {"Authorization": f"Bearer {token}"}

    def call(method, path, **kw):
        r = s.request(method, f"{API}/repos/{REPO}/{path}", headers=h, timeout=300, **kw)
        if r.status_code in (401, 403, 404):
            raise TokenError(f"GitHub 권한 오류({r.status_code}): {r.text[:150]}")
        r.raise_for_status()
        return r.json()

    for attempt in range(3):
        ref = call("GET", f"git/ref/heads/{BRANCH}")
        head = ref["object"]["sha"]
        base_tree = call("GET", f"git/commits/{head}")["tree"]["sha"]
        tree = []
        for rel in UPLOAD:
            f = BASE / rel
            if not f.exists():
                continue
            blob = call("POST", "git/blobs", json={"content": base64.b64encode(f.read_bytes()).decode(), "encoding": "base64"})
            tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = call("POST", "git/trees", json={"base_tree": base_tree, "tree": tree})
        if new_tree["sha"] == base_tree:
            print("  - 변경 없음 — 올릴 내용이 없습니다.")
            return None
        commit = call("POST", "git/commits", json={"message": message, "tree": new_tree["sha"], "parents": [head]})
        r = s.patch(f"{API}/repos/{REPO}/git/refs/heads/{BRANCH}", headers=h, json={"sha": commit["sha"]}, timeout=60)
        if r.status_code == 422 and attempt < 2:          # 그 사이 다른 커밋(자동 수집)이 올라옴 → 다시 시도
            print("  - GitHub 에 새 커밋이 있어 다시 시도합니다…")
            time.sleep(3)
            continue
        r.raise_for_status()
        print(f"  ✓ GitHub 업로드 완료 (커밋 {commit['sha'][:7]})")
        return commit["sha"]
    raise SystemExit("[!] 업로드 실패 — 잠시 후 다시 실행하세요.")


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="PC 공고 수집 → GitHub 웹페이지 업로드")
    ap.add_argument("--sources", default="jexport,jbexport,at,kotra,bizinfo")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-download", action="store_true", help="GitHub DB 받지 않고 PC의 DB 그대로 사용")
    ap.add_argument("--insecure", action="store_true", help="SSL 인증서 오류 시")
    ap.add_argument("--upload-only", action="store_true", help="수집 없이 PC에 있는 데이터만 업로드")
    ap.add_argument("--update-only", action="store_true", help="프로그램만 최신으로 업데이트")
    ap.add_argument("--no-update", action="store_true", help="프로그램 자동 업데이트 생략")
    a = ap.parse_args(argv)
    if a.sources.replace(" ", "") in OLD_DEFAULT_SOURCES:
        a.sources = ALL_SOURCES

    s = _session(a.insecure)
    if not a.no_update and not os.environ.get("AX_UPDATED"):
        print("[0] 프로그램 최신 버전 확인 (GitHub)")
        try:
            changed = update_code(s)
        except Exception as e:
            changed = []
            print(f"  [!] 업데이트 확인 실패 — 지금 프로그램으로 계속합니다 ({type(e).__name__})")
        if changed:
            print(f"  ✓ {len(changed)}개 파일 업데이트: {', '.join(changed[:8])}{' …' if len(changed) > 8 else ''}")
            if "requirements.txt" in changed:
                subprocess.call([sys.executable, "-m", "pip", "install", "-q", "-r", str(BASE / "requirements.txt")])
            # 새 프로그램으로 다시 실행
            env = dict(os.environ, AX_UPDATED="1")
            return subprocess.call([sys.executable, str(BASE / "pc_sync.py")] + list(argv if argv is not None else sys.argv[1:]), env=env)
        print("  ✓ 최신 버전입니다")
    if a.update_only:
        return 0
    token = "" if a.no_upload else _token(s)
    if not a.no_upload and not token:
        raise SystemExit("[!] 토큰이 없어 업로드할 수 없습니다. (--no-upload 로 PC 수집만 가능)")

    if a.upload_only:
        print("[업로드만] PC에 있는 공고 데이터를 GitHub 에 올립니다")
        sha = upload_with_retry(s, token, f"PC 수집 공고 데이터 갱신 {time.strftime('%Y-%m-%d %H:%M')}")
        wait_notify(s, token, sha)
        print(f"\n완료! 1~2분 뒤 웹페이지에 반영됩니다: https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/")
        return 0

    print("[1/5] GitHub 최신 공고 DB 받기")
    if not a.no_download:
        download_db(s)

    print("[2/5] 공고 수집 — 처음에는 10~20분 걸릴 수 있습니다")
    sys.path.insert(0, str(BASE))
    import ax_collect
    import jexport_engine as eng
    eng.REQUEST_DELAY = 0.5
    r = ax_collect.collect(3, False, True, None, sources=[x.strip() for x in a.sources.split(",") if x.strip()])

    print("[3/5] 웹페이지 데이터 만들기")
    import export_static
    e = export_static.export()
    print(f"  ✓ 공고 {e['notices']}건 (접수중 {e['open']}건)")

    if a.no_upload:
        print("[4/5] 업로드 생략 (--no-upload)")
        return 0
    print("[4/5] GitHub 에 올리기")
    sha = upload_with_retry(s, token, f"PC 수집 공고 데이터 갱신 {time.strftime('%Y-%m-%d %H:%M')} (신규 {r['new']}건)")
    wait_notify(s, token, sha)
    print(f"\n완료! 1~2분 뒤 웹페이지에 반영됩니다: https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
