/**
 * Thin CLI for Python bridge. Uses stock-sdk nested under stock-sdk-mcp.
 * Usage: node stock_sdk_cli.mjs <cmd> [args...]
 */
import { createRequire } from "module";
import path from "path";

function loadSdk() {
  const roots = [
    process.env.STOCK_SDK_MCP_ROOT,
    "D:/ProgramFiles/nodejs/node_modules/stock-sdk-mcp",
    path.join(process.env.APPDATA || "", "npm/node_modules/stock-sdk-mcp"),
  ].filter(Boolean);
  let last;
  for (const root of roots) {
    try {
      const req = createRequire(path.join(root, "package.json"));
      return req("stock-sdk");
    } catch (err) {
      last = err;
    }
  }
  throw last || new Error("stock-sdk not found");
}

const sdkMod = loadSdk();
const StockSDK = sdkMod.StockSDK || sdkMod.default;
const sdk = new StockSDK();

function asRows(pool) {
  if (Array.isArray(pool)) return pool;
  if (Array.isArray(pool?.data)) return pool.data;
  if (Array.isArray(pool?.pool)) return pool.pool;
  return [];
}

async function marketEmotion() {
  let zt = null;
  let dtProxy = null;
  let north = null;
  try {
    zt = asRows(await sdk.getZTPool({ type: "zt" })).length;
  } catch (_) {}
  try {
    dtProxy = asRows(await sdk.getZTPool({ type: "dt" })).length;
  } catch (_) {}
  try {
    north = await sdk.getNorthboundFlowSummary();
  } catch (_) {}
  return {
    ok: true,
    source: "stock-sdk",
    zt_pool_count: zt,
    dt_pool_count: dtProxy,
    northbound: north,
  };
}

async function fundFlow(code) {
  const text = String(code || "").replace(/\D/g, "");
  try {
    let flow = null;
    if (typeof sdk.getIndividualFundFlow === "function") {
      flow = await sdk.getIndividualFundFlow(text);
    } else {
      flow = await sdk.getFundFlow(text);
    }
    return { ok: true, source: "stock-sdk", code: text, flow };
  } catch (err) {
    return { ok: false, source: "stock-sdk", error: String(err?.message || err) };
  }
}

async function conceptCore(boardCode, stockCode) {
  try {
    const members = await sdk.getConceptConstituents(boardCode);
    const rows = asRows(members);
    const sorted = [...rows].sort(
      (a, b) => Number(b.amount || b.f6 || 0) - Number(a.amount || a.f6 || 0)
    );
    const n = Math.max(1, Math.ceil(sorted.length * 0.2));
    const topCodes = sorted
      .slice(0, n)
      .map((r) => String(r.code || r.f12 || "").replace(/\D/g, ""));
    const code = String(stockCode || "").replace(/\D/g, "");
    const idx = topCodes.indexOf(code);
    return {
      ok: true,
      source: "stock-sdk",
      board: boardCode,
      member_count: sorted.length,
      core: idx >= 0,
      amount_pct: idx >= 0 ? (idx + 1) / Math.max(sorted.length, 1) : null,
    };
  } catch (err) {
    return { ok: false, source: "stock-sdk", error: String(err?.message || err) };
  }
}

async function quoteBrief(code) {
  try {
    const text = String(code || "").replace(/\D/g, "");
    const quotes = await sdk.getFullQuotes([text]);
    const row = Array.isArray(quotes) ? quotes[0] : quotes?.[text] || quotes;
    return { ok: true, source: "stock-sdk", quote: row };
  } catch (err) {
    return { ok: false, source: "stock-sdk", error: String(err?.message || err) };
  }
}

const [cmd, ...args] = process.argv.slice(2);
let out;
try {
  if (cmd === "market_emotion") out = await marketEmotion();
  else if (cmd === "fund_flow") out = await fundFlow(args[0]);
  else if (cmd === "concept_core") out = await conceptCore(args[0], args[1]);
  else if (cmd === "quote") out = await quoteBrief(args[0]);
  else out = { ok: false, error: `unknown cmd ${cmd}` };
} catch (err) {
  out = { ok: false, error: String(err?.message || err) };
}
process.stdout.write(JSON.stringify(out));
