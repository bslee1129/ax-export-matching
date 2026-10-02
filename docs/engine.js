/* AX 수출지원사업 매칭 엔진 (브라우저용) — ax_match.py · ax_rag.py 와 같은 규칙
 * 기업 정보는 서버로 전송되지 않고 이 브라우저 안에서만 계산됩니다. */
(function (root) {
  'use strict';
  const INDUSTRY_COMPAT = { '농산': ['농산', '식품'], '수산': ['수산', '식품'], '식품': ['식품'], '공산품': ['공산품'], '기타': [] };
  const COUNTRY_GROUP = {
    '중동': ['중동', 'UAE', '사우디', '카타르', '쿠웨이트', '이스라엘', '튀르키예', '터키', '이란', '이라크', '오만', '바레인', '요르단'],
    '동남아': ['동남아', '베트남', '태국', '인도네시아', '말레이시아', '필리핀', '싱가포르', '캄보디아', '미얀마'],
    '미주': ['미주', '미국', '캐나다', '멕시코', '브라질', '칠레'],
    '유럽': ['유럽', '독일', '프랑스', '영국', '네덜란드', '이탈리아', '스페인', '폴란드'],
    '중화권': ['중화권', '중국', '대만', '홍콩'],
    '일본': ['일본', '나고야', '도쿄', '오사카'],
  };
  const sorted = a => [...a].sort((x, y) => (x < y ? -1 : x > y ? 1 : 0));
  const countryGroups = text => new Set(Object.keys(COUNTRY_GROUP).filter(g => COUNTRY_GROUP[g].some(w => (text || '').includes(w))));
  const inter = (a, b) => new Set([...a].filter(x => b.has(x)));

  function dday(end, today) {
    if (!end) return null;
    const a = new Date(end.slice(0, 10) + 'T00:00:00'), b = new Date(today + 'T00:00:00');
    if (isNaN(a)) return null;
    return Math.round((a - b) / 864e5);
  }
  function fmtMan(v) { return v >= 1000 ? `${Math.round(v / 100).toLocaleString()}백만원` : `${Math.round(v).toLocaleString()}만원`; }
  function amountText(a) {
    if (!a || !a.max_manwon) return '공고문 참조';
    let s = '최대 ' + fmtMan(a.max_manwon);
    if (a.special_max_manwon) s += ` (특례 ${fmtMan(a.special_max_manwon)})`;
    if (a.rate) s += ` · ${a.rate}% 이내`;
    return s;
  }

  function scoreNotice(p, n, today) {
    const t = n.target || {};
    const fields = (n.fields || []).map(f => f.field);
    const reasons = [], fails = [], warns = [];
    let score = 0;
    const plus = (pts, text, ev = '') => { score += pts; reasons.push({ type: '+', points: pts, text, evidence: ev }); };
    const firstText = (t.text || []).slice(0, 1).join(' / ');
    const hqEv = ((t.requires || []).find(r => r.rule.includes('본사')) || {}).evidence || '';

    const d = dday(n.receipt_end, today);
    if (!(n.status || '').includes('접수중') || (d !== null && d < 0))
      fails.push({ text: `접수 마감 (${n.receipt_end || n.status})`, evidence: '' });
    const regions = t.regions || [];
    if (regions.length && p.region && !regions.includes(p.region))
      fails.push({ text: `지역 요건 불일치 (공고: ${regions.join('·')} / 기업: ${p.region})`, evidence: hqEv });
    for (const ex of t.excludes || [])
      if (ex.rule.includes('상장') && p.listed) fails.push({ text: '상장기업은 지원 제외', evidence: ex.evidence });
    const ctypes = t.company_types || [];
    const distributor = ctypes.includes('해외 유통매장 운영사');
    if (ctypes.includes('중소기업') && !distributor && ['중견기업', '대기업'].includes(p.size))
      fails.push({ text: `중소기업 대상 사업 (기업규모: ${p.size})`, evidence: firstText });
    for (const rq of t.requires || [])
      if (rq.rule.includes('직수출') && p.direct_export === false) fails.push({ text: '직수출 기업만 지원 (현재 간접수출)', evidence: rq.evidence });
    const nInd = new Set(t.industries || []), pInd = new Set(p.industries || []);
    if (nInd.size && pInd.size) {
      const compat = new Set([...pInd].flatMap(x => INDUSTRY_COMPAT[x] || [x]));
      if (!inter(compat, nInd).size)
        fails.push({ text: `업종 불일치 (공고: ${sorted(nInd).join('·')} / 기업: ${sorted(pInd).join('·')})`, evidence: firstText });
    }
    if (distributor && !p.is_overseas_distributor)
      warns.push({ text: "직접 신청 대상은 '해외 유통매장 운영사' — 국내 수출기업은 컨소시엄(입점기업)으로 참여 검토", evidence: firstText });

    const needs = new Set(p.needs || []);
    if (needs.size) {
      const hit = fields.filter(f => needs.has(f));
      if (hit.length && hit[0] === fields[0]) plus(40, `필요 분야 일치: ${hit.join(', ')}`, ((n.fields[0].evidence || [''])[0]) || '');
      else if (hit.length) {
        const f = n.fields.find(f => hit.includes(f.field) && (f.evidence || []).length);
        plus(28, `필요 분야 일부 일치: ${hit.join(', ')}`, f ? f.evidence[0] : '');
      } else reasons.push({ type: '-', points: 0, text: `필요 분야와 다름 (공고 분야: ${fields.join(', ') || '미분류'})`, evidence: '' });
    } else plus(20, '필요 분야 미입력 — 기본 점수');

    if (nInd.size && pInd.size && !fails.some(f => f.text.includes('업종'))) plus(20, `업종 일치: ${sorted(nInd).join('·')}`, firstText);
    else if (!nInd.size) plus(12, '업종 제한 없음');

    if (regions.length && regions.includes(p.region)) plus(10, `지역 요건 충족 (${p.region})`, hqEv);
    else if (!regions.length) plus(6, '지역 제한 명시 없음');

    const pG = countryGroups(p.target_countries || '');
    const nG = countryGroups((t.countries || []).join(' ') + ' ' + (n.title || ''));
    const both = inter(pG, nG);
    if (pG.size && nG.size && both.size) plus(10, `희망 수출국 일치: ${sorted(both).join(', ')}`, n.title || '');
    else if (!nG.size) plus(5, '국가 제한 없음');
    else reasons.push({ type: '-', points: 0, text: `공고 대상 국가: ${sorted(nG).join(', ')}`, evidence: '' });
    const am = n.amount || {};
    const sp = inter(pG, countryGroups((am.special_countries || []).join(' ')));
    if (sp.size) plus(5, `희망국(${sorted(sp).join(', ')}) 특례 한도 적용 가능`, (am.evidence || []).slice(0, 1).join(' / '));
    for (const pf of t.prefers || [])
      if (inter(countryGroups(pf.rule), pG).size) plus(5, `우선지원 대상: ${pf.rule}`, pf.evidence);

    if (d !== null && d >= 0) {
      if (d >= 7) plus(10, `신청 가능 (D-${d})`);
      else { plus(6, `마감 임박 (D-${d}) — 서둘러 신청`); warns.push({ text: `마감 임박: D-${d}`, evidence: '' }); }
    }
    if (n.early_close) warns.push({ text: '예산 소진 시 조기 마감 — 조기 신청 권장', evidence: '' });

    const usd = p.export_usd;
    if ((t.tiers || []).length && usd !== undefined && usd !== null && usd !== '') {
      const u = Number(usd) || 0;
      const rate = u >= 50000 ? 100 : u >= 30000 ? 50 : 30;
      plus(rate === 100 ? 10 : 6, `수출실적 ${u.toLocaleString()}달러 → 지원비율 약 ${rate}% 구간`, t.tiers[0].evidence);
    } else {
      const all = Object.values(n.sections || {}).join(' ') + (n.title || '');
      if ((p.export_stage || '').startsWith('수출 준비') && /소량|초보|첫\s*수출|내수/.test(all)) plus(10, '수출초보·소량수출 기업 적합');
      else plus(7, '수출단계 제한 없음');
    }

    score = Math.min(score, 100);
    if (distributor && !p.is_overseas_distributor) score = Math.min(score, 45);
    const eligible = !fails.length;
    if (!eligible) score = 0;
    const grade = !eligible ? '부적합' : score >= 80 ? '적극 추천' : score >= 60 ? '추천' : score >= 40 ? '검토' : '낮음';
    const ap = n.apply || {};
    return {
      project_no: n.project_no, title: n.title, score, grade, eligible, d_day: d, receipt_end: n.receipt_end,
      fields, amount: amountText(n.amount), reasons, fails, warnings: warns, summary: n.summary || '',
      apply_methods: ap.methods || [], emails: ap.emails || [], phones: ap.phones || [], detail_url: n.detail_url,
    };
  }
  function match(p, notices, today, includeIneligible = true) {
    const r = notices.map(n => scoreNotice(p, n, today));
    r.sort((a, b) => (a.eligible === b.eligible ? 0 : a.eligible ? -1 : 1) || (b.score - a.score) ||
      ((a.d_day ?? 9999) - (b.d_day ?? 9999)));
    return includeIneligible ? r : r.filter(x => x.eligible);
  }

  // ── 민감정보 마스킹
  const MASKS = [
    [/\b\d{3}-\d{2}-\d{5}\b/g, '***-**-*****'], [/\b\d{6}-\d{7}\b/g, '******-*******'],
    [/\b01[016789]-?\d{3,4}-?\d{4}\b/g, '010-****-****'], [/[\w.+-]+@[\w-]+\.[\w.]+/g, '***@***'],
  ];
  const mask = s => MASKS.reduce((t, [rx, rep]) => t.replace(rx, rep), s || '');
  const profileBrief = p => mask([`소재지 ${p.region || ''}`, `규모 ${p.size || ''}`, `업종 ${(p.industries || []).join('·')}`,
    `품목 ${p.items || ''}`, `희망국가 ${p.target_countries || ''}`, `수출단계 ${p.export_stage || ''}`,
    `전년 수출실적 ${(Number(p.export_usd) || 0).toLocaleString()}달러`, `직수출 ${p.direct_export ? '예' : '아니오'}`,
    `필요분야 ${(p.needs || []).join(', ')}`].join(' / '));

  // ── 원문 근거 검색 (글자 2-gram BM25)
  function grams(text) {
    const t = (text || '').toLowerCase().replace(/[^\p{L}\p{N}_]+/gu, ' ');
    const out = [];
    for (const w of t.split(' ')) {
      if (!w) continue;
      const cs = [...w];
      if (cs.length === 1) out.push(w);
      for (let i = 0; i < cs.length - 1; i++) out.push(cs[i] + cs[i + 1]);
    }
    return out;
  }
  const counter = arr => arr.reduce((m, g) => (m.set(g, (m.get(g) || 0) + 1), m), new Map());
  class Index {
    constructor(chunks) {
      this.chunks = chunks;
      this.docs = chunks.map(c => counter(grams((c.h || '') + ' ' + c.t)));
      this.lens = this.docs.map(d => [...d.values()].reduce((a, b) => a + b, 0));
      this.avg = this.lens.length ? this.lens.reduce((a, b) => a + b, 0) / this.lens.length : 1;
      const df = new Map();
      for (const d of this.docs) for (const g of d.keys()) df.set(g, (df.get(g) || 0) + 1);
      const N = this.docs.length || 1;
      this.idf = new Map([...df].map(([g, f]) => [g, Math.log(1 + (N - f + 0.5) / (f + 0.5))]));
    }
    search(q, k = 6, pn = null) {
      const qg = counter(grams(q)); const out = [];
      this.docs.forEach((d, i) => {
        const c = this.chunks[i];
        if (pn && c.p !== pn) return;
        let s = 0;
        for (const g of qg.keys()) { const f = d.get(g); if (f) s += (this.idf.get(g) || 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * this.lens[i] / this.avg)); }
        if (s > 0) out.push([s, c]);
      });
      return out.sort((a, b) => b[0] - a[0]).slice(0, k);
    }
  }

  const RULES = `당신은 수출지원사업 상담을 돕는 행정 보조도구입니다. 아래 규칙을 반드시 지키세요.
1. 오직 [근거] 로 제공된 공고문 원문 내용만 사용해 답합니다. 원문에 없는 내용은 추측하지 말고 "공고문에서 확인되지 않습니다"라고 답합니다.
2. 문장마다 근거 번호를 [근거 1] 형식으로 표시합니다.
3. 금액·기한·자격요건은 원문 표현을 그대로 옮깁니다. 여러 사업의 조건을 섞지 않습니다.
4. 한국어로 간결하게(5문장 이내) 답합니다.`;

  async function answer(question, index, notices, opts = {}) {
    const q = mask(question);
    const hits = index.search(q, 6, opts.project_no || null);
    const sources = hits.map(([s, c], i) => {
      const n = notices[c.p] || {};
      return { no: i + 1, project_no: c.p, title: n.title || '', source: c.s, heading: c.h, text: c.t, score: s,
        detail_url: n.detail_url, contact: (n.apply || {}).contact || {}, receipt_end: n.receipt_end, status: n.status };
    });
    if (!sources.length) return { mode: 'none', answer: '관련 공고문 내용을 찾지 못했습니다. 질문을 바꾸거나 공고를 선택해 보세요.', sources: [], masked_question: q };
    const cnt = {}; sources.slice(0, 4).forEach(s => cnt[s.project_no] = (cnt[s.project_no] || 0) + s.score);   // 검색점수 합이 가장 큰 공고
    const top = notices[Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a])[0]] || {};
    const ap = top.apply || {}, am = top.amount || {};
    const fact = `📌 ${top.title || ''} — 접수 ${top.receipt_start || ''} ~ ${top.receipt_end || ''} (${top.status || ''}) · 지원 ${amountText(am)} · 신청 ${(ap.methods || []).join(', ')} ${(ap.emails || []).join(', ')}`.trim();

    if (opts.claude && opts.claude.key) {
      // Claude: 검색된 원문 조각 + 핵심 공고의 공고문(한글파일) 항목별 내용을 근거로 제공
      const ctx = sources.map(s => `[근거 ${s.no}] (${s.title} / ${s.source} / ${s.heading}) 접수마감 ${s.receipt_end} 상태 ${s.status}\n${s.text}`).join('\n\n');
      const focus = opts.project_no ? (notices[opts.project_no] || top) : top;
      const ds = Object.entries(focus.doc_sections || {}).map(([k, v]) => `■ ${k}\n${v}`).join('\n').slice(0, 9000);
      const extra = ds ? `\n\n[근거 ${sources.length + 1}] (${focus.title} / 공고문 주요 내용)\n${ds}` : '';
      const prof = opts.profile ? `\n\n[상담 기업 정보(익명)] ${profileBrief(opts.profile)}` : '';
      const facts = [...new Set(sources.map(s => s.project_no))].map(pn => notices[pn]).filter(Boolean).map(n =>
        `- ${n.title}: 접수 ${n.receipt_start || ''} ~ ${n.receipt_end || ''} (${n.status || ''}) · 지원 ${amountText(n.amount || {})} · 신청 ${((n.apply || {}).methods || []).join(', ')}`).join('\n');
      const user = `[공고 정리값]\n${facts}\n\n${ctx}${extra}${prof}\n\n[질문] ${q}`;
      try {
        const r = await fetch('https://api.anthropic.com/v1/messages', {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-api-key': opts.claude.key, 'anthropic-version': '2023-06-01',
            'anthropic-dangerous-direct-browser-access': 'true' },
          body: JSON.stringify({ model: opts.claude.model || 'claude-sonnet-5-5', max_tokens: 1200,
            system: RULES, messages: [{ role: 'user', content: user }] }) });
        const j = await r.json();
        if (!r.ok) throw new Error((j.error && j.error.message) || ('HTTP ' + r.status));
        let txt = (j.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n').trim();
        if (extra) sources.push({ no: sources.length + 1, project_no: focus.project_no, title: focus.title, source: '공고문 주요 내용',
          heading: Object.keys(focus.doc_sections || {}).join(' · '), text: ds, detail_url: focus.detail_url,
          contact: (focus.apply || {}).contact || {}, receipt_end: focus.receipt_end, status: focus.status });
        const cited = [...new Set([...txt.matchAll(/근거\s*(\d+)/g)].map(m => +m[1]).filter(x => x > 0 && x <= sources.length))];
        if (!cited.length) txt += '\n\n※ AI 답변에 근거 표시가 없어 아래 원문을 반드시 확인하세요.';
        return { mode: 'claude', model: j.model || opts.claude.model, answer: txt, fact, cited, sources, masked_question: q,
          usage: j.usage };
      } catch (e) {
        opts.claudeError = String(e.message || e);   // 실패 시 원문 발췌로 대체
      }
    }
    const qg = new Set(grams(q)); const seen = new Set(); const cand = [];
    for (const s of sources) for (const raw of s.text.split('\n')) {
      const l = raw.trim(), key = l.replace(/\s+/g, '');
      if (key.length < 6 || seen.has(key)) continue; seen.add(key);
      let sc = 0.3 / s.no; for (const g of new Set(grams(l))) if (qg.has(g)) sc += index.idf.get(g) || 0;
      cand.push([sc, s.no, l]);
    }
    cand.sort((a, b) => b[0] - a[0]);
    const lines = cand.slice(0, 5).filter(c => c[0] > 0.5).map(([, no, l]) => `- ${l} [근거 ${no}]`);
    const ev = (am.evidence || []).slice(0, 2).map(e => `\n   └ 원문: ${e}`).join('');
    return { mode: 'extract', answer: `${fact}${ev}\n\n질문과 관련된 공고문 원문 발췌:\n${lines.join('\n')}`, fact, sources, masked_question: q,
      error: opts.claudeError || null };
  }

  // Claude API 키 확인 (아주 짧은 요청)
  async function claudeCheck(key, model) {
    try {
      const r = await fetch('https://api.anthropic.com/v1/messages', { method: 'POST',
        headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01',
          'anthropic-dangerous-direct-browser-access': 'true' },
        body: JSON.stringify({ model: model || 'claude-sonnet-5-5', max_tokens: 5, messages: [{ role: 'user', content: '확인' }] }) });
      const j = await r.json();
      return r.ok ? { ok: true, model: j.model } : { ok: false, error: (j.error && j.error.message) || ('HTTP ' + r.status) };
    } catch (e) { return { ok: false, error: String(e.message || e) }; }
  }

  root.AX = { scoreNotice, match, amountText, dday, mask, profileBrief, grams, Index, answer, claudeCheck, countryGroups };
  if (typeof module !== 'undefined') module.exports = root.AX;
})(typeof window !== 'undefined' ? window : globalThis);
