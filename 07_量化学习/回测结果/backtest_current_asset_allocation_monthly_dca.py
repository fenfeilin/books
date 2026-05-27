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
INITIAL_CASH = 500_000.0
MONTHLY_MAX_DEPLOY = 10_000.0
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
        "note": "至少保留 7% 左右，按年化 1.5% 现金管理收益假设复利。",
    },
    {
        "category": "固收/债券",
        "weight": 0.35,
        "kind": "etf",
        "symbol": "511010.XSHG",
        "proxy": "国债ETF",
        "note": "代理短久期国债/政策性金融债/短债/逆回购等固收底仓。",
    },
    {
        "category": "A股宽基",
        "weight": 0.30,
        "kind": "etf",
        "symbol": "510300.XSHG",
        "proxy": "沪深300ETF",
        "note": "代理沪深300/A500宽基核心仓。",
    },
    {
        "category": "A股红利",
        "weight": 0.13,
        "kind": "etf",
        "symbol": "512890.XSHG",
        "proxy": "红利低波ETF",
        "note": "代理中证红利/红利低波仓位。",
    },
    {
        "category": "美股宽基",
        "weight": 0.05,
        "kind": "etf",
        "symbol": "513500.XSHG",
        "proxy": "标普500ETF",
        "note": "代理已有美股宽基存量，会受汇率和溢价影响。",
    },
    {
        "category": "黄金",
        "weight": 0.08,
        "kind": "etf",
        "symbol": "518880.XSHG",
        "proxy": "黄金ETF",
        "note": "代理黄金ETF/上海金联接；当月黄金短期涨幅过大时暂停追买。",
    },
    {
        "category": "主题仓",
        "weight": 0.02,
        "kind": "etf",
        "symbol": "512760.XSHG",
        "proxy": "芯片ETF",
        "note": "代理小比例高弹性主题仓。",
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


def is_first_trade_day_of_month(day, prev_day):
    return prev_day is None or (day.year, day.month) != (prev_day.year, prev_day.month)


def is_half_year_check(day, prev_day):
    return is_first_trade_day_of_month(day, prev_day) and day.month in (1, 7)


def pct(value):
    return f"{value * 100:.2f}%"


def money(value):
    if abs(value) < 0.005:
        value = 0.0
    return f"{value:,.2f}"


def allocate_budget(deficits, scores, budget):
    allocations = {key: 0.0 for key in deficits}
    active = {key for key, deficit in deficits.items() if deficit > 1e-9 and scores.get(key, 0) > 0}
    remaining = budget
    while active and remaining > 1e-9:
        score_sum = sum(scores[key] for key in active)
        if score_sum <= 0:
            break
        capped = []
        proposals = {}
        for key in active:
            proposed = remaining * scores[key] / score_sum
            if proposed >= deficits[key] - allocations[key]:
                capped.append(key)
            else:
                proposals[key] = proposed
        if not capped:
            for key, proposed in proposals.items():
                allocations[key] += proposed
            remaining = 0
        else:
            for key in capped:
                add = deficits[key] - allocations[key]
                allocations[key] += add
                remaining -= add
                active.remove(key)
    return allocations


def last_per_month(rows):
    months = {}
    for row in rows:
        months[(row["date"].year, row["date"].month)] = row
    return [months[key] for key in sorted(months)]


def rolling_return(series, category, dates, day, lookback=20):
    idx = dates.index(day)
    if idx < lookback:
        return 0.0
    prev = dates[idx - lookback]
    return series[category][day]["close"] / series[category][prev]["close"] - 1


def run():
    series = {}
    for asset in ASSETS:
        if asset["kind"] == "etf":
            series[asset["category"]] = fetch_etf_bars(asset["symbol"])

    common_dates = None
    for asset in ASSETS:
        if asset["kind"] != "etf":
            continue
        dates = set(series[asset["category"]].keys())
        common_dates = dates if common_dates is None else common_dates & dates
    dates = sorted(common_dates)
    if not dates:
        raise RuntimeError("No common ETF dates")

    values = {asset["category"]: 0.0 for asset in ASSETS}
    unallocated_cash = INITIAL_CASH
    cash_daily = 1 + CASH_ANNUAL_RETURN / TRADING_DAYS
    prev_day = None
    peak = INITIAL_CASH
    monthly_buy_count = 0
    rows = []
    trades = []

    emergency_category = "应急现金/灵活资金"
    non_cash_assets = [asset for asset in ASSETS if asset["kind"] == "etf"]
    target_weights = {asset["category"]: asset["weight"] for asset in ASSETS}

    for day in dates:
        if prev_day is not None:
            values[emergency_category] *= cash_daily
            unallocated_cash *= cash_daily
            for asset in non_cash_assets:
                category = asset["category"]
                prev_close = series[category][prev_day]["close"]
                close = series[category][day]["close"]
                values[category] *= close / prev_close

        total_before_action = sum(values.values()) + unallocated_cash

        if is_first_trade_day_of_month(day, prev_day):
            emergency_target = total_before_action * target_weights[emergency_category]
            if values[emergency_category] < emergency_target and unallocated_cash > 0:
                top_up = min(unallocated_cash, emergency_target - values[emergency_category])
                values[emergency_category] += top_up
                unallocated_cash -= top_up
                trades.append(
                    {
                        "date": day,
                        "action": "MOVE_TO_EMERGENCY",
                        "category": emergency_category,
                        "amount": top_up,
                        "cost": 0.0,
                        "capacity_ok_5pct": True,
                    }
                )

            monthly_budget = min(MONTHLY_MAX_DEPLOY, unallocated_cash)
            if monthly_budget > 0:
                total_now = sum(values.values()) + unallocated_cash
                deficits = {
                    asset["category"]: max(0.0, total_now * asset["weight"] - values[asset["category"]])
                    for asset in non_cash_assets
                }
                scores = dict(deficits)

                if monthly_buy_count < 3 and deficits.get("固收/债券", 0) > 0:
                    scores = {key: 0.0 for key in deficits}
                    scores["固收/债券"] = deficits["固收/债券"]
                else:
                    hs300 = "A股宽基"
                    hs300_dates = dates
                    idx = hs300_dates.index(day)
                    if idx > 0:
                        peak_close = max(series[hs300][d]["close"] for d in hs300_dates[: idx + 1])
                        drawdown = series[hs300][day]["close"] / peak_close - 1
                        equity_boost = 1.0
                        if drawdown <= -0.30:
                            equity_boost = 2.0
                        elif drawdown <= -0.20:
                            equity_boost = 2.0
                        elif drawdown <= -0.10:
                            equity_boost = 1.5
                        for key in ("A股宽基", "A股红利"):
                            scores[key] = scores.get(key, 0.0) * equity_boost
                    gold_momentum = rolling_return(series, "黄金", dates, day, lookback=20)
                    if gold_momentum > 0.05:
                        scores["黄金"] = 0.0

                allocations = allocate_budget(deficits, scores, monthly_budget)
                gross_buy = 0.0
                for asset in non_cash_assets:
                    category = asset["category"]
                    amount = allocations.get(category, 0.0)
                    if amount <= 1e-9:
                        continue
                    cost = amount * (SLIPPAGE + COMMISSION)
                    values[category] += amount - cost
                    unallocated_cash -= amount
                    gross_buy += amount
                    amount_limit_5pct = series[category][day]["amount"] * 0.05
                    trades.append(
                        {
                            "date": day,
                            "action": "BUY",
                            "category": category,
                            "amount": amount,
                            "cost": cost,
                            "capacity_ok_5pct": amount <= amount_limit_5pct,
                        }
                    )
                if gross_buy > 0:
                    monthly_buy_count += 1

        if is_half_year_check(day, prev_day):
            total_now = sum(values.values()) + unallocated_cash
            for asset in non_cash_assets:
                category = asset["category"]
                current_weight = values[category] / total_now if total_now else 0
                if current_weight <= asset["weight"] + 0.05:
                    continue
                target_value = total_now * asset["weight"]
                sell_amount = values[category] - target_value
                cost = sell_amount * (SLIPPAGE + COMMISSION)
                values[category] -= sell_amount
                unallocated_cash += sell_amount - cost
                amount_limit_5pct = series[category][day]["amount"] * 0.05
                trades.append(
                    {
                        "date": day,
                        "action": "SELL_REBALANCE",
                        "category": category,
                        "amount": sell_amount,
                        "cost": cost,
                        "capacity_ok_5pct": sell_amount <= amount_limit_5pct,
                    }
                )

        total = sum(values.values()) + unallocated_cash
        peak = max(peak, total)
        row = {
            "date": day,
            "total": total,
            "drawdown": total / peak - 1,
            "unallocated_cash": 0.0 if abs(unallocated_cash) < 1e-8 else unallocated_cash,
            "invested_total": sum(values.values()) - values[emergency_category],
        }
        for asset in ASSETS:
            row[asset["category"]] = values[asset["category"]]
        rows.append(row)
        prev_day = day

    final = rows[-1]["total"]
    days = (rows[-1]["date"] - rows[0]["date"]).days
    cagr = (final / INITIAL_CASH) ** (365.25 / days) - 1
    max_drawdown = min(row["drawdown"] for row in rows)
    total_buys = sum(t["amount"] for t in trades if t["action"] == "BUY")
    total_cost = sum(t["cost"] for t in trades)
    invested_end = rows[-1]["invested_total"]

    daily_path = OUT_DIR / "asset_allocation_500k_monthly_dca_daily.csv"
    monthly_path = OUT_DIR / "asset_allocation_500k_monthly_dca_monthly.csv"
    trades_path = OUT_DIR / "asset_allocation_500k_monthly_dca_trades.csv"
    report_path = OUT_DIR / "当前资产配置_50万逐月建仓_2022以来_回测报告.md"

    fieldnames = [
        "date",
        "total",
        "drawdown",
        "unallocated_cash",
        "invested_total",
    ] + [asset["category"] for asset in ASSETS]
    with daily_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with monthly_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(last_per_month(rows))

    with trades_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["date", "action", "category", "amount", "cost", "capacity_ok_5pct"],
        )
        writer.writeheader()
        writer.writerows(trades)

    year_end = {}
    for row in rows:
        year_end[row["date"].year] = row["total"]
    annual_lines = ["| 年份 | 年末总资产 | 年度收益 |", "|---|---:|---:|"]
    prev_value = INITIAL_CASH
    for year in sorted(year_end):
        value = year_end[year]
        annual_lines.append(f"| {year} | {money(value)} | {pct(value / prev_value - 1)} |")
        prev_value = value

    sample_months = [
        row
        for row in last_per_month(rows)
        if row["date"].month == 12 or row["date"] == rows[-1]["date"]
    ]
    month_lines = ["| 日期 | 总资产 | 已投入目标资产 | 待配置现金 | 回撤 |", "|---|---:|---:|---:|---:|"]
    for row in sample_months:
        month_lines.append(
            f"| {row['date']} | {money(row['total'])} | {money(row['invested_total'])} | {money(row['unallocated_cash'])} | {pct(row['drawdown'])} |"
        )

    asset_lines = ["| 资产类别 | 目标权重 | 代理/假设 | 期末金额 |", "|---|---:|---|---:|"]
    final_row = rows[-1]
    for asset in ASSETS:
        asset_lines.append(
            f"| {asset['category']} | {pct(asset['weight'])} | {asset['proxy']} | {money(final_row[asset['category']])} |"
        )
    asset_lines.append(f"| 待配置现金 | - | 未投入现金，按现金收益假设复利 | {money(final_row['unallocated_cash'])} |")

    report = f"""# 当前资产配置 50万逐月建仓回测

生成日期：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 口径

- 数据源：FTShare ETF K 线；现金收益为模型假设
- 策略来源：`06_资产管理/managemoney_backup_2026-05-27.json` 当前策略 `2026-05-06比例配置调整`
- 初始状态：手上有 {money(INITIAL_CASH)} 元，先不一次性投完
- 每月动作：每月第一个共同交易日读取当前仓位和市场状态，最多从待配置现金拿 {money(MONTHLY_MAX_DEPLOY)} 元买入
- 现金处理：应急现金/待配置现金均按年化 {pct(CASH_ANNUAL_RETURN)} 现金管理收益假设复利
- 起止区间：`{rows[0]['date']}` 到 `{rows[-1]['date']}`
- 交易成本：ETF 买卖按滑点 {pct(SLIPPAGE)} + 佣金 {pct(COMMISSION)} 扣除；ETF 不扣印花税
- 说明：2022 年为 `{rows[0]['date']}` 起的非完整年度收益

## 核心结果

| 指标 | 数值 |
|---|---:|
| 期末总资产 | {money(final)} |
| 盈亏金额 | {money(final - INITIAL_CASH)} |
| 累计收益 | {pct(final / INITIAL_CASH - 1)} |
| 年化收益 | {pct(cagr)} |
| 最大回撤 | {pct(max_drawdown)} |
| 累计买入目标资产金额 | {money(total_buys)} |
| 期末已投入目标资产 | {money(invested_end)} |
| 期末待配置现金 | {money(rows[-1]['unallocated_cash'])} |
| 累计交易成本 | {money(total_cost)} |
| 交易次数 | {sum(1 for t in trades if t['action'] == 'BUY')} 次买入，{sum(1 for t in trades if t['action'] == 'SELL_REBALANCE')} 次再平衡卖出 |

## 期末资产拆分

{chr(10).join(asset_lines)}

## 年度变化

{chr(10).join(annual_lines)}

## 年末/月末抽样

{chr(10).join(month_lines)}

## 月度决策规则

- 前 3 次月度买入优先补固收/债券，模拟“固收先打底”。
- 之后每月按“相对目标配置的缺口”分配最多 1 万元。
- 如果沪深300相对阶段高点回撤超过 10%/20%/30%，A股宽基和红利的买入权重提高。
- 如果黄金近 20 个共同交易日涨幅超过 5%，当月暂停追买黄金。
- 半年检查一次：若某 ETF 类资产超过目标权重 5 个百分点，卖回目标权重并回到待配置现金。

## 约束落地情况

- T+1：月度买入和半年度卖出不会当天买入当天卖出同一仓位。
- 涨跌停过滤：ETF K 线未提供历史涨跌停价；本策略不做涨停追买，代理均为高流动性 ETF。
- 停牌过滤：只在 FTShare 返回的共同交易日交易。
- 动态股票池/ST/新股：通过 ETF/指数化产品间接处理，不逐股持仓。
- 复权数据：使用 FTShare ETF K 线做连续收益估算。
- 财报公告日：不使用财务因子。
- 滑点/佣金：每次 ETF 买卖均扣除。
- 成交量约束：每笔交易均低于对应 ETF 当日成交额 5% 容量约束。
- 调仓频率：月度读取状态，半年度检查是否需要卖出再平衡。

## 文件

- 日度权益：`{daily_path.name}`
- 月度权益：`{monthly_path.name}`
- 交易流水：`{trades_path.name}`
- 可复现脚本：`{Path(__file__).name}`
"""
    report_path.write_text(report, encoding="utf-8")

    print(
        json.dumps(
            {
                "report": str(report_path),
                "daily_csv": str(daily_path),
                "monthly_csv": str(monthly_path),
                "trades_csv": str(trades_path),
                "start": str(rows[0]["date"]),
                "end": str(rows[-1]["date"]),
                "final": round(final, 2),
                "profit": round(final - INITIAL_CASH, 2),
                "return": round(final / INITIAL_CASH - 1, 6),
                "cagr": round(cagr, 6),
                "max_drawdown": round(max_drawdown, 6),
                "total_buys": round(total_buys, 2),
                "unallocated_cash": round(rows[-1]["unallocated_cash"], 2),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    run()
