/* Diagnostics contain only status and fixed causes, never account material. */
const pageLabels = { missing: '未打开', loading: '正在加载', available: '已打开',
  ambiguous: '存在多个页面', inactive: '需要激活' };
const causeMessages = {
  credential_missing: '请在元宝页面完成登录，然后重新解析视频号链接。',
  identity_page_unavailable: '元宝页面暂不可用，请点击“打开元宝”，确认页面加载后重新解析。',
  identity_tab_ambiguous: '请只保留一个普通元宝标签页，然后重新解析。',
  identity_navigation_changed: '元宝页面在解析时发生跳转，请等待加载完成后重新解析。',
  identity_origin_invalid: '元宝页面来源不符合要求，请重新打开官方元宝页面。',
  identity_account_conflict: '元宝账号在解析时发生变化，请确认账号后重新解析。',
  identity_material_invalid: '元宝登录状态暂不可用，请确认登录后重新解析。',
  native_api_unavailable: '元宝页面的解析接口暂不可用，请刷新元宝页面后重新解析。',
  parse_response_invalid: '元宝解析响应未通过校验，请重新解析。',
  parse_request_failed: '元宝解析请求失败，请检查网络后重新解析。',
  extension_timeout: '元宝页面准备或解析超时，请确认页面加载后重新解析。',
};
const connection = document.getElementById('connection');
const page = document.getElementById('page');
const message = document.getElementById('message');
const buttons = [...document.querySelectorAll('button')];
let pending = false;
async function refresh(type = 'status') {
  if (pending) return;
  pending = true;
  buttons.forEach(button => { button.disabled = true; });
  try {
    const state = await chrome.runtime.sendMessage({ type });
    if (!state || state.error) throw new Error('status_unavailable');
    document.getElementById('version').textContent = `v${state.version}`;
    connection.textContent = state.connected ? '已连接' : '未连接';
    page.textContent = pageLabels[state.page] ?? '暂不可用';
    document.getElementById('reconnect').hidden = state.connected;
    message.textContent = !state.connected ? '请确认宿主身份服务正在运行，然后点击“重新连接”。' :
      state.busy ? '正在处理解析任务，请稍候。' :
      state.page === 'ambiguous' ? causeMessages.identity_tab_ambiguous :
      state.page === 'inactive' ? '请点击“打开元宝”激活页面，然后重新解析。' :
      state.cause ? causeMessages[state.cause] ?? '上次解析未完成，请重新解析。' :
      state.page === 'missing' ? '解析视频号时会自动打开元宝后台页，并复用已有登录。' :
      '元宝页面已打开。登录状态将在实际解析时校验。';
  } catch {
    connection.textContent = '暂不可用';
    message.textContent = '无法读取插件状态，请重新加载插件后再试。';
  } finally {
    pending = false;
    buttons.forEach(button => { button.disabled = false; });
  }
}
document.getElementById('open-yuanbao').addEventListener('click', () => { void refresh('open_yuanbao'); });
document.getElementById('refresh').addEventListener('click', () => { void refresh(); });
document.getElementById('reconnect').addEventListener('click', () => { void refresh('reconnect'); });
void refresh();
