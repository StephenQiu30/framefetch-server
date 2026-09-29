async function update(command = 'status') {
  try {
    const reply = await chrome.runtime.sendMessage({command});
    document.getElementById('status').textContent = reply.state;
  } catch {
    document.getElementById('status').textContent = '连接不可用，请检查本机来源服务';
  }
}
document.getElementById('connect').addEventListener('click', () => update('connect'));
update();
