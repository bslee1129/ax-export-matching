# -*- coding: utf-8 -*-
"""④ 공고문 근거 기반 질의응답 (RAG, 폐쇄형)

1) 검색: 한국어 글자 2-gram BM25 로 공고 원문 조각(chunks) 중 관련도 상위 N개 선택 (외부 라이브러리 불필요)
2) 답변:
   - 로컬 LLM(Ollama) 사용 가능 시: 검색된 원문만 근거로 답하도록 제한, [근거 n] 인용 필수
   - 사용 불가 시: 관련 원문 문장을 그대로 발췌해서 제시 (거짓 답변 없음)
3) 모든 답변에 원문 링크·담당자 연락처 병기, 질문 속 민감정보는 마스킹 후 처리
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter

import ax_match

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("AX_LLM_MODEL", "")      # 비우면 설치된 모델 중 자동 선택
PREFERRED_MODELS = ["exaone", "qwen2.5", "qwen3", "gemma", "llama3"]


def _grams(text: str) -> list[str]:
    t = re.sub(r"[^\w가-힣]+", " ", (text or "").lower())
    out = []
    for w in t.split():
        if len(w) == 1:
            out.append(w)
        out += [w[i:i + 2] for i in range(len(w) - 1)]
    return out


class Index:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs = [Counter(_grams(c["heading"] + " " + c["text"])) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 1
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        N = len(self.docs) or 1
        self.idf = {g: math.log(1 + (N - f + 0.5) / (f + 0.5)) for g, f in df.items()}

    def search(self, query: str, k: int = 6, project_no: str | None = None) -> list[tuple[float, dict]]:
        q = Counter(_grams(query))
        scored = []
        for i, (d, ln) in enumerate(zip(self.docs, self.lens)):
            c = self.chunks[i]
            if project_no and c["project_no"] != project_no:
                continue
            s = 0.0
            for g in q:
                f = d.get(g)
                if f:
                    s += self.idf.get(g, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * ln / self.avg))
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]


# ── 로컬 LLM (Ollama)
def llm_status() -> dict:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=2) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return {"available": False, "models": [], "model": None,
                "message": "로컬 AI(Ollama) 미실행 — 원문 발췌 방식으로 답변합니다."}
    model = OLLAMA_MODEL if OLLAMA_MODEL in models else next(
        (m for pref in PREFERRED_MODELS for m in models if m.startswith(pref)), models[0] if models else None)
    return {"available": bool(model), "models": models, "model": model,
            "message": f"로컬 AI 사용: {model}" if model else "Ollama는 실행 중이나 설치된 모델이 없습니다 (예: ollama pull qwen2.5:3b)"}


def _ollama(model: str, prompt: str, timeout: int = 120) -> str:
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.1, "num_ctx": 8192}}).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read()).get("response", "").strip()


SYSTEM_RULES = """당신은 수출지원사업 상담을 돕는 행정 보조도구입니다. 아래 규칙을 반드시 지키세요.
1. 오직 [근거] 로 제공된 공고문 원문 내용만 사용해 답합니다. 원문에 없는 내용은 추측하지 말고 "공고문에서 확인되지 않습니다"라고 답합니다.
2. 문장마다 근거 번호를 [근거 1] 형식으로 표시합니다.
3. 금액·기한·자격요건은 원문 표현을 그대로 옮깁니다. 여러 사업의 조건을 섞지 않습니다.
4. 한국어로 간결하게(5문장 이내) 답합니다."""


def answer(question: str, index: Index, notices: dict, project_no: str | None = None,
           profile: dict | None = None, use_llm: bool = True) -> dict:
    q = ax_match.mask(question)
    hits = index.search(q, k=6, project_no=project_no)
    sources = []
    for i, (s, c) in enumerate(hits, 1):
        n = notices.get(c["project_no"], {})
        sources.append({"no": i, "project_no": c["project_no"], "title": n.get("title", ""),
                        "source": c["source"], "heading": c["heading"], "text": c["text"], "score": round(s, 2),
                        "detail_url": n.get("detail_url"),
                        "contact": (n.get("apply") or {}).get("contact", {}), "receipt_end": n.get("receipt_end"),
                        "status": n.get("status")})
    if not sources:
        return {"mode": "none", "answer": "관련 공고문 내용을 찾지 못했습니다. 질문을 바꾸거나 공고를 선택해 보세요.",
                "sources": [], "masked_question": q}

    # 핵심 공고(근거에 가장 많이 등장) 의 표준 메타데이터 요약 — DB에 정리된 값이라 신뢰도 높음
    top_pn = Counter(s["project_no"] for s in sources[:4]).most_common(1)[0][0]
    tn = notices.get(top_pn, {})
    ap, am = tn.get("apply") or {}, tn.get("amount") or {}
    fact = (f"📌 {tn.get('title','')} — 접수 {tn.get('receipt_start') or ''} ~ {tn.get('receipt_end') or ''} ({tn.get('status','')})"
            f" · 지원 {ax_match._amount_text(am)} · 신청 {', '.join(ap.get('methods', []))} {', '.join(ap.get('emails', []))}".rstrip())
    fact_ev = am.get("evidence", [])[:2]

    st = llm_status() if use_llm else {"available": False}
    if st.get("available"):
        ctx = "\n\n".join(f"[근거 {s['no']}] ({s['title']} / {s['source']} / {s['heading']}) "
                          f"접수마감 {s['receipt_end']} 상태 {s['status']}\n{s['text']}" for s in sources)
        prof = f"\n[기업 정보(익명)] {ax_match.profile_brief(profile)}" if profile else ""
        prompt = f"{SYSTEM_RULES}\n\n[공고 정리값] {fact}\n\n{ctx}{prof}\n\n[질문] {q}\n\n[답변]"
        try:
            txt = _ollama(st["model"], prompt)
            cited = sorted({int(x) for x in re.findall(r"근거\s*(\d+)", txt) if 0 < int(x) <= len(sources)})
            if not cited:
                txt += "\n\n※ AI 답변에 근거 표시가 없어 아래 원문을 반드시 확인하세요."
            return {"mode": "llm", "model": st["model"], "answer": txt, "fact": fact, "cited": cited, "sources": sources,
                    "masked_question": q}
        except Exception as e:
            st = {"available": False, "message": f"로컬 AI 호출 실패({e}) — 원문 발췌로 대체"}

    # 발췌형 답변 (LLM 없이): 검색된 모든 근거에서 질문과 가장 겹치는 문장 top 5 (희귀어 가중)
    qg = set(_grams(q))
    cand, seen = [], set()
    for s in sources:
        for l in (x.strip() for x in s["text"].splitlines()):
            key = re.sub(r"\s+", "", l)
            if len(key) < 6 or key in seen:
                continue
            seen.add(key)
            sc = sum(index.idf.get(g, 0) for g in qg & set(_grams(l))) + 0.3 / s["no"]
            cand.append((sc, s["no"], l))
    cand.sort(key=lambda x: -x[0])
    lines = [f"- {l} [근거 {no}]" for sc, no, l in cand[:5] if sc > 0.5]
    ev = "".join(f"\n   └ 원문: {e}" for e in fact_ev)
    return {"mode": "extract", "answer": f"{fact}{ev}\n\n질문과 관련된 공고문 원문 발췌:\n" + "\n".join(lines), "fact": fact,
            "sources": sources, "masked_question": q, "llm_message": st.get("message", "")}
