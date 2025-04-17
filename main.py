import ccxt
import time
import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime
import os

# === CONFIGURATION ===
TELEGRAM_TOKEN = '7881384249:AAFLRCsETKh6Mr4Dh0s3KdSjrDdNdwNn2G4'
CHAT_ID = '-1002520925418'
EXCHANGE = ccxt.binance()
TIMEFRAME = '15m'
CHECK_INTERVAL = 60 * 15  # 15 menit
MIN_VOLUME_24H = 100000  # Min volume
sent_signals = set()


# === TOOLS ===
def send_telegram(msg, chart_path=None):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg}
        )
        if chart_path:
            with open(chart_path, 'rb') as img:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
                    files={"photo": img}, data={"chat_id": CHAT_ID}
                )
            os.remove(chart_path)
    except Exception as e:
        print(f"Gagal kirim telegram: {e}")


def get_ohlcv(symbol, timeframe='15m', limit=100):
    for _ in range(3):
        try:
            return np.array(EXCHANGE.fetch_ohlcv(symbol, timeframe, limit=limit))
        except:
            time.sleep(1)
    return None


def compute_stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3):
    deltas = np.diff(closes)
    seed = deltas[:rsi_period]
    up = seed[seed >= 0].sum() / rsi_period
    down = -seed[seed < 0].sum() / rsi_period
    rs = up / down if down != 0 else 0
    rsi = [100 - 100 / (1 + rs)]

    for delta in deltas[rsi_period:]:
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up = (up * (rsi_period - 1) + upval) / rsi_period
        down = (down * (rsi_period - 1) + downval) / rsi_period
        rs = up / down if down != 0 else 0
        rsi.append(100 - 100 / (1 + rs))

    rsi = np.array(rsi)
    stoch_rsi = (rsi - pd.Series(rsi).rolling(stoch_period).min()) / (
        pd.Series(rsi).rolling(stoch_period).max() - pd.Series(rsi).rolling(stoch_period).min())
    stoch_rsi_k = stoch_rsi.rolling(smooth_k).mean()
    stoch_rsi_d = stoch_rsi_k.rolling(smooth_d).mean()
    return stoch_rsi_k, stoch_rsi_d


def is_cross_up(k, d, threshold=20):
    if np.isnan(k[-2]) or np.isnan(d[-2]):
        return False
    return k[-2] < d[-2] and k[-1] > d[-1] and k[-1] < threshold


def generate_chart(symbol, data):
    df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
    df["Time"] = pd.to_datetime(df["Time"], unit='ms')
    df.set_index("Time", inplace=True)

    fig, axlist = mpf.plot(df, type='candle', style='charles', volume=True,
                           title=symbol, returnfig=True)
    chart_file = f"{symbol.replace('/', '_')}.png"
    fig.savefig(chart_file)
    plt.close(fig)
    return chart_file


# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning...")
    try:
        all_symbols = [m['symbol'] for m in EXCHANGE.load_markets().values()
                       if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]
        symbols = []
        for s in all_symbols:
            try:
                ticker = EXCHANGE.fetch_ticker(s)
                if ticker['quoteVolume'] > MIN_VOLUME_24H:
                    symbols.append(s)
            except:
                continue

        for symbol in symbols:
            data = get_ohlcv(symbol, TIMEFRAME)
            if data is None or len(data) < 50:
                continue
            closes = data[:, 4]
            k, d = compute_stoch_rsi(closes)

            if is_cross_up(k, d):
                price = closes[-1]
                time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                signal_key = f"{symbol}-{time_str}-{price:.2f}"
                if signal_key in sent_signals:
                    continue
                sent_signals.add(signal_key)

                msg = (
                    f"⚡ STOCH RSI CROSSING ({symbol})\n"
                    f"Cross at oversold area (K={k[-1]:.2f}, D={d[-1]:.2f})\n"
                    f"Price: {price:.4f}\nTime: {time_str}"
                )
                chart = generate_chart(symbol, data)
                send_telegram(msg, chart)
                print(f"[{datetime.now()}] SIGNAL! {symbol}")

        print(f"[{datetime.now()}] Selesai, tunggu {CHECK_INTERVAL/60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"[ERROR] {e}")
        send_telegram(f"⚠️ ERROR: {e}")
        time.sleep(60)
