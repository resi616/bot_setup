# main.py
import ccxt
import time
import requests
import numpy as np
from datetime import datetime

# === CONFIGURATION ===
TELEGRAM_TOKEN = '7723680969:AAFABMNNFD4OU645wvMfp_AeRVgkMlEfzwI'
CHAT_ID = '-1002643789070'
EXCHANGE = ccxt.binance()
TIMEFRAME = '15m'
CHECK_INTERVAL = 60 * 15  # 15 menit

sent_signals = {}

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
    lows = data[:, 3]
    volumes = data[:, 5]

    last_close = closes[-1]
    rsi = compute_rsi(closes)
    avg_volume = np.mean(volumes[-10:-1])

    # === LONG SETUP ===
    long_breakout = last_close > max(highs[-5:-1])
    long_volume = volumes[-1] > 1.5 * avg_volume
    long_rsi = rsi[-1] > 60

    if long_breakout and long_volume and long_rsi:
        entry = last_close
        tp1 = entry * 1.015
        tp2 = entry * 1.03
        tp3 = entry * 1.05
        tp4 = entry * 1.08
        sl = entry * 0.97

        signal_data = ("LONG", round(entry, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4), round(tp4, 4), round(sl, 4))
        if sent_signals.get(symbol) == signal_data:
            return None  # sama, skip

        sent_signals[symbol] = signal_data

        msg = (
            f"🟢 SIGNAL LONG: {symbol}\n"
            f"Entry: {entry:.4f}\n"
            f"TP1: {tp1:.4f}\n"
            f"TP2: {tp2:.4f}\n"
            f"TP3: {tp3:.4f}\n"
            f"TP4: {tp4:.4f}\n"
            f"SL: {sl:.4f}"
        )
        return msg

    # === SHORT SETUP ===
    short_breakdown = last_close < min(lows[-5:-1])
    short_volume = volumes[-1] > 1.5 * avg_volume
    short_rsi = rsi[-1] < 40

    if short_breakdown and short_volume and short_rsi:
        entry = last_close
        tp1 = entry * 0.985
        tp2 = entry * 0.97
        tp3 = entry * 0.95
        tp4 = entry * 0.92
        sl = entry * 1.03

        signal_data = ("SHORT", round(entry, 4), round(tp1, 4), round(tp2, 4), round(tp3, 4), round(tp4, 4), round(sl, 4))
        if sent_signals.get(symbol) == signal_data:
            return None  # sama, skip

        sent_signals[symbol] = signal_data

        msg = (
            f"🔴 SIGNAL SHORT: {symbol}\n"
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
                   if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]

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
        send_telegram(f"❌ Error saat scan: {e}")
        time.sleep(60)
