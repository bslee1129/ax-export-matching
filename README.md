# AI 기반 수출지원사업 맞춤형 매칭 플랫폼 (PoC)

전남광주 지역 영세·수출초보기업의 정보 격차 해소를 위해, 수출지원사업 공고를 **자동 수집·분석**하고 기업 프로필에 맞는 사업을 **근거와 함께 추천**하는 웹페이지입니다.

- 🌐 웹페이지: GitHub Pages (`docs/` 폴더) — 저장소 Settings › Pages 에 표시된 주소
- 🔄 데이터 갱신: GitHub Actions가 **매일 08:40(한국시간)** 수출e음 공고 수집 → `docs/data/` 갱신
- 🔒 기업 프로필·추천 결과는 서버로 전송되지 않고 **사용자 브라우저(localStorage)에만 저장**

## 구성

```
.github/workflows/collect.yml   매일 자동 수집 (수동 실행: Actions › 공고 자동 수집 › Run workflow)
ax_collect.py                   수출e음 목록 → 접수중 공고 상세·첨부(HWP/HWPX/PDF/ZIP) 수집·분석
jexport_engine.py               크롤러 + HWP/HWPX 표(병합셀) 파서
ax_meta.py                      메타데이터 표준화 (지원분야·대상·금액·기한·신청방법 + 원문 근거)
ax_match.py / ax_rag.py         적합도 매칭 엔진 / 원문 근거 검색(RAG) — 로컬 실행용
export_static.py                DB → 웹페이지용 JSON (docs/data/notices.json, chunks.json, meta.json)
data/ax_notices.db              공고 DB (Actions가 갱신)
docs/                           GitHub Pages 웹페이지 (index.html, engine.js = 매칭·검색 엔진 JS 버전)
ax_server.py + local_web/       내 PC에서 실행하는 로컬 버전
```

## 웹페이지 기능

| 탭 | 기능 |
|---|---|
| 대시보드·알림 | 접수중 공고 수, 14일 내 마감, 등록 기업별 맞춤 알림(추천 60점↑ 중 마감 임박·신규) |
| 기업 맞춤 추천 | 기업 프로필 입력 → 적합도 0~100점, 부적합 사유, 판단 근거(원문 문장), 신청 페이지 바로가기 / 엑셀 템플릿으로 여러 기업 일괄 등록, 추천결과 엑셀 다운로드 |
| 공고 DB | 접수중·전체 공고 목록, 지원분야·대상·금액·신청방법 정리, 상세페이지 원문 |
| 데이터 현황 | 최근 갱신 시각, 수집 실행 기록 링크 |

### 적합도 점수
지원분야 40 + 업종 20 + 지역 10 + 희망국가 10 + 신청기한 10 + 수출단계·실적 10 (+특례·우선지원 가점 5).
지역·업종·규모·상장·직수출·마감 요건 불충족은 **부적합**으로 분리. 배점·키워드는 `docs/engine.js`(웹)와 `ax_match.py`/`ax_meta.py`(수집)에서 수정합니다.

## 운영 메모

- 수집 실패 시(사이트 점검·접속 차단 등) 기존 데이터가 유지되며, Actions 탭에 실패 기록이 남습니다. 해외 서버(GitHub)에서 사이트 접속이 막히는 경우 내 PC에서 `python ax_collect.py` → `python export_static.py` 실행 후 `data/`, `docs/data/`를 커밋하면 됩니다.
- 메타데이터는 규칙 기반 추출입니다. 신청 전 반드시 공고 원문을 확인하세요.
- 공고 데이터 출처: 전남광주통합특별시 수출e음 (https://www.jexport.or.kr)
