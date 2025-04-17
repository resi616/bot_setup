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
    k_values = k_values[d_period - 1:]  # Sesuaikan panjang k_values dengan d_values
    return k_values, d_values

def detect_pump_cross(symbol, data):
    k, d = compute_stochastic(data)
    if len(k) < 2 or len(d) < 2:
        return None

    # Cek crossing dan oversold
    if k[-2] < d[-2] and k[-1] > d[-1] and k[-1] < 20 and d[-1] < 20:
        last_price = data[-1, 4]
        signal_key = f"{symbol}-{last_price:.4f}-{datetime.now(datetime.UTC).isoformat()[:13]}"
        if signal_key in sent_alerts:
            return None
        sent_alerts.add(signal_key)

        msg = (
            f"🟢 POTENSI PUMP TERDETEKSI!"
            f"Symbol: {symbol}"
            f"Harga Terakhir: {last_price:.4f}"
            f"Stoch K: {k[-1]:.2f}, D: {d[-1]:.2f} (crossing di bawah 20)"
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
                signal = detect_pump_cross(symbol, data)
                if signal:
                    print(f"[{datetime.now()}] {symbol} pump terdeteksi!")
                    send_telegram(signal)

        print(f"[{datetime.now()}] Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)
