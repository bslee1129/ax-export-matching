# AI 기반 수출지원사업 맞춤형 매칭 플랫폼 (PoC)

전남광주 지역 영세·수출초보기업의 정보 격차 해소를 위해, 수출지원사업 공고를 **자동 수집·분석**하고 기업 프로필에 맞는 사업을 **근거와 함께 추천**하는 웹페이지입니다.

- 🌐 웹페이지: GitHub Pages (`docs/` 폴더) — 저장소 Settings › Pages 에 표시된 주소
- 🔄 데이터 갱신: GitHub Actions가 **매일 08:40(한국시간)** 수출e음·전북 수출통합지원시스템·aT수출종합지원시스템·KOTRA 무역투자24·기업마당(수출 분야) 공고 수집 → `docs/data/` 갱신 → 구독 회원에게 맞춤 공고 메일
- 🔒 기업 프로필·추천 결과는 서버로 전송되지 않고 **사용자 브라우저(localStorage)에만 저장** (메일 알림 회원 정보는 운영자 구글 시트에만 저장)

## 구성

```
.github/workflows/collect.yml   매일 자동 수집 → 중복 묶기 → 메일 알림 (수동 실행: Actions › 공고 자동 수집 › Run workflow)
.github/workflows/notify.yml    PC에서 올린 경우의 메일 알림
ax_collect.py                   사이트별 목록 → 접수중 공고 상세·첨부(HWP/HWPX/PDF/ZIP) 수집·분석
ax_sources.py                   수집 사이트별 목록·상세·첨부 수집기 (jexport·jbexport·at·kotra·bizinfo)
ax_dedup.py                     사이트 간 같은 공고 묶기 (첨부 본문·파일명·제목·마감일 비교)
ax_notify.py                    구독 회원별 맞춤 공고 메일 (적합도 70점↑ 새 공고)
gas/Code.gs                     회원가입·메일 발송 서버 (구글 Apps Script, 운영자 계정에 배포)
jexport_engine.py               크롤러 + HWP/HWPX 표(병합셀) 파서
ax_meta.py                      메타데이터 표준화 (지원분야·대상·금액·기한·신청방법 + 원문 근거)
ax_match.py / ax_rag.py         적합도 매칭 엔진 / 원문 근거 검색(RAG) — 로컬 실행용
export_static.py                DB → 웹페이지용 JSON (docs/data/notices.json, chunks.json, meta.json)
data/ax_notices.db              공고 DB (Actions가 갱신)
docs/                           GitHub Pages 웹페이지 (index.html, engine.js = 매칭·검색 엔진 JS 버전, config.js = 알림 서버 주소)
ax_server.py + local_web/       내 PC에서 실행하는 로컬 버전
```

## 웹페이지 기능

| 탭 | 기능 |
|---|---|
| 대시보드·알림 | 접수중 공고 수, 14일 내 마감, 등록 기업별 맞춤 알림(적합도 **70점↑** 중 마감 임박·신규) |
| 기업 맞춤 추천 | 기업 프로필 입력 → 적합도 0~100점, 부적합 사유, 판단 근거(원문 문장), 신청 페이지 바로가기 / 엑셀 템플릿으로 여러 기업 일괄 등록, 추천결과 엑셀 다운로드 |
| 공고 DB | 접수중·전체 공고 목록, 지원분야·대상·금액·신청방법 정리, 상세페이지 원문, 같은 공고의 다른 게시처 |
| 알림 신청 | 이메일 + 조건(소재지·업종·필요분야·희망국·키워드) 등록 → 확인 메일 → 매일 수집 후 적합도 70점↑ 새 공고 메일 |
| 데이터 현황 | 최근 갱신 시각, 수집 실행 기록 링크 |

### 적합도 점수
지원분야 40 + 업종 20 + 지역 10 + 희망국가 10 + 신청기한 10 + 수출단계·실적 10 (+특례·우선지원 가점 5).
지역·업종·규모·상장·직수출·마감 요건 불충족은 **부적합**으로 분리.

대상 **업종**은 7분류 — 농수산 · 식품 · 화장품(뷰티) · 공예품 · 생활용품(소비재) · 의료기기 · 기타 공산품(기계·부품·전자·소재·IT 등). 공고가 '소비재'면 식품·화장품·생활용품·공예품, '제조기업·공산품'이면 제조 업종 전체로 봅니다. 농수산 기업은 식품 공고에도 추천됩니다. 예전 프로필 값(농산·수산·공산품)은 자동 변환됩니다.

대상 **업종·지역**은 ① 공고 **제목**(예: `[경기]`, `강원 ○○`, `김제시 ○○`, `○○지역 기업`, `화장품`·`농식품`·`자동차부품`) ② 상세페이지 지원대상 ③ 첨부 공고문의 '신청자격·지원대상' 순으로 판단하고, 어디서 판단했는지(제목/지원대상)와 근거 문장을 화면에 표시합니다. 행사 개최지(예: '부산 국제 전시회')는 지역 요건으로 보지 않습니다. 규칙을 고친 뒤 기존 공고에 반영: `python ax_collect.py --reanalyze` 배점·키워드는 `docs/engine.js`(웹)와 `ax_match.py`/`ax_meta.py`(수집)에서 수정합니다.

## PC에서 수집해 올리기 (기업마당·KOTRA)

기업마당·KOTRA 사이트는 해외(GitHub 서버) 접속을 막거나 끊는 경우가 있어, 매일 자동 수집에서 빠질 수 있습니다.
이때는 한국에 있는 PC에서 `PC수집_업로드.bat` 을 더블클릭하면 다섯 사이트를 모두 수집해 웹페이지에 올립니다(`pc_sync.py`). 올린 뒤 회원 메일 알림은 GitHub Actions(notify.yml)가 자동으로 보냅니다.

- 필요: Python. Git 프로그램은 필요 없습니다(GitHub API로 업로드)
- 처음 한 번 GitHub 토큰 입력 — https://github.com/settings/personal-access-tokens/new 에서
  Repository access: Only select repositories → ax-export-matching / Permissions → Contents: Read and write
  (토큰은 이 PC의 `github_token.txt` 에만 저장되고 저장소에는 올라가지 않습니다)
- 순서: 프로그램 자동 업데이트 → GitHub 최신 DB 받기 → 수집 → 웹 데이터 생성 → 커밋 1개로 업로드 → **구독 회원 메일 발송**(GitHub 이 자동 실행, PC 창에 '구독 회원 N명 중 M명에게 메일 발송' 결과 표시)
- 일부 사이트만: `PC수집_업로드.bat --sources bizinfo,kotra` 또는 `python pc_sync.py --sources bizinfo`

## 운영 메모

- 수집 실패 시(사이트 점검·접속 차단 등) 기존 데이터가 유지되며, Actions 탭에 실패 기록이 남습니다. 해외 서버(GitHub)에서 사이트 접속이 막히는 경우 내 PC에서 `python ax_collect.py` → `python export_static.py` 실행 후 `data/`, `docs/data/`를 커밋하면 됩니다.
- 메타데이터는 규칙 기반 추출입니다. 신청 전 반드시 공고 원문을 확인하세요.
- 공고 데이터 출처
  - 수출e음 (https://www.jexport.or.kr/user/reg_biz)
  - 전북특별자치도 수출통합지원시스템 '전북특별자치도 지원사업' (https://www.jbexport.or.kr/other/spWork/spWorkSupportBusiness/view1.do) — 지역 요건: 제목·'도내' 문구가 있으면 전북 기업만
  - aT수출종합지원시스템 사업신청 (https://global.at.or.kr/front/bizReq/brList.do)
  - KOTRA 무역투자24 사업신청 (https://www.kotra.or.kr/subList/20000020753)
  - 중기부 기업마당 지원사업 공고, 지원분야 '수출' (https://www.bizinfo.go.kr)
- 수집 범위는 전국입니다. 지자체 공고([경기] 등)는 해당 시·도 기업에만 추천합니다(기업 프로필의 소재지 기준).
- 같은 공고가 여러 사이트에 올라온 경우(제목이 달라도 첨부 공고문 본문·파일명이 같고 마감일이 같으면) 수출e음 → 전북 → aT → KOTRA → 기업마당 순으로 **대표 1건만 추천·알림**하고, 나머지는 '다른 게시처'로 표시합니다(`ax_dedup.py`, 확인: `python ax_dedup.py`).
- 일부 사이트만 수집: `python ax_collect.py --sources at,kotra`

## 메일 알림 설정 (처음 한 번, 운영자)

회원가입·메일 발송은 운영자 Google 계정의 **Apps Script**(무료)가 맡습니다. 회원 이메일은 운영자 구글 시트에만 저장되고 공개 저장소에는 올라가지 않습니다(발송 기록 `data/notify_state.json`에는 이메일 대신 해시만 저장).

1. https://script.google.com → **새 프로젝트** → `gas/Code.gs` 내용을 붙여넣고 저장
2. 함수 `setup` 선택 → **실행** → 권한 허용 → 실행 로그에 나온 **알림 키** 복사 (회원 명부 구글 시트가 자동 생성됨)
3. **배포 › 새 배포** → 유형 **웹 앱** / 실행 사용자 **나** / 액세스 **모든 사용자** → **웹 앱 URL** 복사
4. GitHub 저장소 **Settings › Secrets and variables › Actions › New repository secret**
   - `AX_NOTIFY_URL` = 웹 앱 URL
   - `AX_NOTIFY_KEY` = 알림 키
5. `docs/config.js` 의 `notifyUrl` 에 같은 웹 앱 URL 입력 후 커밋 → 웹페이지 **알림 신청** 탭이 활성화됨
6. 확인: 알림 신청 탭에서 본인 메일로 신청 → 확인 메일의 버튼 클릭 → Actions › **맞춤 공고 메일 알림** › Run workflow (첫 메일: 지금 신청 가능한 맞춤 공고)

- 발송 한도: 일반 Gmail 계정 하루 100명(Workspace 1,500명). 메일 내용 미리보기: `python ax_notify.py --dry-run`
- 카카오 알림톡은 카카오 비즈니스 채널 + 발송대행사(유료) 계약과 사전 승인된 메시지 템플릿이 필요해 이번 버전은 메일로 보냅니다. 계약 후 `ax_notify.py` 의 발송부에 대행사 API를 추가하면 됩니다.
