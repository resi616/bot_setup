# main.py
import ccxt
import time
import requests
import numpy as np
from datetime import datetime

# === CONFIGURATION ===
TELEGRAM_TOKEN = '7723680969:AAFABMNNFD4OU645wvMfp_AeRVgkMlEfzwI'
CHAT_ID = '-1002643789070'
EXCHANGE = ccxt.binance({
    'options': {'defaultType': 'future'}
})

TIMEFRAME = '15m'
CHECK_INTERVAL = 60 * 15  # 15 menit

# === TOOLS ===
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": msg}
    try:
        requests.post(url, json=payload)  # pakai json biar aman emoji/UTF-8
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


def detect_signal(symbol, data):
    closes = data[:, 4]
    highs = data[:, 2]
    volumes = data[:, 5]

    last_close = closes[-1]
    rsi = compute_rsi(closes)
    breakout = last_close > max(highs[-5:-1])
    volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
    rsi_condition = rsi[-1] > 60

    if breakout and volume_spike and rsi_condition:
        entry = last_close
        tp1 = entry * 1.015
        tp2 = entry * 1.03
        tp3 = entry * 1.05
        tp4 = entry * 1.08
        sl = entry * 0.97

        msg = (
            f"\ud83d\udea8 SIGNAL ENTRY: {symbol}\n"
            f"Entry: {entry:.4f}\n"
            f"TP1: {tp1:.4f}\n"
            f"TP2: {tp2:.4f}\n"
            f"TP3: {tp3:.4f}\n"
            f"TP4: {tp4:.4f}\n"
            f"SL: {sl:.4f}"
        )
        return msg
    return None

# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning market...")
    try:
        symbols = [m['symbol'] for m in EXCHANGE.load_markets().values()
           if m['quote'] == 'USDT' and m['contract'] and '/' in m['symbol']]


        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME)
            if data is not None:
                signal = detect_signal(symbol, data)
                if signal:
                    print(f"[{datetime.now()}] {symbol} SIGNAL!")
                    send_telegram(signal)

        print(f"[{datetime.now()}] Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)
