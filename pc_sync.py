# -*- coding: utf-8 -*-
"""PC에서 공고 수집 → GitHub 웹페이지에 올리기 (Git 프로그램 없이 GitHub API 사용)

기업마당·KOTRA 는 해외(GitHub 서버) 접속을 막는 경우가 있어 한국 PC에서 수집해 올립니다.

  python pc_sync.py                     # 최신 DB 받기 → 5개 사이트 수집 → 웹 데이터 생성 → GitHub 업로드
  python pc_sync.py --sources bizinfo   # 일부 사이트만
  python pc_sync.py --no-upload         # 업로드 없이 PC에서만 수집

  python pc_sync.py --upload-only       # 수집은 끝났고 업로드만 다시 할 때

GitHub 토큰(처음 한 번 입력, 이 PC의 github_token.txt 에만 저장 — 저장소에는 올라가지 않음)
  https://github.com/settings/personal-access-tokens/new
  → Repository access: Only select repositories → ax-export-matching
  → Permissions → Repository permissions → Contents: Read and write → Generate token
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
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


def download_db(s):
    """GitHub 의 최신 공고 DB 받기 (매일 자동 수집 결과와 합치기 위해)"""
    url = f"https://github.com/{REPO}/raw/{BRANCH}/data/ax_notices.db"
    r = s.get(url, timeout=120)
    r.raise_for_status()
    p = BASE / "data" / "ax_notices.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.content)
    print(f"  ✓ 최신 DB 받음 ({len(r.content) / 1e6:.1f} MB)")


def upload(s, token: str, message: str):
    """변경 파일들을 커밋 1개로 업로드 (Git Data API)"""
    h = {"Authorization": f"Bearer {token}"}

    def call(method, path, **kw):
        r = s.request(method, f"{API}/repos/{REPO}/{path}", headers=h, timeout=300, **kw)
        if r.status_code in (401, 403, 404):
            raise SystemExit(f"\n[!] GitHub 권한 오류({r.status_code}). 토큰이 만료됐거나 권한(Contents: Read and write)이 없습니다.\n"
                             f"    {TOKEN_FILE.name} 파일을 지우고 다시 실행해 새 토큰을 입력하세요.\n    {r.text[:200]}")
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
            return
        commit = call("POST", "git/commits", json={"message": message, "tree": new_tree["sha"], "parents": [head]})
        r = s.patch(f"{API}/repos/{REPO}/git/refs/heads/{BRANCH}", headers=h, json={"sha": commit["sha"]}, timeout=60)
        if r.status_code == 422 and attempt < 2:          # 그 사이 다른 커밋(자동 수집)이 올라옴 → 다시 시도
            print("  - GitHub 에 새 커밋이 있어 다시 시도합니다…")
            time.sleep(3)
            continue
        r.raise_for_status()
        print(f"  ✓ GitHub 업로드 완료 (커밋 {commit['sha'][:7]})")
        return
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
    a = ap.parse_args(argv)

    s = _session(a.insecure)
    token = "" if a.no_upload else _token(s)
    if not a.no_upload and not token:
        raise SystemExit("[!] 토큰이 없어 업로드할 수 없습니다. (--no-upload 로 PC 수집만 가능)")

    if a.upload_only:
        print("[업로드만] PC에 있는 공고 데이터를 GitHub 에 올립니다")
        upload(s, token, f"PC 수집 공고 데이터 갱신 {time.strftime('%Y-%m-%d %H:%M')}")
        print(f"\n완료! 1~2분 뒤 웹페이지에 반영됩니다: https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/")
        return 0

    print("[1/4] GitHub 최신 공고 DB 받기")
    if not a.no_download:
        download_db(s)

    print("[2/4] 공고 수집 — 처음에는 10~20분 걸릴 수 있습니다")
    sys.path.insert(0, str(BASE))
    import ax_collect
    import jexport_engine as eng
    eng.REQUEST_DELAY = 0.5
    r = ax_collect.collect(3, False, True, None, sources=[x.strip() for x in a.sources.split(",") if x.strip()])

    print("[3/4] 웹페이지 데이터 만들기")
    import export_static
    e = export_static.export()
    print(f"  ✓ 공고 {e['notices']}건 (접수중 {e['open']}건)")

    if a.no_upload:
        print("[4/4] 업로드 생략 (--no-upload)")
        return 0
    print("[4/4] GitHub 에 올리기")
    upload(s, token, f"PC 수집 공고 데이터 갱신 {time.strftime('%Y-%m-%d %H:%M')} (신규 {r['new']}건)")
    print(f"\n완료! 1~2분 뒤 웹페이지에 반영됩니다: https://{REPO.split('/')[0]}.github.io/{REPO.split('/')[1]}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
