/* Diagnostics contain only status and fixed causes, never account material. */
const sessionLabels = { missing: '缺少登录材料', available: '可用', unavailable: '暂不可用' };
const causeMessages = {
  credential_missing: '请在元宝页面完成登录，然后重新解析视频号链接。',
  identity_account_conflict: '元宝账号在解析时发生变化，请确认账号后重新解析。',
  identity_material_invalid: '元宝登录状态暂不可用，请确认登录后重新解析。',
  parse_response_invalid: '元宝解析响应未通过校验，请重新解析。',
  yuanbao_response_source_invalid: '元宝响应来源不符合固定解析接口，请重新解析。',
  yuanbao_response_size_invalid: '元宝解析响应超过大小限制，请重新解析。',
  yuanbao_response_utf8_invalid: '元宝解析响应编码异常，请重新解析。',
  yuanbao_response_json_invalid: '元宝未返回有效的解析 JSON，请稍后重新解析。',
  yuanbao_response_credential_echo: '元宝响应包含认证材料，插件已拒绝导出。',
  parse_request_failed: '元宝解析请求失败，请检查网络后重新解析。',
  extension_timeout: '元宝解析请求超时，请检查网络后重新解析。',
};
const connection = document.getElementById('connection');
const session = document.getElementById('session');
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
    session.textContent = sessionLabels[state.session] ?? '暂不可用';
    document.getElementById('reconnect').hidden = state.connected;
    message.textContent = !state.connected ? '请确认宿主身份服务正在运行，然后点击“重新连接”。' :
      state.busy ? '正在处理解析任务，请稍候。' :
      state.cause ? causeMessages[state.cause] ?? '上次解析未完成，请重新解析。' :
      state.session === 'missing' ? '请点击“登录元宝”，完成登录后重新解析。' :
      '解析无需打开元宝页面。登录有效性将在实际请求时校验。';
  } catch {
    connection.textContent = '暂不可用';
    message.textContent = '无法读取插件状态，请重新加载插件后再试。';
  } finally {
    pending = false;
    buttons.forEach(button => { button.disabled = false; });
  }
}
document.getElementById('login-yuanbao').addEventListener('click', () => { void refresh('login_yuanbao'); });
document.getElementById('refresh').addEventListener('click', () => { void refresh(); });
document.getElementById('reconnect').addEventListener('click', () => { void refresh('reconnect'); });
void refresh();
