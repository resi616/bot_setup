import ccxt
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime
import mplfinance as mpf
import matplotlib.pyplot as plt

# === CONFIGURATION ===
TELEGRAM_TOKEN = '7723680969:AAFABMNNFD4OU645wvMfp_AeRVgkMlEfzwI'
CHAT_ID = '-1002643789070'
EXCHANGE = ccxt.binance()
TIMEFRAME = '15m'
SWING_TIMEFRAME = '1h'
CHECK_INTERVAL = 60 * 15  # 15 menit
MIN_RR = 2.0  # Risk-Reward Ratio minimal 1:2

sent_signals = set()

# === TOOLS ===
def send_telegram(msg, chart_path=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload)
        if chart_path:
            photo_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            with open(chart_path, 'rb') as img:
                requests.post(photo_url, files={"photo": img}, data={"chat_id": CHAT_ID})
    except Exception as e:
        print(f"Gagal kirim pesan: {e}")

def get_ohlcv(symbol, timeframe, limit=100):
    try:
        data = EXCHANGE.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return np.array(data)
    except:
        return None

def compute_rsi(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gains[:period]) if len(gains) >= period else 0
    avg_loss = np.mean(losses[:period]) if len(losses) >= period else 0

    rsi = []
    if avg_loss == 0:
        rsi.append(100 if avg_gain > 0 else 0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100 - (100 / (1 + rs)))

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100 if avg_gain > 0 else 0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - (100 / (1 + rs)))

    return rsi

def compute_atr(data, period=14):
    highs = data[:, 2]
    lows = data[:, 3]
    closes = data[:, 4]
    tr = np.zeros(len(data) - 1)
    for i in range(1, len(data)):
        tr[i-1] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
    atr = np.zeros(len(tr) - period + 1)
    for i in range(period, len(tr) + 1):
        atr[i-period] = np.mean(tr[i-period:i])
    return atr[-1] if len(atr) > 0 else 0

def find_swing_high_lows(data):
    highs = data[:, 2]
    lows = data[:, 3]
    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])
    return swing_high, swing_low

def generate_chart(symbol, data, entry, tp, sl, rsi_last):
    df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
    df["Time"] = pd.to_datetime(df["Time"], unit='ms')
    df.set_index("Time", inplace=True)

    apds = [
        mpf.make_addplot([entry]*len(df), color='green', linestyle='--', width=1),
        mpf.make_addplot([tp]*len(df), color='blue', linestyle='--', width=1),
        mpf.make_addplot([sl]*len(df), color='red', linestyle='--', width=1),
    ]

    fig, axes = mpf.plot(df, type='candle', volume=True, addplot=apds, returnfig=True, style='yahoo', title=symbol)
    axes[0].text(0.02, 0.95, f"RSI: {rsi_last:.2f}", transform=axes[0].transAxes, fontsize=10, verticalalignment='top', bbox=dict(boxstyle="round", fc="w"))

    chart_file = f"{symbol.replace('/', '_')}.png"
    fig.savefig(chart_file)
    plt.close(fig)
    return chart_file

def detect_signal(symbol, data):
    closes = data[:, 4]
    highs = data[:, 2]
    volumes = data[:, 5]

    last_close = closes[-1]
    rsi = compute_rsi(closes, period=14)
    breakout = last_close > max(highs[-5:-1])
    volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
    rsi_condition = 65 <= rsi[-1] <= 75

    if breakout and volume_spike and rsi_condition:
        swing_data = get_ohlcv(symbol, SWING_TIMEFRAME)
        if swing_data is None:
            return None
        swing_high, swing_low = find_swing_high_lows(swing_data)

        atr = compute_atr(data, period=14)
        if atr == 0:
            return None

        sl = min(swing_low, last_close - 1.5 * atr)
        risk = last_close - sl
        tp = last_close + (risk * MIN_RR)
        tp = min(tp, swing_high * 1.05)

        if risk <= 0 or (tp - last_close) / risk < MIN_RR:
            return None

        signal_key = f"{symbol}-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
        if signal_key in sent_signals:
            return None
        sent_signals.add(signal_key)

        msg = (
            f"🟢 SIGNAL ENTRY: {symbol}\n"
            f"Entry: {last_close:.4f}\n"
            f"TP: {tp:.4f}\n"
            f"SL: {sl:.4f}\n"
            f"RR: {(tp - last_close) / (last_close - sl):.2f}:1"
        )

        chart_path = generate_chart(symbol, data, last_close, tp, sl, rsi[-1])
        return msg, chart_path
    return None

# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning market...")
    try:
        symbols = [m['symbol'] for m in EXCHANGE.load_markets().values()
                   if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]

        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME)
            if data is not None:
                result = detect_signal(symbol, data)
                if result:
                    msg, chart = result
                    print(f"[{datetime.now()}] {symbol} SIGNAL!")
                    send_telegram(msg, chart)

        print(f"[{datetime.now()}] Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)
