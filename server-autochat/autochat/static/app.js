'use strict';
let csrf = '';
let refreshTimer;
const $ = id => document.getElementById(id);
const labels = {claimed:'处理中', pending:'等待核查', sent:'已发送', uncertain:'发送结果不确定', acknowledged:'已核查', no_new_context:'无新聊天', model_skipped:'语境不适合', invalid_reply:'回复未通过检查', context_failed:'读取失败', generation_failed:'生成失败', rate_limited:'限流冷却', rejected:'群组拒绝发送', expired:'错过时段', paused:'已暂停', guarded:'已拦截'};
const notes = {no_new_context:'没有新增的有效聊天内容', invalid_reply:'字数不符或与近期回复重复', generation_failed:'请检查 DeepSeek 配置、余额及网络', context_failed:'请检查 Telegram 连接和群权限', rate_limited:'等待平台要求的冷却时间', uncertain:'请在 Telegram 核查后解除保护', pending:'程序可能中断，请核查发送结果', sent:'Telegram 已确认发送请求', expired:'生成超时，本时段不补发', claimed:'已占用时段；重启后不会重复执行'};
function notify(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => $('toast').hidden = true, 5000); }
function loginView() { $('dashboard').hidden = true; $('login-view').hidden = false; clearInterval(refreshTimer); }
async function api(path, method='GET', data) {
  const headers = {'X-CSRF-Token': csrf};
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch('/api/' + path, {method, headers, credentials:'same-origin', body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) { if (response.status === 401 && path !== 'login') loginView(); throw new Error(result.detail || '操作失败'); }
  return result;
}
async function busy(button, fn) { button.disabled = true; const original = button.textContent; button.textContent = '处理中…'; try { await fn(); } catch (error) { notify(error.message); } finally { button.disabled = false; button.textContent = original; } }
function timeText(timestamp) { return new Date(timestamp).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}); }
async function refresh() {
  const s = await api('status');
  $('server-time').textContent = timeText(s.server_time);
  $('sent-count').textContent = s.sent;
  $('sent-progress').value = s.sent;
  $('run-badge').textContent = s.blocked ? '等待人工核查' : s.enabled ? '自动回复已启用' : '已暂停';
  $('run-badge').classList.toggle('running', s.enabled && !s.blocked);
  $('run-title').textContent = s.blocked ? '先核查，再继续。' : s.enabled ? '正在等待下一段对话。' : '准备好，再开始聊天。';
  $('run-description').textContent = s.enabled ? s.schedule : '保存配置后，点击启用即可在计划时段自动运行。';
  $('worker-error').textContent = s.last_error ? '上次连接失败（'+s.last_error+'），请检查配置后重新启用。' : '';
  $('uncertain-box').hidden = !s.blocked;
  $('empty-history').hidden = s.records.length > 0;
  $('records').replaceChildren();
  for (const record of s.records) {
    const row = document.createElement('tr');
    const planned = String(8 + Math.floor(record.slot / 2)).padStart(2,'0') + ':' + (record.slot % 2 ? '30':'00');
    for (const text of [planned, labels[record.status] || record.status, record.finished ? timeText(record.finished * 1000) : '—', notes[record.status] || record.detail || '—']) {
      const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
    }
    $('records').append(row);
  }
}
async function loadSettings() {
  const s = await api('settings');
  for (const key of ['api_id','model','target']) $('settings-form').elements[key].value = s[key];
  for (const [key,id] of [['api_hash','api-hash-state'],['session_string','session-string-state'],['deepseek_api_key','deepseek-api-key-state']]) {
    $(id).textContent = s[key+'_set'] ? '已保存 · 留空保留' : '未配置';
    $('settings-form').elements[key].value = '';
  }
}
async function dashboard() { $('login-view').hidden = true; $('dashboard').hidden = false; await Promise.all([refresh(),loadSettings()]); clearInterval(refreshTimer); refreshTimer = setInterval(() => refresh().catch(e => notify(e.message)),10000); }
$('login-form').addEventListener('submit', async event => { event.preventDefault(); $('login-error').textContent=''; await busy(event.submitter, async () => { try { const s = await api('login','POST',{password:$('password').value}); csrf=s.csrf; $('password').value=''; await dashboard(); } catch(error) { $('login-error').textContent=error.message; } }); });
$('settings-form').addEventListener('submit', async event => { event.preventDefault(); await busy(event.submitter, async () => { await api('settings','POST',Object.fromEntries(new FormData(event.target))); await loadSettings(); await refresh(); notify('配置已保存，自动回复已暂停。确认后点击启用。'); }); });
$('enable').addEventListener('click', e => busy(e.currentTarget, async () => { await api('enable','POST'); await loadSettings(); await refresh(); notify('自动回复已启用，将按计划时段运行。'); }));
$('pause').addEventListener('click', e => busy(e.currentTarget, async () => { await api('pause','POST'); await refresh(); notify('已暂停；已经提交给 Telegram 的消息无法撤回。'); }));
$('load-groups').addEventListener('click', e => busy(e.currentTarget, async () => { const groups=await api('groups','POST'); $('groups').replaceChildren(new Option('请选择群组','')); for(const g of groups) $('groups').add(new Option(g.title+' · '+g.id,g.id)); $('group-picker').hidden=false; notify('已读取 '+groups.length+' 个群组，请选择后保存。'); }));
$('groups').addEventListener('change', e => { if(e.target.value) $('target').value=e.target.value; });
$('preview').addEventListener('click', e => busy(e.currentTarget, async () => { const p=await api('preview','POST'); $('preview-text').textContent=p.reply || '当前没有可用的聊天内容'; $('preview-meta').textContent=(p.valid?'字数检查通过':'不会发送此预览')+' · '+p.context_count+' 条上下文'; notify(p.message); }));
$('resolve').addEventListener('click', e => busy(e.currentTarget, async () => { if(!confirm('确认已在 Telegram 核查发送结果？解除后不会重发这条消息。')) return; await api('resolve-uncertain','POST',{confirmed:true}); await refresh(); notify('已解除保护，继续遵守发送间隔。'); }));
$('logout').addEventListener('click', async () => { try { await api('logout','POST'); } catch (_) {} csrf=''; loginView(); });
for(const link of document.querySelectorAll('nav a')) link.addEventListener('click',()=>{ for(const item of document.querySelectorAll('nav a')) item.classList.remove('active'); link.classList.add('active'); });
(async () => { try { csrf=(await api('session')).csrf; await dashboard(); } catch (_) { loginView(); } })();
