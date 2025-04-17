import ccxt
import time
import requests
import numpy as np
from datetime import datetime

# === CONFIG ===
TELEGRAM_TOKEN = '7881384249:AAFLRCsETKh6Mr4Dh0s3KdSjrDdNdwNn2G4'
CHAT_ID = '-1002520925418'
EXCHANGE = ccxt.binance()
TIMEFRAME = '15m'
CHECK_INTERVAL = 60 * 15  # 15 menit

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

    stoch_k = []
    for i in range(k_period - 1, len(closes)):
        low_min = np.min(lows[i - k_period + 1:i + 1])
        high_max = np.max(highs[i - k_period + 1:i + 1])
        k = 100 * (closes[i] - low_min) / (high_max - low_min) if high_max != low_min else 0
        stoch_k.append(k)

    stoch_d = [np.mean(stoch_k[i - d_period + 1:i + 1]) for i in range(d_period - 1, len(stoch_k))]
    return stoch_k[-len(stoch_d):], stoch_d

def detect_stoch_cross(symbol, data):
    stoch_k, stoch_d = compute_stochastic(data)
    if len(stoch_k) < 2 or len(stoch_d) < 2:
        return None

    # Check crossing %K naik menembus %D (bullish cross)
    if stoch_k[-2] < stoch_d[-2] and stoch_k[-1] > stoch_d[-1]:
        key = f"{symbol}-{int(data[-1, 0] / 1000)}"
        if key in sent_alerts:
            return None  # Skip duplikat
        sent_alerts.add(key)

        msg = (
            f"🚨 POSSIBLE PUMP DETECTED!\n"
            f"Symbol: {symbol}\n"
            f"Timeframe: {TIMEFRAME}\n"
            f"Stoch %K: {stoch_k[-2]:.2f} -> {stoch_k[-1]:.2f}\n"
            f"Stoch %D: {stoch_d[-2]:.2f} -> {stoch_d[-1]:.2f}\n"
            f"📈 Crossing Terjadi: Bullish"
        )
        return msg
    return None

# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning market for possible pump...")
    try:
        symbols = [m['symbol'] for m in EXCHANGE.load_markets().values()
                   if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]

        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME)
            if data is not None:
                signal = detect_stoch_cross(symbol, data)
                if signal:
                    print(f"[{datetime.now()}] ALERT: {symbol} - Crossing Terdeteksi")
                    send_telegram(signal)

        print(f"[{datetime.now()}] Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"❌ Error saat scanning: {e}")
        time.sleep(60)
