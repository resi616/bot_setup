import ccxt
import time
import requests
import numpy as np
from datetime import datetime, timezone

# === CONFIGURATION ===
TELEGRAM_TOKEN = '8152840476:AAHqFTaJn67tLlIwnBWjEZbt5wyvl09FfiI'
CHAT_ID = '-1002520925418'
EXCHANGE = ccxt.binance()
TIMEFRAME = '5m'
CHECK_INTERVAL = 60 * 5  # 5 menit

sent_alerts = set()

# === TOOLS ===
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Gagal kirim pesan: {e}")

def get_ohlcv(symbol, timeframe, limit=100):
    try:
        data = EXCHANGE.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return np.array(data)
    except:
        return None

def compute_stochastic(data, k_period=5, d_period=3):
    highs = data[:, 2]
    lows = data[:, 3]
    closes = data[:, 4]
    k_values = []

    for i in range(k_period - 1, len(closes)):
        high_max = np.max(highs[i - k_period + 1:i + 1])
        low_min = np.min(lows[i - k_period + 1:i + 1])
        k = 100 * (closes[i] - low_min) / (high_max - low_min) if high_max != low_min else 0
        k_values.append(k)

    d_values = [np.mean(k_values[i - d_period + 1:i + 1]) for i in range(d_period - 1, len(k_values))]
    k_values = k_values[d_period - 1:]
    return k_values, d_values

def compute_rsi(closes, period=14):
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = [100. - 100. / (1. + rs)]

    for delta in deltas[period:]:
        up_val = max(delta, 0)
        down_val = -min(delta, 0)
        up = (up * (period - 1) + up_val) / period
        down = (down * (period - 1) + down_val) / period
        rs = up / down if down != 0 else 0
        rsi.append(100. - 100. / (1. + rs))
    return rsi

def detect_stoch_cross(symbol, data):
    k, d = compute_stochastic(data)
    if len(k) < 5 or len(d) < 5:
        return None

    closes = data[:, 4]
    volumes = data[:, 5]
    highs = data[:, 2]
    rsi = compute_rsi(closes)

    for i in range(-5, -1):
        if (
            k[i-1] < d[i-1] and k[i-1] < 20 and d[i-1] < 20 and
            k[i] > d[i] and k[i] > 20 and d[i] > 20
        ):
            volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
            breakout = closes[-1] > np.max(highs[-6:-1])

            if volume_spike and breakout and rsi[-1] > 50:
                last_price = closes[-1]
                k_now = k[-1]
                d_now = d[-1]
                signal_key = f"{symbol}-{last_price:.4f}-{k_now:.2f}-{d_now:.2f}"
                if signal_key in sent_alerts:
                    return None
                sent_alerts.add(signal_key)

                msg = (
                    f"🟢 CROSSING STOCH DETECTED!\n"
                    f"Symbol: {symbol}\n"
                    f"Harga Terakhir: {last_price:.4f}\n"
                    f"K: {k_now:.2f}, D: {d_now:.2f} (cross di atas 20 dari bawah)"
                )
                return msg
    return None

# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Mulai screening pump...")
    try:
        symbols = [m['symbol'] for m in EXCHANGE.load_markets().values()
                   if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]

        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME)
            if data is not None:
                signal = detect_stoch_cross(symbol, data)
                if signal:
                    print(f"[{datetime.now()}] {symbol} crossing terdeteksi!")
                    send_telegram(signal)

        print(f"[{datetime.now()}] Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)