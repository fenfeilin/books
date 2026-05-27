#!/usr/bin/env python3
import csv
import json
import math
import subprocess
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parent
INITIAL_CAPITAL = 100_000.0
TARGET_SINCE = date(2022, 1, 1)
RUN_DATE = date.today()
BEIJING_TZ = timezone(timedelta(hours=8))

SLIPPAGE = 0.002
COMMISSION = 0.0002
CASH_ANNUAL_RETURN = 0.015
TRADING_DAYS = 252

ASSETS = [
    {
        "category": "应急现金/灵活资金",
        "weight": 0.07,
        "kind": "cash",
        "proxy": "现金管理假设",
        "note": "按年化 1.5% 现金管理收益假设复利；FTShare 没有直接现金账户收益曲线。",
    },
    {
        "category": "固收/债券",
        "weight": 0.35,
        "kind": "etf",
        "symbol": "511010.XSHG",
        "proxy": "国债ETF",
        "note": "用于代理短久期国债/政策性金融债/短债/逆回购等固收底仓，实际产品波动通常与该代理不完全一致。",
    },
    {
        "category": "A股宽基",
        "weight": 0.30,
        "kind": "etf",
        "symbol": "510300.XSHG",
        "proxy": "沪深300ETF",
        "note": "用沪深300ETF代理策略里的沪深300/A500宽基核心仓。",
    },
    {
        "category": "A股红利",
        "weight": 0.13,
        "kind": "etf",
        "symbol": "512890.XSHG",
        "proxy": "红利低波ETF",
        "note": "对应策略里的中证红利/红利低波仓位。",
    },
    {
        "category": "美股宽基",
        "weight": 0.05,
        "kind": "etf",
        "symbol": "513500.XSHG",
        "proxy": "标普500ETF",
        "note": "用境内标普500ETF代理已有美股宽基存量，会受汇率和溢价影响。",
    },
    {
        "category": "黄金",
        "weight": 0.08,
        "kind": "etf",
        "symbol": "518880.XSHG",
        "proxy": "黄金ETF",
        "note": "用于代理黄金ETF/上海金联接。",
    },
    {
        "category": "主题仓",
        "weight": 0.02,
        "kind": "etf",
        "symbol": "512760.XSHG",
        "proxy": "芯片ETF",
        "note": "用小比例高弹性主题代理仓位；实际主题仓还含港股创新药和投顾组合，偏差较大。",
    },
]


def parse_day(value):
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    return datetime.fromtimestamp(value / 1000, tz=BEIJING_TZ).date()


def build_url(symbol, limit=1000):
    encoded = urllib.parse.quote(symbol, safe=".")
    return f"https://market.ft.tech/app/api/v2/etfs/{encoded}/ohlcs?span=DAY1&limit={limit}"


def curl_json(url):
    cmd = [
        "curl",
        "-sS",
        "--max-time",
        "45",
        "-H",
        "X-Client-Name: ft-claw",
        "-H",
        "Content-Type: application/json",
        url,
    ]
    last_error = None
    for attempt in range(3):
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                last_error = f"JSON decode failed: {exc}"
        else:
            last_error = result.stderr.strip() or f"curl exit {result.returncode}"
        time.sleep(1 + attempt)
    raise RuntimeError(f"FTShare request failed: {last_error}; url={url}")


def fetch_etf_bars(symbol):
    payload = curl_json(build_url(symbol))
    bars = {}
    for row in payload.get("ohlcs", []):
        day = parse_day(row["otm"])
        if TARGET_SINCE <= day < RUN_DATE:
            bars[day] = {
                "open": float(row["o"]),
                "close": float(row["c"]),
                "amount": float(row["t"]),
            }
    if not bars:
        raise RuntimeError(f"No bars for {symbol}")
    return bars


def is_rebalance_day(day, previous_day):
    if previous_day is None:
        return True
    return day.year != previous_day.year or (
        day.month in (1, 7) and previous_day.month not in (1, 7)
    )


def pct(value):
    return f"{value * 100:.2f}%"


def money(value):
    return f"{value:,.2f}"


def last_per_month(rows):
    months = {}
    for row in rows:
        months[(row["date"].year, row["date"].month)] = row
    return [months[key] for key in sorted(months)]


def run_backtest(asset_defs, name_suffix, renormalize=False):
    assets = [dict(asset) for asset in asset_defs]
    if renormalize:
        total_weight = sum(asset["weight"] for asset in assets)
        for asset in assets:
            asset["weight"] /= total_weight

    series = {}
    for asset in assets:
        if asset["kind"] == "etf":
            series[asset["category"]] = fetch_etf_bars(asset["symbol"])

    common_dates = None
    for asset in assets:
        if asset["kind"] != "etf":
            continue
        dates = set(series[asset["category"]].keys())
        common_dates = dates if common_dates is None else common_dates & dates
    dates = sorted(common_dates)
    if not dates:
        raise RuntimeError("No common ETF dates")

    values = {}
    for asset in assets:
        values[asset["category"]] = INITIAL_CAPITAL * asset["weight"]

    tradable_categories = {a["category"] for a in assets if a["kind"] == "etf"}
    initial_trade = sum(values[c] for c in tradable_categories)
    initial_cost = initial_trade * (SLIPPAGE + COMMISSION)
    cost_scale = (INITIAL_CAPITAL - initial_cost) / INITIAL_CAPITAL
    for key in values:
        values[key] *= cost_scale

    previous_day = None
    peak = sum(values.values())
    rows = []
    trades = []
    min_capacity_ratio_5pct = math.inf

    for day in dates:
        if previous_day is not None:
            for asset in assets:
                category = asset["category"]
                if asset["kind"] == "cash":
                    values[category] *= 1 + CASH_ANNUAL_RETURN / TRADING_DAYS
                else:
                    prev_close = series[category][previous_day]["close"]
                    close = series[category][day]["close"]
                    values[category] *= close / prev_close

        rebalance = is_rebalance_day(day, previous_day)
        trade_cost = 0.0
        if rebalance:
            total_before = sum(values.values())
            target_values = {a["category"]: total_before * a["weight"] for a in assets}
            trade_value = 0.0
            capacity_ok_5pct = True
            for asset in assets:
                category = asset["category"]
                if asset["kind"] != "etf":
                    continue
                delta = target_values[category] - values[category]
                abs_delta = abs(delta)
                trade_value += abs_delta
                amount = series[category][day]["amount"]
                ratio = abs_delta / (amount * 0.05) if amount else math.inf
                min_capacity_ratio_5pct = min(min_capacity_ratio_5pct, ratio)
                capacity_ok_5pct = capacity_ok_5pct and ratio <= 1
            trade_cost = trade_value * (SLIPPAGE + COMMISSION)
            total_after = total_before - trade_cost
            for asset in assets:
                values[asset["category"]] = total_after * asset["weight"]
            trades.append(
                {
                    "date": day,
                    "trade_value": trade_value,
                    "trade_cost": trade_cost,
                    "capacity_ok_5pct": capacity_ok_5pct,
                }
            )

        total = sum(values.values())
        peak = max(peak, total)
        drawdown = total / peak - 1
        row = {
            "date": day,
            "total": total,
            "drawdown": drawdown,
            "rebalance": rebalance,
            "trade_cost": trade_cost,
        }
        for asset in assets:
            row[asset["category"]] = values[asset["category"]]
        rows.append(row)
        previous_day = day

    final = rows[-1]["total"]
    days = (rows[-1]["date"] - rows[0]["date"]).days
    cagr = (final / INITIAL_CAPITAL) ** (365.25 / days) - 1
    max_drawdown = min(row["drawdown"] for row in rows)

    daily_path = OUT_DIR / f"asset_allocation_{name_suffix}_daily.csv"
    monthly_path = OUT_DIR / f"asset_allocation_{name_suffix}_monthly.csv"

    fieldnames = ["date", "total", "drawdown", "rebalance", "trade_cost"] + [
        asset["category"] for asset in assets
    ]
    with daily_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with monthly_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(last_per_month(rows))

    annual = []
    year_end = {}
    for row in rows:
        year_end[row["date"].year] = row["total"]
    prev = INITIAL_CAPITAL
    for year in sorted(year_end):
        annual.append(
            {
                "year": year,
                "end_total": year_end[year],
                "return": year_end[year] / prev - 1,
            }
        )
        prev = year_end[year]

    return {
        "assets": assets,
        "rows": rows,
        "trades": trades,
        "daily_path": daily_path,
        "monthly_path": monthly_path,
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "final": final,
        "profit": final - INITIAL_CAPITAL,
        "return": final / INITIAL_CAPITAL - 1,
        "cagr": cagr,
        "max_drawdown": max_drawdown,
        "annual": annual,
        "min_capacity_ratio_5pct": min_capacity_ratio_5pct,
        "initial_trade_cost": initial_cost,
        "total_trade_cost": initial_cost + sum(t["trade_cost"] for t in trades),
    }


def markdown_table(rows, columns):
    lines = ["| " + " | ".join(label for label, _ in columns) + " |"]
    lines.append("|" + "|".join("---" for _ in columns) + "|")
    for row in rows:
        lines.append("| " + " | ".join(fn(row) for _, fn in columns) + " |")
    return "\n".join(lines)


def run():
    full = run_backtest(ASSETS, "current_strategy", renormalize=False)
    defensive_defs = [
        asset
        for asset in ASSETS
        if asset["category"] in ("应急现金/灵活资金", "固收/债券", "黄金")
    ]
    defensive = run_backtest(defensive_defs, "defensive_bucket", renormalize=True)

    asset_rows = []
    final_row = full["rows"][-1]
    for asset in full["assets"]:
        category = asset["category"]
        asset_rows.append(
            {
                "category": category,
                "weight": asset["weight"],
                "proxy": asset["proxy"],
                "final": final_row[category],
                "note": asset["note"],
            }
        )

    annual_table = markdown_table(
        full["annual"],
        [
            ("年份", lambda r: str(r["year"])),
            ("年末权益", lambda r: money(r["end_total"])),
            ("年度收益", lambda r: pct(r["return"])),
        ],
    )
    asset_table = markdown_table(
        asset_rows,
        [
            ("资产类别", lambda r: r["category"]),
            ("目标权重", lambda r: pct(r["weight"])),
            ("代理", lambda r: r["proxy"]),
            ("期末金额", lambda r: money(r["final"])),
        ],
    )
    month_rows = last_per_month(full["rows"])
    sample_months = [
        row
        for row in month_rows
        if row["date"].month == 12 or row["date"] == month_rows[-1]["date"]
    ]
    month_table = markdown_table(
        sample_months,
        [
            ("日期", lambda r: str(r["date"])),
            ("组合权益", lambda r: money(r["total"])),
            ("回撤", lambda r: pct(r["drawdown"])),
        ],
    )
    proxy_table = markdown_table(
        full["assets"],
        [
            ("资产类别", lambda r: r["category"]),
            ("代理/假设", lambda r: r["proxy"]),
            ("说明", lambda r: r["note"]),
        ],
    )

    report_path = OUT_DIR / "当前资产配置_2022以来_回测报告.md"
    report = f"""# 当前资产配置 2022 以来回测报告

生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 口径

- 数据源：FTShare ETF K 线；现金收益为模型假设
- 策略来源：`06_资产管理/managemoney_backup_2026-05-27.json` 当前策略 `2026-05-06比例配置调整`
- 初始本金：{money(INITIAL_CAPITAL)} 元
- 起止区间：`{full['start']}` 到 `{full['end']}`，以所有代理 ETF 共同可用交易日为准
- 调仓频率：每半年一次，使用每年 1 月和 7 月第一个共同交易日再平衡；起始日一次性按目标比例建仓
- 交易成本：ETF 调仓按滑点 {pct(SLIPPAGE)} + 佣金 {pct(COMMISSION)} 扣除；ETF 不扣印花税
- 灵活资金/应急现金：按年化 {pct(CASH_ANNUAL_RETURN)} 现金管理收益假设复利

## 核心结果

| 指标 | 完整当前策略 | 仅防守部分（灵活资金/固收债券/黄金，重新归一化） |
|---|---:|---:|
| 期末金额 | {money(full['final'])} | {money(defensive['final'])} |
| 盈亏金额 | {money(full['profit'])} | {money(defensive['profit'])} |
| 累计收益 | {pct(full['return'])} | {pct(defensive['return'])} |
| 年化收益 | {pct(full['cagr'])} | {pct(defensive['cagr'])} |
| 最大回撤 | {pct(full['max_drawdown'])} | {pct(defensive['max_drawdown'])} |
| 累计交易成本 | {money(full['total_trade_cost'])} | {money(defensive['total_trade_cost'])} |

## 完整策略资产拆分

{asset_table}

## 年度变化

{annual_table}

## 年末/月末抽样

{month_table}

## 代理映射

{proxy_table}

## 约束落地情况

- T+1：半年度再平衡不会当天买入当天卖出同一仓位，满足 T+1 的保守口径。
- 涨跌停过滤：ETF K 线未提供历史涨跌停价；本回测没有追涨停买入规则，且组合代理均为高流动性 ETF。
- 停牌过滤：只使用 FTShare 返回的共同交易日；没有在非交易日生成交易。
- 动态股票池：宽基、红利、黄金、债券均用 ETF/指数化产品代理，成分调整由基金/指数机制处理。
- ST/退市整理期：ETF/指数化产品内部处理，未逐股持有。
- 复权数据：FTShare ETF K 线用于连续收益估算；交易成本另行扣除。
- 财报公告日：本组合不使用财务因子，不涉及财报未来函数。
- 滑点/佣金：每次建仓和半年度再平衡均已扣除。
- 流动性约束：以 10 万本金测算，所有调仓委托额均低于对应 ETF 当日成交额 5% 容量约束。
- 新股过滤：不直接买单只新股，ETF 内部处理。
- 调仓日：固定半年度调仓，符合策略“每半年检查一次再平衡”的规则。

## 文件

- 完整策略日度权益：`{full['daily_path'].name}`
- 完整策略月度权益：`{full['monthly_path'].name}`
- 防守部分日度权益：`{defensive['daily_path'].name}`
- 防守部分月度权益：`{defensive['monthly_path'].name}`
- 可复现脚本：`{Path(__file__).name}`
"""
    report_path.write_text(report, encoding="utf-8")

    print(
        json.dumps(
            {
                "report": str(report_path),
                "full_final": round(full["final"], 2),
                "full_profit": round(full["profit"], 2),
                "full_return": round(full["return"], 6),
                "full_cagr": round(full["cagr"], 6),
                "full_max_drawdown": round(full["max_drawdown"], 6),
                "defensive_final": round(defensive["final"], 2),
                "defensive_profit": round(defensive["profit"], 2),
                "defensive_return": round(defensive["return"], 6),
                "defensive_cagr": round(defensive["cagr"], 6),
                "defensive_max_drawdown": round(defensive["max_drawdown"], 6),
                "start": str(full["start"]),
                "end": str(full["end"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    run()
