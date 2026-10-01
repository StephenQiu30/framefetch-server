import { spawn } from "node:child_process";

const egressProxy = resolveYoutubeEgressProxy(process.env);
if (process.argv.includes("--check-config")) {
  process.exit(0);
}
if (process.argv.includes("--check-health")) {
  try {
    const response = await fetch("http://127.0.0.1:4416/ping", {
      signal: AbortSignal.timeout(2_000),
    });
    process.exit(response.ok ? 0 : 1);
  } catch {
    process.exit(1);
  }
}

const childEnvironment = {
  ...process.env,
  HTTP_PROXY: egressProxy,
  HTTPS_PROXY: egressProxy,
  NO_PROXY: "127.0.0.1,localhost",
  http_proxy: egressProxy,
  https_proxy: egressProxy,
  no_proxy: "127.0.0.1,localhost",
};
delete childEnvironment.RUNNER_EGRESS_PROXY;
delete childEnvironment.RUNNER_PROVIDER_EGRESS_PROXIES;

const HEALTH_URL = "http://127.0.0.1:4416/ping";
const STARTUP_GRACE_MS = 5_000;
const PROBE_INTERVAL_MS = 10_000;
const PROBE_TIMEOUT_MS = 3_000;
const FAILURE_THRESHOLD = 3;
const TERMINATE_GRACE_MS = 3_000;
const RESTART_DELAY_MS = 1_000;
const MAX_RESTART_DELAY_MS = 30_000;

let active;
let restartTimer;
let restartDelayMs = RESTART_DELAY_MS;
let stopping = false;

function startChild() {
  if (stopping) return;

  const child = spawn(process.execPath, ["/app/build/main.js", "--host", "0.0.0.0"], {
    cwd: "/app",
    env: childEnvironment,
    // The upstream process logs minted tokens and their bindings. Its output
    // must never reach persistent container logs.
    stdio: ["ignore", "ignore", "ignore"],
  });
  const state = {
    child,
    failures: 0,
    ready: false,
    probeTimer: undefined,
    killTimer: undefined,
  };
  active = state;

  child.once("error", () => {
    console.error("youtube POT provider process could not start");
  });
  child.once("close", () => {
    clearTimeout(state.probeTimer);
    clearTimeout(state.killTimer);
    if (active === state) active = undefined;
    if (stopping) {
      process.exit(0);
    }
    console.error("youtube POT provider process stopped; restart scheduled");
    const delay = restartDelayMs;
    restartDelayMs = Math.min(MAX_RESTART_DELAY_MS, restartDelayMs * 2);
    restartTimer = setTimeout(startChild, delay);
  });
  state.probeTimer = setTimeout(() => probe(state), STARTUP_GRACE_MS);
}

async function probe(state) {
  if (stopping || active !== state) return;

  try {
    const response = await fetch(HEALTH_URL, {
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error("unexpected POT provider response");
    }
    state.failures = 0;
    state.ready = true;
    restartDelayMs = RESTART_DELAY_MS;
  } catch {
    state.ready = false;
    state.failures += 1;
    if (state.failures >= FAILURE_THRESHOLD) {
      console.error("youtube POT provider failed consecutive health probes");
      recycle(state);
      return;
    }
  }

  state.probeTimer = setTimeout(() => probe(state), PROBE_INTERVAL_MS);
}

function recycle(state) {
  if (active !== state || childFinished(state.child)) return;
  signalChild(state.child, "SIGTERM");
  state.killTimer = setTimeout(() => {
    if (!childFinished(state.child)) signalChild(state.child, "SIGKILL");
  }, TERMINATE_GRACE_MS);
}

function shutdown(signal) {
  if (stopping) return;
  stopping = true;
  clearTimeout(restartTimer);
  if (active === undefined || childFinished(active.child)) {
    process.exit(0);
  }
  const state = active;
  clearTimeout(state.probeTimer);
  signalChild(state.child, signal);
  state.killTimer = setTimeout(() => {
    if (!childFinished(state.child)) signalChild(state.child, "SIGKILL");
  }, TERMINATE_GRACE_MS);
}

function childFinished(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function signalChild(child, signal) {
  try {
    child.kill(signal);
  } catch {
    // The close event owns cleanup and restart decisions.
  }
}

process.once("SIGINT", () => shutdown("SIGINT"));
process.once("SIGTERM", () => shutdown("SIGTERM"));
startChild();

function resolveYoutubeEgressProxy(environment) {
  const fallback = validatedProxy(environment.RUNNER_EGRESS_PROXY);
  const rawOverrides = environment.RUNNER_PROVIDER_EGRESS_PROXIES ?? "{}";
  let overrides;
  try {
    overrides = JSON.parse(rawOverrides);
  } catch {
    throw new Error("provider egress proxy configuration is invalid");
  }
  if (
    overrides === null ||
    Array.isArray(overrides) ||
    typeof overrides !== "object"
  ) {
    throw new Error("provider egress proxy configuration is invalid");
  }

  const validated = {};
  for (const [provider, proxy] of Object.entries(overrides)) {
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(provider)) {
      throw new Error("provider egress proxy configuration is invalid");
    }
    validated[provider] = validatedProxy(proxy);
  }
  return validated.youtube || fallback;
}

function validatedProxy(value) {
  if (typeof value !== "string" || value !== value.trim()) {
    throw new Error("runner egress proxy is invalid");
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("runner egress proxy is invalid");
  }
  if (
    !["http:", "https:"].includes(parsed.protocol) ||
    !parsed.hostname ||
    parsed.username ||
    parsed.password ||
    (parsed.pathname !== "" && parsed.pathname !== "/") ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("runner egress proxy is invalid");
  }
  return value.replace(/\/$/, "");
}
