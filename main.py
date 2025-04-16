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
TELEGRAM_TOKEN = '7723680969:AAERGAlUjOpKgzCpHihut2SYFALCHZ50h1M'
CHAT_ID = '-1002643789070'
EXCHANGE = ccxt.binance({
    'enableRateLimit': True,
    'defaultType': 'future'  # Futures (USDⓈ-M perpetual)
})
TIMEFRAME = '15m'
SWING_TIMEFRAME = '1h'
CHECK_INTERVAL = 60 * 15  # 15 menit
MIN_RR = 2.0  # Risk-Reward Ratio minimal 1:2
MIN_VOLUME_24H = 100000  # Minimal volume 24h dalam USDT
BTC_DROP_THRESHOLD = -0.02  # Blok long jika BTC turun > 2%

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

def get_ohlcv(symbol, timeframe, limit=100, retries=3):
    for _ in range(retries):
        try:
            data = EXCHANGE.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, params={'contractType': 'PERPETUAL'})
            return np.array(data)
        except:
            time.sleep(1)
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

def compute_adx(data, period=14):
    highs = data[:, 2]
    lows = data[:, 3]
    closes = data[:, 4]
    plus_dm = np.zeros(len(data) - 1)
    minus_dm = np.zeros(len(data) - 1)
    for i in range(1, len(data)):
        up_move = highs[i] - highs[i-1]
        down_move = lows[i-1] - lows[i]
        plus_dm[i-1] = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm[i-1] = down_move if down_move > up_move and down_move > 0 else 0
    atr = compute_atr(data, period)
    plus_di = np.zeros(len(data) - period)
    minus_di = np.zeros(len(data) - period)
    for i in range(period, len(data)):
        plus_di[i-period] = 100 * np.mean(plus_dm[i-period:i]) / atr if atr > 0 else 0
        minus_di[i-period] = 100 * np.mean(minus_dm[i-period:i]) / atr if atr > 0 else 0
    dx = np.zeros(len(plus_di))
    for i in range(len(plus_di)):
        dx[i] = 100 * abs(plus_di[i] - minus_di[i]) / (plus_di[i] + minus_di[i]) if (plus_di[i] + minus_di[i]) > 0 else 0
    adx = np.mean(dx[-period:]) if len(dx) >= period else 0
    return adx, plus_di[-1], minus_di[-1]

def compute_sma(closes, period=20):
    return pd.Series(closes).rolling(window=period).mean().values

def find_swing_high_lows(data):
    highs = data[:, 2]
    lows = data[:, 3]
    swing_high = max(highs[-20:])
    swing_low = min(lows[-20:])
    return swing_high, swing_low

def generate_chart(symbol, data, entry, tp, sl, rsi_last, adx_last):
    try:
        df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
        df["Time"] = pd.to_datetime(df["Time"], unit='ms')
        df.set_index("Time", inplace=True)
        sma = compute_sma(df["Close"].values, period=20)
        rsi = compute_rsi(df["Close"].values, period=14)
        rsi = np.pad(rsi, (len(df) - len(rsi), 0), 'constant', constant_values=np.nan)
        apds = [
            mpf.make_addplot([entry]*len(df), color='green', linestyle='--', width=1),
            mpf.make_addplot([tp]*len(df), color='blue', linestyle='--', width=1),
            mpf.make_addplot([sl]*len(df), color='red', linestyle='--', width=1),
            mpf.make_addplot(sma, color='orange', linestyle='-', width=1, ylabel='SMA 20'),
            mpf.make_addplot(rsi, color='purple', panel=1, ylabel='RSI (14)'),
            mpf.make_addplot([70]*len(df), color='red', linestyle='--', panel=1),
            mpf.make_addplot([30]*len(df), color='green', linestyle='--', panel=1),
        ]
        chart_file = f"{symbol.replace('/', '_')}.png"
        mpf.plot(
            df,
            type='candle',
            volume=True,
            style='yahoo',
            title=f"{symbol} Futures Signal",
            addplot=apds,
            panel_ratios=(1, 0.5),
            savefig=chart_file
        )
        print(f"Chart disimpan sebagai {chart_file}")
        return chart_file
    except Exception as e:
        send_telegram(f"⚠️ Gagal buat chart untuk {symbol}: {e}")
        return None

def detect_trend(data):
    adx, plus_di, minus_di = compute_adx(data)
    if adx > 25 and plus_di > minus_di:
        return "uptrend"
    elif adx > 25 and minus_di > plus_di:
        return "downtrend"
    return "sideways"

def detect_signal(symbol, data):
    closes = data[:, 4]
    highs = data[:, 2]
    lows = data[:, 3]
    opens = data[:, 1]
    volumes = data[:, 5]

    last_close = closes[-1]
    last_open = opens[-1]
    rsi = compute_rsi(closes, period=14)
    trend = detect_trend(data)
    adx, _, _ = compute_adx(data)

    # Filter Korelasi BTC untuk Long
    if "BTC" not in symbol:  # Lewati untuk BTC/USDT:USDT
        btc_data = get_ohlcv("BTC/USDT:USDT", TIMEFRAME, limit=10)
        if btc_data is not None:
            btc_change = (btc_data[-1, 4] - btc_data[0, 4]) / btc_data[0, 4]
            if btc_change < BTC_DROP_THRESHOLD and trend in ["uptrend", "sideways"]:
                print(f"[DEBUG] {symbol} - Long diblok karena BTC turun {btc_change:.2%}")
                if trend == "downtrend":
                    pass  # Lanjut ke short
                else:
                    return None

    swing_data = get_ohlcv(symbol, SWING_TIMEFRAME)
    if swing_data is None:
        return None
    swing_high, swing_low = find_swing_high_lows(swing_data)
    atr = compute_atr(data, period=14)
    if atr == 0:
        return None

    print(f"\n[DEBUG] {symbol} - Trend: {trend}, RSI: {rsi[-1]:.2f}, ADX: {adx:.2f}, ATR: {atr:.4f}")

    # LONG: Uptrend
    if trend == "uptrend":
        breakout = last_close > max(highs[-5:-1])
        volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
        rsi_condition = 60 <= rsi[-1] <= 75

        print(f"[DEBUG] Uptrend Long - Breakout: {breakout}, Volume Spike: {volume_spike}, RSI Condition: {rsi_condition}")

        if breakout and volume_spike and rsi_condition:
            sl = min(swing_low, last_close - 1.5 * atr)
            risk = last_close - sl
            tp = last_close + (risk * MIN_RR)
            tp = min(tp, swing_high * 1.05)

            if risk <= 0 or (tp - last_close) / risk < MIN_RR:
                return None

            signal_key = f"{symbol}-long-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
            if signal_key in sent_signals:
                return None
            sent_signals.add(signal_key)

            msg = (
                f"🟢 TREND STRATEGY (LONG): {symbol}\n"
                f"Entry: {last_close:.4f}\nTP: {tp:.4f}\nSL: {sl:.4f}\nRR: {(tp - last_close) / (last_close - sl):.2f}:1"
            )
            chart_path = generate_chart(symbol, data, last_close, tp, sl, rsi[-1], adx)
            return msg, chart_path

    # LONG: Sideways
    elif trend == "sideways":
        resistance = max(highs[-20:])
        breakout = last_close > resistance * 1.01
        volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
        rsi_condition = 60 <= rsi[-1] <= 70
        candle_body = abs(last_close - last_open)
        body_condition = candle_body > 0.5 * atr

        print(f"[DEBUG] Sideways Long - Breakout: {breakout}, Volume Spike: {volume_spike}, RSI Condition: {rsi_condition}, Body Condition: {body_condition}")

        if breakout and volume_spike and rsi_condition and body_condition:
            sl = min(swing_low, last_close - 1.5 * atr)
            risk = last_close - sl
            tp = last_close + risk * MIN_RR

            if risk <= 0 or (tp - last_close) / risk < MIN_RR:
                return None

            signal_key = f"{symbol}-long-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
            if signal_key in sent_signals:
                return None
            sent_signals.add(signal_key)

            msg = (
                f"🟡 SIDEWAYS STRATEGY (LONG): {symbol}\n"
                f"Entry: {last_close:.4f}\nTP: {tp:.4f}\nSL: {sl:.4f}\nRR: {(tp - last_close) / (last_close - sl):.2f}:1"
            )
            chart_path = generate_chart(symbol, data, last_close, tp, sl, rsi[-1], adx)
            return msg, chart_path

    # SHORT: Downtrend
    elif trend == "downtrend":
        breakout = last_close < min(lows[-5:-1])
        volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
        rsi_condition = 25 <= rsi[-1] <= 40

        print(f"[DEBUG] Downtrend Short - Breakout: {breakout}, Volume Spike: {volume_spike}, RSI Condition: {rsi_condition}")

        if breakout and volume_spike and rsi_condition:
            sl = max(swing_high, last_close + 1.5 * atr)
            risk = sl - last_close
            tp = last_close - (risk * MIN_RR)
            tp = max(tp, swing_low * 0.95)

            if risk <= 0 or (last_close - tp) / risk < MIN_RR:
                return None

            signal_key = f"{symbol}-short-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
            if signal_key in sent_signals:
                return None
            sent_signals.add(signal_key)

            msg = (
                f"🔴 TREND STRATEGY (SHORT): {symbol}\n"
                f"Entry: {last_close:.4f}\nTP: {tp:.4f}\nSL: {sl:.4f}\nRR: {(last_close - tp) / (sl - last_close):.2f}:1"
            )
            chart_path = generate_chart(symbol, data, last_close, tp, sl, rsi[-1], adx)
            return msg, chart_path

    # SHORT: Sideways
    elif trend == "sideways":
        support = min(lows[-20:])
        breakout = last_close < support * 0.99
        volume_spike = volumes[-1] > 1.5 * np.mean(volumes[-10:-1])
        rsi_condition = 30 <= rsi[-1] <= 40
        candle_body = abs(last_open - last_close)
        body_condition = candle_body > 0.5 * atr

        print(f"[DEBUG] Sideways Short - Breakout: {breakout}, Volume Spike: {volume_spike}, RSI Condition: {rsi_condition}, Body Condition: {body_condition}")

        if breakout and volume_spike and rsi_condition and body_condition:
            sl = max(swing_high, last_close + 1.5 * atr)
            risk = sl - last_close
            tp = last_close - (risk * MIN_RR)

            if risk <= 0 or (last_close - tp) / risk < MIN_RR:
                return None

            signal_key = f"{symbol}-short-{last_close:.4f}-{tp:.4f}-{sl:.4f}"
            if signal_key in sent_signals:
                return None
            sent_signals.add(signal_key)

            msg = (
                f"🟡 SIDEWAYS STRATEGY (SHORT): {symbol}\n"
                f"Entry: {last_close:.4f}\nTP: {tp:.4f}\nSL: {sl:.4f}\nRR: {(last_close - tp) / (sl - last_close):.2f}:1"
            )
            chart_path = generate_chart(symbol, data, last_close, tp, sl, rsi[-1], adx)
            return msg, chart_path

    return None

# === MAIN LOOP ===
# === MAIN LOOP ===
while True:
    print(f"[{datetime.now()}] Scanning futures market...")
    try:
        markets = EXCHANGE.load_markets()
        symbols = [m['symbol'] for m in markets.values()
                   if m.get('quote') == 'USDT' and m.get('swap') and m.get('contract') and '/' in m['symbol']]
        
        liquid_symbols = []
        for symbol in symbols:
            try:
                data = get_ohlcv(symbol, TIMEFRAME, limit=100)  # Ambil minimal 100 data candle
                if data is None or data.shape[0] < 50 or data.shape[1] != 6:
                    print(f"[{symbol}] ❌ Data tidak valid (None/kosong/bentuk tidak sesuai)")
                    continue

                avg_volume = np.mean(data[:, 5] * data[:, 4])  # volume x close
                if avg_volume * 96 > MIN_VOLUME_24H:
                    liquid_symbols.append(symbol)
            except Exception as e:
                print(f"[{symbol}] Error saat cek volume: {e}")
                continue

        print(f"✅ Total simbol liquid: {len(liquid_symbols)}\n")

        for symbol in liquid_symbols:
            try:
                data = get_ohlcv(symbol, TIMEFRAME, limit=150)
                if data is None or data.shape[0] < 50 or data.shape[1] != 6:
                    print(f"[{symbol}] ❌ Data tidak valid saat deteksi sinyal")
                    continue

                result = detect_signal(symbol, data)
                if result:
                    msg, chart = result
                    print(f"[{datetime.now()}] 🚨 {symbol} SIGNAL!")
                    send_telegram(msg, chart)
            except Exception as e:
                print(f"[{symbol}] Error saat deteksi sinyal: {e}")
                continue

        print(f"[{datetime.now()}] ✅ Selesai scanning, tunggu {CHECK_INTERVAL / 60} menit...\n")
        time.sleep(CHECK_INTERVAL)

    except Exception as e:
        print(f"🔥 ERROR UTAMA: {e}")
        send_telegram(f"\u274c Error saat scan: {e}")
        time.sleep(60)
