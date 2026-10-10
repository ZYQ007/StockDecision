import json
import sqlite3
from pathlib import Path
from threading import Lock

from app.engine.levels import Bar

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_bars (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS factors (
    code TEXT PRIMARY KEY,
    as_of TEXT NOT NULL,
    ref_date TEXT,
    ma5 REAL,
    ma10 REAL,
    ma20 REAL,
    ma60 REAL,
    ma20_up INTEGER,
    high_20 REAL,
    low_20 REAL,
    close_10_ago REAL,
    avg_amount_5 REAL,
    avg_volume_5 REAL,
    ref_close REAL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    price REAL,
    verdict TEXT,
    setup_type TEXT,
    market_regime TEXT,
    sector_name TEXT,
    sector_rank INTEGER,
    detail_json TEXT,
    source TEXT,
    ret_1d REAL,
    ret_3d REAL,
    ret_5d REAL,
    max_dd_5d REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_signal ON signals(trade_date, code);

CREATE TABLE IF NOT EXISTS stock_boards (
    code TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS board_closes (
    board_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    close REAL NOT NULL,
    PRIMARY KEY (board_code, trade_date)
);

CREATE TABLE IF NOT EXISTS sector_days (
    trade_date TEXT NOT NULL,
    name TEXT NOT NULL,
    rank INTEGER,
    total INTEGER,
    pct REAL,
    amount REAL,
    inflow REAL,
    source TEXT,
    PRIMARY KEY (trade_date, name)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT,
    entry_price REAL NOT NULL,
    entry_date TEXT NOT NULL,
    stop_pct REAL NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE INDEX IF NOT EXISTS ix_positions_open ON positions(status, code);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def replace_bars(self, code: str, bars: list[Bar]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM daily_bars WHERE code = ?", (code,))
            self.conn.executemany(
                "INSERT INTO daily_bars(code, trade_date, open, high, low, close, volume, amount) VALUES (?,?,?,?,?,?,?,?)",
                [(code, b.trade_date, b.open, b.high, b.low, b.close, b.volume, b.amount) for b in bars],
            )
            self.conn.commit()

    def load_bars(self, code: str) -> list[Bar]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT trade_date, open, high, low, close, volume, amount FROM daily_bars WHERE code = ? ORDER BY trade_date",
                (code,),
            ).fetchall()
        return [Bar(r["trade_date"], r["open"], r["high"], r["low"], r["close"], r["volume"], r["amount"]) for r in rows]

    def save_factor(self, code: str, as_of: str, ref: dict) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO factors(code, as_of, ref_date, ma5, ma10, ma20, ma60, ma20_up, high_20, low_20,
                                    close_10_ago, avg_amount_5, avg_volume_5, ref_close)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET
                    as_of=excluded.as_of, ref_date=excluded.ref_date, ma5=excluded.ma5, ma10=excluded.ma10,
                    ma20=excluded.ma20, ma60=excluded.ma60, ma20_up=excluded.ma20_up, high_20=excluded.high_20,
                    low_20=excluded.low_20, close_10_ago=excluded.close_10_ago, avg_amount_5=excluded.avg_amount_5,
                    avg_volume_5=excluded.avg_volume_5, ref_close=excluded.ref_close
                """,
                (
                    code,
                    as_of,
                    ref.get("ref_date"),
                    ref.get("ma5"),
                    ref.get("ma10"),
                    ref.get("ma20"),
                    ref.get("ma60"),
                    1 if ref.get("ma20_up") else 0,
                    ref.get("high_20"),
                    ref.get("low_20"),
                    ref.get("close_10_ago"),
                    ref.get("avg_amount_5"),
                    ref.get("avg_volume_5"),
                    ref.get("ref_close"),
                ),
            )
            self.conn.commit()

    def get_factor(self, code: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM factors WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["ma20_up"] = bool(data["ma20_up"])
        return data

    def factor_codes_as_of(self, as_of: str) -> set[str]:
        with self._lock:
            rows = self.conn.execute("SELECT code FROM factors WHERE as_of = ?", (as_of,)).fetchall()
        return {r["code"] for r in rows}

    def insert_signal(self, row: dict) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO signals(
                    ts, trade_date, code, name, price, verdict, setup_type, market_regime,
                    sector_name, sector_rank, detail_json, source
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["ts"],
                    row["trade_date"],
                    row["code"],
                    row["name"],
                    row["price"],
                    row["verdict"],
                    row["setup_type"],
                    row["market_regime"],
                    row["sector_name"],
                    row["sector_rank"],
                    row["detail_json"],
                    row["source"],
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def open_signals(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM signals WHERE verdict = '可买' AND (ret_1d IS NULL OR ret_3d IS NULL OR ret_5d IS NULL)"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_returns(self, signal_id: int, ret_1d, ret_3d, ret_5d, max_dd) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE signals SET ret_1d=?, ret_3d=?, ret_5d=?, max_dd_5d=? WHERE id=?",
                (ret_1d, ret_3d, ret_5d, max_dd, signal_id),
            )
            self.conn.commit()

    def save_sector_snapshot(self, trade_date: str, rows: list[dict]) -> None:
        if not trade_date or not rows:
            return
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO sector_days(trade_date, name, rank, total, pct, amount, inflow, source)
                VALUES (?,?,?,?,?,?,?, 'official')
                ON CONFLICT(trade_date, name) DO UPDATE SET
                    rank=excluded.rank,
                    total=excluded.total,
                    pct=excluded.pct,
                    amount=excluded.amount,
                    inflow=COALESCE(excluded.inflow, sector_days.inflow),
                    source='official'
                """,
                [
                    (
                        trade_date,
                        row["name"],
                        row.get("rank"),
                        row.get("total"),
                        row.get("pct"),
                        row.get("amount"),
                        row.get("inflow"),
                    )
                    for row in rows
                    if row.get("name")
                ],
            )
            self.conn.commit()

    def save_sector_inflows(self, rows: list[dict]) -> None:
        if not rows:
            return
        with self._lock:
            for row in rows:
                if not row.get("name") or not row.get("trade_date") or row.get("inflow") is None:
                    continue
                self.conn.execute(
                    """
                    INSERT INTO sector_days(trade_date, name, inflow, source)
                    VALUES (?,?,?, 'flow')
                    ON CONFLICT(trade_date, name) DO UPDATE SET
                        inflow=excluded.inflow
                    """,
                    (row["trade_date"], row["name"], row["inflow"]),
                )
            self.conn.commit()

    def load_official_sectors(self) -> dict[str, dict[str, dict]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT trade_date, name, rank, total, pct, amount, inflow FROM sector_days"
            ).fetchall()
        out: dict[str, dict[str, dict]] = {}
        for row in rows:
            out.setdefault(row["name"], {})[row["trade_date"]] = {
                "rank": row["rank"],
                "total": row["total"],
                "pct": row["pct"],
                "amount": row["amount"],
                "inflow": row["inflow"],
            }
        return out

    def load_close_series(self, skip_codes: set[str] | None = None) -> dict[str, list[tuple[str, float]]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT code, trade_date, close FROM daily_bars ORDER BY code, trade_date"
            ).fetchall()
        skip = skip_codes or set()
        out: dict[str, list[tuple[str, float]]] = {}
        for row in rows:
            if row["code"] in skip or row["close"] is None:
                continue
            out.setdefault(row["code"], []).append((row["trade_date"], row["close"]))
        return out

    def save_stock_boards(self, code: str, trade_date: str, payload: dict) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_boards(code, trade_date, payload) VALUES (?,?,?)
                ON CONFLICT(code) DO UPDATE SET trade_date=excluded.trade_date, payload=excluded.payload
                """,
                (code, trade_date, json.dumps(payload, ensure_ascii=False)),
            )
            self.conn.commit()

    def get_stock_boards(self, code: str) -> dict | None:
        with self._lock:
            row = self.conn.execute("SELECT trade_date, payload FROM stock_boards WHERE code = ?", (code,)).fetchone()
        if not row:
            return None
        return {"trade_date": row["trade_date"], "data": json.loads(row["payload"])}

    def save_board_closes(self, board_code: str, rows: list[tuple[str, float]]) -> None:
        if not rows:
            return
        with self._lock:
            self.conn.executemany(
                """
                INSERT INTO board_closes(board_code, trade_date, close) VALUES (?,?,?)
                ON CONFLICT(board_code, trade_date) DO UPDATE SET close=excluded.close
                """,
                [(board_code, trade_date, close) for trade_date, close in rows],
            )
            self.conn.commit()

    def load_board_closes(self) -> dict[str, dict[str, float]]:
        with self._lock:
            rows = self.conn.execute("SELECT board_code, trade_date, close FROM board_closes").fetchall()
        out: dict[str, dict[str, float]] = {}
        for row in rows:
            out.setdefault(row["board_code"], {})[row["trade_date"]] = row["close"]
        return out

    def signal_rows(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT setup_type, ret_1d, ret_3d, ret_5d, max_dd_5d FROM signals WHERE verdict = '可买'"
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_buy_signals(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, trade_date, code, name, price, setup_type, sector_name, sector_rank,
                       ret_1d, ret_3d, ret_5d, max_dd_5d, detail_json, source
                FROM signals WHERE verdict = '可买'
                ORDER BY trade_date DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_open_position(self, row: dict) -> dict:
        with self._lock:
            existing = self.conn.execute(
                "SELECT id FROM positions WHERE code = ? AND status = 'open'",
                (row["code"],),
            ).fetchone()
            if existing:
                self.conn.execute(
                    """
                    UPDATE positions
                    SET name=?, entry_price=?, entry_date=?, stop_pct=?, note=?, created_at=?
                    WHERE id=?
                    """,
                    (
                        row.get("name") or "",
                        row["entry_price"],
                        row["entry_date"],
                        row["stop_pct"],
                        row.get("note") or "",
                        row["created_at"],
                        existing["id"],
                    ),
                )
                pos_id = existing["id"]
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO positions(code, name, entry_price, entry_date, stop_pct, note, status, created_at)
                    VALUES (?,?,?,?,?,?, 'open', ?)
                    """,
                    (
                        row["code"],
                        row.get("name") or "",
                        row["entry_price"],
                        row["entry_date"],
                        row["stop_pct"],
                        row.get("note") or "",
                        row["created_at"],
                    ),
                )
                pos_id = cur.lastrowid
            self.conn.commit()
            out = self.conn.execute("SELECT * FROM positions WHERE id = ?", (pos_id,)).fetchone()
        return dict(out)

    def open_positions(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_date DESC, id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def close_position(self, code: str, closed_at: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE positions SET status = 'closed', closed_at = ?
                WHERE code = ? AND status = 'open'
                """,
                (closed_at, code),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def get_open_position(self, code: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM positions WHERE code = ? AND status = 'open'",
                (code,),
            ).fetchone()
        return dict(row) if row else None
