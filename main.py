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
SWING_TIMEFRAME = '1h'
CHECK_INTERVAL = 60 * 15  # 15 menit

sent_signals = set()

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

def find_swing_high_lows(data):
    highs = data[:, 2]
    lows = data[:, 3]
    swing_high = max(highs[-10:])
    swing_low = min(lows[-10:])
    return swing_high, swing_low

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
        swing_data = get_ohlcv(symbol, SWING_TIMEFRAME)
        if swing_data is None:
            return None
        swing_high, swing_low = find_swing_high_lows(swing_data)

        entry = last_close
        tp1 = swing_high
        sl = swing_low

        signal_key = f"{symbol}-{entry:.4f}-{tp1:.4f}-{sl:.4f}"
        if signal_key in sent_signals:
            return None  # Skip duplikat
        sent_signals.add(signal_key)

        msg = (
            f"🟢 SIGNAL ENTRY: {symbol}\n"
            f"Entry: {entry:.4f}\n"
            f"TP: {tp1:.4f}\n"
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
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)
