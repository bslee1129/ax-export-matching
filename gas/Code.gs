/**
 * AX 수출지원 매칭 — 알림 회원(구독자) 관리 + 메일 발송 (Google Apps Script)
 *
 * 웹페이지(GitHub Pages)는 서버가 없어 회원 정보를 저장할 곳이 없으므로,
 * 관리자 본인의 Google 계정에서 이 스크립트를 '웹 앱'으로 배포해 회원 명부(구글 시트)와 메일 발송을 맡깁니다.
 *  - 회원 이메일은 이 구글 시트에만 저장되고 GitHub(공개 저장소)에는 올라가지 않습니다.
 *  - 메일은 관리자 Gmail 계정 이름으로 발송됩니다 (일반 Gmail 하루 100명 한도).
 *
 * 설치 (처음 한 번)
 *  1) https://script.google.com → 새 프로젝트 → 이 파일 내용을 붙여넣고 저장
 *  2) 위 함수 선택에서 setup 을 골라 [실행] → 권한 허용 → 실행 로그의 '알림 키'를 복사
 *  3) [배포] → 새 배포 → 유형: 웹 앱 / 실행 사용자: 나 / 액세스 권한: 모든 사용자 → 배포 → 웹 앱 URL 복사
 *  4) GitHub 저장소 Settings → Secrets and variables → Actions 에 등록
 *       AX_NOTIFY_URL = 웹 앱 URL,  AX_NOTIFY_KEY = 알림 키
 *     그리고 docs/config.js 의 notifyUrl 에 같은 웹 앱 URL 입력 (회원가입 화면이 사용)
 *
 * 동작
 *  - 회원가입(subscribe): 시트에 '확인대기'로 저장 → 확인 메일의 링크를 눌러야 '구독중' (남의 메일 주소 무단 등록 방지)
 *  - 수집 후 GitHub Actions(ax_notify.py)가 list 로 구독자 조건을 받아 적합도 70점↑ 새 공고를 계산 → send 로 메일 발송
 *  - 모든 메일 하단에 '알림 해지' 링크
 *  - 관리자 화면(admin_list): 웹페이지 '관리자' 탭에서 비밀번호 확인 후 신청 기업 목록 조회
 *      비밀번호는 공개 저장소에 두지 않고 Apps Script [프로젝트 설정 › 스크립트 속성] ADMIN_PASSWORD 에 저장
 *      (10번 틀리면 10분 잠김)
 */

const SHEET = '구독자';
const COLS = ['id', 'email', 'name', 'conditions', 'status', 'token', 'created_at', 'confirmed_at', 'pending', 'updated_at'];
const SENDER_NAME = 'AX 수출지원사업 알림';

function setup() {
  sheet_();
  const p = PropertiesService.getScriptProperties();
  if (!p.getProperty('NOTIFY_KEY')) p.setProperty('NOTIFY_KEY', Utilities.getUuid().replace(/-/g, ''));
  Logger.log('알림 키(AX_NOTIFY_KEY): ' + p.getProperty('NOTIFY_KEY'));
  Logger.log('회원 명부 시트: ' + SpreadsheetApp.openById(p.getProperty('SHEET_ID')).getUrl());
  Logger.log('관리자(발송) 계정: ' + Session.getEffectiveUser().getEmail());
}

function sheet_() {
  const p = PropertiesService.getScriptProperties();
  let ss = null;
  const id = p.getProperty('SHEET_ID');
  if (id) { try { ss = SpreadsheetApp.openById(id); } catch (e) { ss = null; } }
  if (!ss) { ss = SpreadsheetApp.create('AX 수출지원 알림 회원'); p.setProperty('SHEET_ID', ss.getId()); }
  let sh = ss.getSheetByName(SHEET);
  if (!sh) { sh = ss.insertSheet(SHEET); sh.appendRow(COLS); sh.setFrozenRows(1); const d = ss.getSheetByName('Sheet1') || ss.getSheetByName('시트1'); if (d) ss.deleteSheet(d); }
  return sh;
}

function rows_() {
  const sh = sheet_();
  const v = sh.getDataRange().getValues();
  const out = [];
  for (let i = 1; i < v.length; i++) {
    const o = { _row: i + 1 };
    COLS.forEach((c, j) => o[c] = v[i][j]);
    out.push(o);
  }
  return out;
}

function save_(o) {
  const sh = sheet_();
  const vals = [COLS.map(c => o[c] === undefined ? '' : o[c])];
  if (o._row) sh.getRange(o._row, 1, 1, COLS.length).setValues(vals);
  else sh.appendRow(vals[0]);
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

function page_(title, msg) {
  return HtmlService.createHtmlOutput(
    `<meta name="viewport" content="width=device-width,initial-scale=1"><div style="font-family:sans-serif;max-width:560px;margin:60px auto;padding:0 16px">
     <h2 style="color:#1f4e79">${title}</h2><p style="line-height:1.6">${msg}</p></div>`).setTitle(title);
}

function selfUrl_() { return ScriptApp.getService().getUrl(); }
const esc_ = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

// 조건은 매칭에 필요한 항목만 (사업자번호 등 식별정보는 받지 않음)
const COND_KEYS = ['region', 'size', 'listed', 'industries', 'items', 'target_countries', 'export_stage', 'export_usd',
  'direct_export', 'is_overseas_distributor', 'needs', 'keywords', 'min_score', 'sources'];
function cleanCond_(c) {
  const o = {};
  COND_KEYS.forEach(k => { if (c && c[k] !== undefined) o[k] = c[k]; });
  o.min_score = Math.max(70, Math.min(100, Number(o.min_score) || 70));
  return o;
}

function doPost(e) {
  let b = {};
  try { b = JSON.parse(e.postData.contents || '{}'); } catch (err) { return json_({ ok: false, error: '요청 형식 오류' }); }
  const key = PropertiesService.getScriptProperties().getProperty('NOTIFY_KEY');
  try {
    if (b.action === 'subscribe') return json_(subscribe_(b));
    if (b.action === 'unsubscribe_request') return json_(unsubRequest_(b));
    if (b.action === 'admin_list') return json_(adminList_(b));
    if (b.key !== key || !key) return json_({ ok: false, error: '권한 없음' });
    if (b.action === 'list') return json_(list_());
    if (b.action === 'send') return json_(send_(b.messages || []));
    if (b.action === 'test') return json_({ ok: true, admin: Session.getEffectiveUser().getEmail(), quota: MailApp.getRemainingDailyQuota() });
    return json_({ ok: false, error: '알 수 없는 요청' });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function doGet(e) {
  const q = e.parameter || {};
  const r = rows_().find(x => String(x.id) === String(q.id) && String(x.token) === String(q.t));
  if (q.action === 'confirm') {
    if (!r) return page_('확인 실패', '링크가 올바르지 않거나 만료되었습니다. 웹페이지에서 다시 신청해 주세요.');
    if (r.pending) { r.conditions = r.pending; r.pending = ''; }
    const first = r.status !== '구독중';
    r.status = '구독중'; r.confirmed_at = new Date().toISOString(); r.updated_at = r.confirmed_at;
    save_(r);
    if (first) {
      try { MailApp.sendEmail({ to: Session.getEffectiveUser().getEmail(), name: SENDER_NAME,
        subject: '[AX 알림] 새 구독자 ' + r.email, htmlBody: `새 구독자가 확인을 마쳤습니다: ${esc_(r.email)} (${esc_(r.name)})<br>조건: <pre>${esc_(r.conditions)}</pre>` }); } catch (err) {}
    }
    return page_('알림 신청 완료', `<b>${esc_(r.email)}</b> 로 맞춤 공고 알림을 보내 드립니다.<br>
      매일 공고 수집 후 조건에 맞는 <b>적합도 ${esc_(JSON.parse(r.conditions || '{}').min_score || 70)}점 이상</b> 새 공고가 있을 때만 메일이 갑니다.<br>
      첫 메일에는 지금 신청 가능한 맞춤 공고를 모아 보내 드립니다.`);
  }
  if (q.action === 'unsubscribe') {
    if (!r) return page_('해지 실패', '링크가 올바르지 않습니다.');
    r.status = '해지'; r.updated_at = new Date().toISOString(); save_(r);
    return page_('알림 해지 완료', `${esc_(r.email)} 의 알림을 해지했습니다. 다시 받으려면 웹페이지에서 신청하세요.`);
  }
  return page_('AX 수출지원 알림', '수출지원사업 맞춤 공고 알림 서비스입니다.');
}

function subscribe_(b) {
  const email = String(b.email || '').trim().toLowerCase();
  if (!EMAIL_RE.test(email)) return { ok: false, error: '이메일 주소를 확인해 주세요.' };
  if (!b.agree) return { ok: false, error: '개인정보 수집·이용에 동의해 주세요.' };
  const lock = LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const now = new Date().toISOString();
    const cond = JSON.stringify(cleanCond_(b.conditions || {}));
    let r = rows_().find(x => String(x.email).toLowerCase() === email);
    if (r && r.updated_at && (Date.now() - new Date(r.updated_at).getTime()) < 60 * 1000)
      return { ok: false, error: '잠시 후 다시 시도해 주세요.' };
    if (!r) r = { id: Utilities.getUuid().slice(0, 8), email, created_at: now, status: '확인대기' };
    r.name = String(b.name || '').slice(0, 60);
    r.token = Utilities.getUuid().replace(/-/g, '');
    r.pending = cond; r.updated_at = now;
    if (r.status === '해지') r.status = '확인대기';
    save_(r);
    const link = `${selfUrl_()}?action=confirm&id=${r.id}&t=${r.token}`;
    MailApp.sendEmail({ to: email, name: SENDER_NAME, subject: '[AX 수출지원] 맞춤 공고 알림 신청 확인',
      htmlBody: `<div style="font-family:sans-serif;line-height:1.6">안녕하세요${r.name ? ' ' + esc_(r.name) + '님' : ''}.<br>
        수출지원사업 맞춤 공고 알림 신청을 받았습니다. 아래 버튼을 눌러야 알림이 시작됩니다.<br><br>
        <a href="${link}" style="background:#1f4e79;color:#fff;padding:10px 18px;border-radius:6px;text-decoration:none">알림 신청 확인</a><br><br>
        <span style="color:#666;font-size:12px">본인이 신청하지 않았다면 이 메일을 무시하세요. 확인하지 않으면 메일이 발송되지 않습니다.</span></div>` });
    return { ok: true, message: '확인 메일을 보냈습니다. 메일의 [알림 신청 확인]을 눌러 주세요.' };
  } finally { lock.releaseLock(); }
}

function unsubRequest_(b) {
  const email = String(b.email || '').trim().toLowerCase();
  const r = rows_().find(x => String(x.email).toLowerCase() === email && x.status === '구독중');
  if (r) {
    const link = `${selfUrl_()}?action=unsubscribe&id=${r.id}&t=${r.token}`;
    MailApp.sendEmail({ to: email, name: SENDER_NAME, subject: '[AX 수출지원] 알림 해지 링크',
      htmlBody: `아래 링크를 누르면 알림이 해지됩니다.<br><a href="${link}">알림 해지</a>` });
  }
  return { ok: true, message: '등록된 주소라면 해지 링크를 메일로 보냈습니다.' };
}

function list_() {
  const base = selfUrl_();
  return { ok: true, quota: MailApp.getRemainingDailyQuota(), subscribers: rows_().filter(r => r.status === '구독중').map(r => ({
    id: String(r.id), email: r.email, name: r.name, conditions: JSON.parse(r.conditions || '{}'),
    unsubscribe_url: `${base}?action=unsubscribe&id=${r.id}&t=${r.token}`, confirmed_at: r.confirmed_at })) };
}

function send_(messages) {
  const done = [], failed = [];
  const ok = new Set(rows_().filter(r => r.status === '구독중').map(r => String(r.email).toLowerCase()));
  for (const m of messages.slice(0, 50)) {
    const to = String(m.to || '').toLowerCase();
    if (!ok.has(to)) { failed.push({ to, error: '구독중이 아닌 주소' }); continue; }
    try {
      if (MailApp.getRemainingDailyQuota() < 1) { failed.push({ to, error: '오늘 발송 한도 초과' }); continue; }
      MailApp.sendEmail({ to, name: SENDER_NAME, subject: String(m.subject || '').slice(0, 200), htmlBody: String(m.html || '') });
      done.push(to);
    } catch (err) { failed.push({ to, error: String(err) }); }
  }
  return { ok: true, sent: done, failed, quota: MailApp.getRemainingDailyQuota() };
}

// ── 관리자: 신청 기업 목록 (비밀번호는 스크립트 속성 ADMIN_PASSWORD)
function adminList_(b) {
  const pw = PropertiesService.getScriptProperties().getProperty('ADMIN_PASSWORD');
  if (!pw) return { ok: false, error: '관리자 비밀번호가 아직 설정되지 않았습니다 (Apps Script › 프로젝트 설정 › 스크립트 속성 ADMIN_PASSWORD).' };
  const cache = CacheService.getScriptCache();
  const fails = Number(cache.get('admin_fail') || 0);
  if (fails >= 10) return { ok: false, error: '비밀번호를 여러 번 틀려 10분간 잠겼습니다. 잠시 후 다시 시도하세요.' };
  if (String(b.password || '') !== pw) {
    cache.put('admin_fail', String(fails + 1), 600);
    Utilities.sleep(700);
    return { ok: false, error: '비밀번호가 맞지 않습니다.' };
  }
  cache.remove('admin_fail');
  const iso = v => (v instanceof Date) ? v.toISOString() : String(v || '');
  const parse = v => { try { return JSON.parse(v || '{}'); } catch (e) { return {}; } };
  return {
    ok: true, admin: Session.getEffectiveUser().getEmail(), quota: MailApp.getRemainingDailyQuota(),
    sheet_url: SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SHEET_ID')).getUrl(),
    subscribers: rows_().map(r => ({
      id: String(r.id), email: String(r.email || ''), name: String(r.name || ''), status: String(r.status || ''),
      created_at: iso(r.created_at), confirmed_at: iso(r.confirmed_at), updated_at: iso(r.updated_at),
      conditions: parse(r.conditions || r.pending), pending_change: !!r.pending && !!r.conditions
    }))
  };
}
