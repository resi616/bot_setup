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
MIN_RR = 2.0  # Risk-Reward Ratio minimal 1:2

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
    """Perhitungan RSI yang lebih akurat."""
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    # Hitung rata-rata gain/loss untuk periode awal
    avg_gain = np.mean(gains[:period]) if len(gains) >= period else 0
    avg_loss = np.mean(losses[:period]) if len(losses) >= period else 0

    rsi = []
    if avg_loss == 0:
        rsi.append(100 if avg_gain > 0 else 0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100 - (100 / (1 + rs)))

    # Smoothing untuk periode berikutnya
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
    """Menghitung Average True Range (ATR)."""
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
    """Mencari swing high/low dari 20 candle terakhir."""
    highs = data[:, 2]
    lows = data[:, 3]
    swing_high = max(highs[-20:])  # Diperpanjang ke 20 candle
    swing_low = min(lows[-20:])
    return swing_high, swing_low

def detect_signal(symbol, data):
    closes = data[:, 4]
    highs = data[:, 2]
    volumes = data[:, 5]

    last_close = closes[-1]
    rsi = compute_rsi(closes, period=14)
    breakout = last_close > max(highs[-5:-1])
    volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
    rsi_condition = 65 <= rsi[-1] <= 75  # Diperketat untuk sinyal lebih kuat

    if breakout and volume_spike and rsi_condition:
        swing_data = get_ohlcv(symbol, SWING_TIMEFRAME)
        if swing_data is None:
            return None
        swing_high, swing_low = find_swing_high_lows(swing_data)

        # Hitung ATR untuk SL/TP dinamis
        atr = compute_atr(data, period=14)
        if atr == 0:
            return None

        # Tentukan SL berdasarkan swing low atau ATR
        sl = min(swing_low, last_close - 1.5 * atr)
        # Tentukan TP dengan RR minimal 1:2
        risk = last_close - sl
        tp = last_close + (risk * MIN_RR)

        # Validasi TP agar tidak melebihi swing high
        tp = min(tp, swing_high * 1.05)  # Maksimal 5% di atas swing high

        # Validasi RR
        if risk <= 0 or (tp - last_close) / risk < MIN_RR:
            return None

        signal_key = f"{symbol}-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
        if signal_key in sent_signals:
            return None  # Skip duplikat
        sent_signals.add(signal_key)

        msg = (
            f"🟢 SIGNAL ENTRY: {symbol}\n"
            f"Entry: {last_close:.4f}\n"
            f"TP: {tp:.4f}\n"
            f"SL: {sl:.4f}\n"
            f"RR: {(tp - last_close) / (last_close - sl):.2f}:1"
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