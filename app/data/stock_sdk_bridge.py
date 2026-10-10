"""stock-sdk（Node）备源桥接。失败返回空，不假装有数。"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

log = logging.getLogger("stockdecision.sdk")

_CLI = Path(__file__).resolve().parent / "stock_sdk_cli.mjs"
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 60.0
_stats = {"ok": 0, "fail": 0, "last_error": "", "last_ok_at": 0.0}


def bridge_stats() -> dict:
    return dict(_stats)


def _run(cmd: str, *args: str, timeout: float = 12.0) -> dict:
    key = "|".join((cmd, *args))
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    node = shutil.which("node")
    if not node or not _CLI.exists():
        _stats["fail"] += 1
        _stats["last_error"] = "node 或 stock_sdk_cli.mjs 不可用"
        return {"ok": False, "error": _stats["last_error"]}
    try:
        proc = subprocess.run(
            [node, str(_CLI), cmd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        text = (proc.stdout or "").strip()
        if not text:
            raise RuntimeError((proc.stderr or "empty stdout")[:200])
        data = json.loads(text)
        if data.get("ok"):
            _stats["ok"] += 1
            _stats["last_ok_at"] = now
        else:
            _stats["fail"] += 1
            _stats["last_error"] = str(data.get("error") or "sdk ok=false")
        _CACHE[key] = (now, data)
        return data
    except Exception as exc:
        _stats["fail"] += 1
        _stats["last_error"] = str(exc)
        log.debug("stock-sdk bridge %s failed: %s", cmd, exc)
        out = {"ok": False, "error": str(exc), "source": "stock-sdk"}
        _CACHE[key] = (now, out)
        return out


def market_emotion() -> dict:
    return _run("market_emotion")


def fund_flow(code: str) -> dict:
    return _run("fund_flow", code)


def concept_core(board_code: str, stock_code: str) -> dict:
    return _run("concept_core", board_code, stock_code)


def quote_brief(code: str) -> dict:
    return _run("quote", code)


def flow_3d_sum(code: str) -> float | None:
    """Parse SDK fund-flow payload into a 3-day main-force sum when possible."""
    data = fund_flow(code)
    if not data.get("ok"):
        return None
    flow = data.get("flow")
    if flow is None:
        return None
    if isinstance(flow, (int, float)):
        return float(flow)
    if isinstance(flow, list):
        vals = []
        for item in flow[-3:]:
            if isinstance(item, (int, float)):
                vals.append(float(item))
            elif isinstance(item, dict):
                for key in ("main_net", "mainNetInflow", "net", "value", "f62"):
                    if item.get(key) is not None:
                        try:
                            vals.append(float(item[key]))
                            break
                        except (TypeError, ValueError):
                            pass
        return sum(vals) if vals else None
    if isinstance(flow, dict):
        for key in ("main_net_3d", "sum3", "mainNetInflow", "f62"):
            if flow.get(key) is not None:
                try:
                    return float(flow[key])
                except (TypeError, ValueError):
                    pass
        days = flow.get("days") or flow.get("data") or []
        if isinstance(days, list) and days:
            return _sum_day_list(days)
    return None


def _sum_day_list(days: list) -> float | None:
    vals = []
    for item in days[-3:]:
        if not isinstance(item, dict):
            continue
        for key in ("main_net", "mainNetInflow", "net", "value", "f62"):
            if item.get(key) is not None:
                try:
                    vals.append(float(item[key]))
                    break
                except (TypeError, ValueError):
                    pass
    return sum(vals) if vals else None
