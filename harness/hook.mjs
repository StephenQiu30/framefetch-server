// Claude Code hook 入口：node harness/hook.mjs <session|pre|post|stop>，从 stdin 读取 hook JSON。
import { readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { areasFor, check, forbiddenRule, protectedRule, specMap, toRepoPath } from './check.mjs';

const event = process.argv[2];
const input = (() => {
  try {
    return JSON.parse(readFileSync(0, 'utf8') || '{}');
  } catch {
    return {};
  }
})();
const reply = (payload) => process.stdout.write(JSON.stringify(payload));
const targetFile = () => {
  const toolInput = input.tool_input ?? {};
  const file = toolInput.file_path ?? toolInput.notebook_path;
  return file ? toRepoPath(file) : null;
};

function session() {
  const areas = specMap.areas.map((area) => `- ${area.id}：${area.docs.join('、')}`).join('\n');
  reply({
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: [
        'video-server 规范 harness 已启用。实现代码前先阅读改动路径对应的规范文档（映射见 harness/spec-map.json），按文档设计实现；文档与代码不一致时先指出，不自行另立规则。',
        areas,
        '生成目录、锁文件、.env 与上游 Skill 由 hook 拦截；结束前 hook 会运行 node harness/check.mjs --changed。',
      ].join('\n'),
    },
  });
}

function pre() {
  const file = targetFile();
  if (!file) return;
  const rule = protectedRule(file) ?? forbiddenRule(file);
  if (!rule) return;
  reply({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: 'deny',
      permissionDecisionReason: `${file}：${rule.reason}（规则见 harness/spec-map.json）`,
    },
  });
}

// 每个会话中每个领域只提示一次，避免重复注入上下文。
function post() {
  const file = targetFile();
  if (!file) return;
  const areas = areasFor(file);
  if (!areas.length) return;
  const ledger = path.join(tmpdir(), `video-server-harness-${input.session_id ?? 'unknown'}.json`);
  let seen = [];
  try {
    seen = JSON.parse(readFileSync(ledger, 'utf8'));
  } catch {}
  const fresh = areas.filter((area) => !seen.includes(area.id));
  if (!fresh.length) return;
  writeFileSync(ledger, JSON.stringify([...seen, ...fresh.map((area) => area.id)]));
  const text = fresh.map((area) => `${area.id}：${area.note} 规范：${area.docs.join('、')}`).join('\n');
  reply({
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext: `${file} 属于以下领域，实现必须与对应规范一致：\n${text}`,
    },
  });
}

function stop() {
  if (input.stop_hook_active) return;
  const { errors, warnings } = check({ changedOnly: true });
  if (errors.length) {
    reply({ decision: 'block', reason: `规范检查未通过，请修复后再结束：\n${errors.join('\n')}` });
  } else if (warnings.length) {
    reply({ systemMessage: `规范提示：${warnings.join(' ')}` });
  }
}

({ session, pre, post, stop })[event]?.();
