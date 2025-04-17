import ccxt
import time
import requests
import numpy as np
import pandas as pd
from datetime import datetime
import mplfinance as mpf
import matplotlib.pyplot as plt
import os

# === CONFIGURATION ===
TELEGRAM_TOKEN = '7723680969:AAFABMNNFD4OU645wvMfp_AeRVgkMlEfzwI'
CHAT_ID = '-1002643789070'
EXCHANGE = ccxt.binance({
    'enableRateLimit': True,
    'defaultType': 'future'
})
TIMEFRAME = '5m'  # Timeframe: 5 menit
CHECK_INTERVAL = 60 * 15  # 15 menit
MIN_RR = 1.5  # Risk-Reward Ratio 1.5:1
MIN_CANDLES = 10  # Minimal candle untuk atasi data pendek

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
            os.remove(chart_path)
    except Exception as e:
        print(f"Gagal kirim pesan: {e}")

def get_ohlcv(symbol, timeframe, limit=100, retries=5):
    for attempt in range(retries):
        try:
            since = int((time.time() - (limit * 5 * 60)) * 1000)  # 500 menit ke belakang
            data = EXCHANGE.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, since=since, params={'contractType': 'PERPETUAL'})
            data = np.array(data)
            if len(data) == 0:
                print(f"[ERROR] {symbol} - Tidak ada data yang dikembalikan")
                return None
            if len(data) < MIN_CANDLES:
                print(f"[WARNING] {symbol} - Data terlalu pendek: {len(data)} candles, minimal {MIN_CANDLES}")
                return None
            print(f"[INFO] {symbol} - Berhasil mengambil {len(data)} candles")
            return data
        except Exception as e:
            print(f"[ERROR] Gagal ambil data {symbol}, attempt {attempt + 1}/{retries}: {e}")
            time.sleep(3)
    return None

def compute_stoch(highs, lows, closes, k_period=5, d_period=3, smooth_k=3):
    if len(closes) < k_period + d_period + smooth_k:
        return [], [], []
    
    k_values = []
    for i in range(k_period - 1, len(closes)):
        lowest_low = np.min(lows[i - (k_period - 1):i + 1])
        highest_high = np.max(highs[i - (k_period - 1):i + 1])
        if highest_high == lowest_low:
            k = 0
        else:
            k = (closes[i] - lowest_low) / (highest_high - lowest_low) * 100
        k_values.append(k)
    
    d_values = pd.Series(k_values).rolling(window=d_period).mean().values
    slow_d_values = pd.Series(d_values).rolling(window=smooth_k).mean().values
    
    return k_values, d_values, slow_d_values

def compute_atr(data, period=14):
    if len(data) < period + 1:
        return 0
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

def generate_chart(symbol, data, entry, tp, sl, stoch_k, stoch_d):
    try:
        df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
        df["Time"] = pd.to_datetime(df["Time"], unit='ms')
        df.set_index("Time", inplace=True)
        stoch_k = np.pad(stoch_k, (len(df) - len(stoch_k), 0), 'constant', constant_values=np.nan)
        stoch_d = np.pad(stoch_d, (len(df) - len(stoch_d), 0), 'constant', constant_values=np.nan)
        apds = [
            mpf.make_addplot([entry]*len(df), color='green', linestyle='--', width=1),
            mpf.make_addplot([tp]*len(df), color='blue', linestyle='--', width=1),
            mpf.make_addplot([sl]*len(df), color='red', linestyle='--', width=1),
            mpf.make_addplot(stoch_k, color='blue', panel=1, ylabel='Stochastic (5,3,3)'),
            mpf.make_addplot(stoch_d, color='red', panel=1),
            mpf.make_addplot([80]*len(df), color='red', linestyle='--', panel=1),
            mpf.make_addplot([20]*len(df), color='green', linestyle='--', panel=1),
        ]
        chart_file = f"{symbol.replace('/', '_')}_futures_pump.png"
        mpf.plot(
            df,
            type='candle',
            volume=True,
            style='yahoo',
            title=f"{symbol} Futures Pump Signal",
            addplot=apds,
            panel_ratios=(1, 0.5),
            savefig=chart_file
        )
        print(f"Chart disimpan sebagai {chart_file}")
        return chart_file
    except Exception as e:
        send_telegram(f"⚠️ Gagal buat chart untuk {symbol}: {e}")
        return None

def detect_pump(symbol, data):
    if len(data) < MIN_CANDLES:
        print(f"[WARNING] {symbol} - Data tidak cukup untuk analisis: {len(data)} candles")
        return None

    closes = data[:, 4]
    highs = data[:, 2]
    lows = data[:, 3]
    volumes = data[:, 5]

    last_close = closes[-1]
    prev_high = highs[-2]
    stoch_k, stoch_d, slow_d = compute_stoch(highs, lows, closes, k_period=5, d_period=3, smooth_k=3)
    if len(stoch_k) < 2:
        print(f"[WARNING] {symbol} - Gagal menghitung Stochastic, data terlalu pendek")
        return None
    atr = compute_atr(data, period=14)
    if atr == 0:
        print(f"[WARNING] {symbol} - ATR tidak valid")
        return None

    print(f"\n[DEBUG] {symbol} - Stoch K: {stoch_k[-1]:.2f}, Stoch D: {stoch_d[-1]:.2f}, ATR: {atr:.4f}")

    # Kondisi Pump: Oversold + Crossover + Volume Spike
    oversold = stoch_k[-1] < 20 and stoch_d[-1] < 20
    bullish_crossover = stoch_k[-1] > stoch_d[-1] and stoch_k[-2] <= stoch_d[-2]
    volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1]) if len(volumes) > 10 else False
    breakout = last_close > prev_high  # Konfirmasi breakout

    print(f"[DEBUG] Pump - Oversold: {oversold}, Bullish Crossover: {bullish_crossover}, Volume Spike: {volume_spike}, Breakout: {breakout}")

    if oversold and bullish_crossover and volume_spike and breakout:
        sl = last_close - atr
        risk = last_close - sl
        tp = last_close + (risk * MIN_RR)

        if risk <= 0 or (tp - last_close) / risk < MIN_RR:
            print(f"[WARNING] {symbol} - Risk tidak valid untuk pump")
            return None

        signal_key = f"{symbol}-pump-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
        if signal_key in sent_signals:
            return None
        sent_signals.add(signal_key)

        msg = (
            f"🟢 PUMP DETECTION [Futures]: {symbol}\n"
            f"Entry: {last_close:.4f}\nTP: {tp:.4f}\nSL: {sl:.4f}\nRR: {(tp - last_close) / (last_close - sl):.2f}:1"
        )
        chart_path = generate_chart(symbol, data, last_close, tp, sl, stoch_k, stoch_d)
        return msg, chart_path

    return None

# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning futures market for pumps...")
    try:
        markets = EXCHANGE.load_markets()
        symbols = [symbol for symbol in markets.keys()
                   if markets[symbol]['swap'] and markets[symbol]['contract'] and markets[symbol]['quote'] == 'USDT' and '/' in symbol]

        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME, limit=100)
            if data is not None:
                result = detect_pump(symbol, data)
                if result:
                    msg, chart = result
                    print(f"[{datetime.now()}] {symbol} PUMP SIGNAL! (Futures)")
                    send_telegram(msg, chart)
            time.sleep(1)  # Delay untuk rate limit

        print(f"[{datetime.now()}] Selesai scanning (Futures), tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"ERROR: {e}")
        send_telegram(f"\u274c Error saat scan (Futures): {e}")
        time.sleep(60)