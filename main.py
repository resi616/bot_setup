import time
import numpy as np
import pandas as pd
from binance.um_futures import UMFutures
from datetime import datetime
import requests

# Konfigurasi API dan Telegram
API_KEY = "9qs8E7x5eh6iHxOvM02TAegv8hTDBkzBbveapywWM9lgX4EM9xlNjplKDLXhUjcy"
API_SECRET = "wCK3Ul1h5lZRobbeYHLjyjL9znQcvdt5lmGp324nzqgmlOZO7eWhGpNVJfQJ8ttUE"
TELEGRAM_TOKEN = '8152840476:AAHqFTaJn67tLlIwnBWjEZbt5wyvl09FfiI'
TELEGRAM_CHAT_ID = '-1002520925418'

# Inisialisasi klien Binance Futures
binance = UMFutures(key=API_KEY, secret=API_SECRET)
TIMEFRAME = "5m"
CHECK_INTERVAL = 60 * 5  # 5 menit
last_signals = {}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        })
        return response.json().get("ok", False)
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return False

def calculate_ema(prices, period):
    return prices.ewm(span=period, adjust=False).mean()

def get_signal(symbol, closes):
    df = pd.DataFrame({'close': closes})
    df['ema13'] = calculate_ema(df['close'], 13)
    df['ema21'] = calculate_ema(df['close'], 21)

    if df['ema13'].iloc[-2] < df['ema21'].iloc[-2] and df['ema13'].iloc[-1] > df['ema21'].iloc[-1]:
        return "bullish"
    elif df['ema13'].iloc[-2] > df['ema21'].iloc[-2] and df['ema13'].iloc[-1] < df['ema21'].iloc[-1]:
        return "bearish"
    return None

def is_risk_on():
    try:
        bnb_data = binance.klines("BNBUSDT", TIMEFRAME, limit=30)
        volumes = [float(k[5]) for k in bnb_data]
        avg_vol = np.mean(volumes[:-1])
        current_vol = volumes[-1]
        return current_vol > avg_vol * 1.5
    except Exception as e:
        print(f"[Volume Check Error] {e}")
        return False

def main_loop():
    while True:
        print(f"[{datetime.now()}] Scanning futures market...")
        try:
            exchange_info = binance.exchange_info()
            symbols = [
                s['symbol'] for s in exchange_info['symbols']
                if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT'
            ]

            risk_mode = is_risk_on()
            signal_count = 0

            for symbol in symbols:
                try:
                    klines = binance.klines(symbol, TIMEFRAME, limit=30)
                    closes = [float(k[4]) for k in klines]
                    signal = get_signal(symbol, closes)

                    if signal:
                        entry = closes[-1]
                        entry_str = f"{entry:.10f}".rstrip("0")
                        decimal_places = len(entry_str.split(".")[1]) if "." in entry_str else 2

                        if signal == "bullish":
                            tp1 = round(entry * 1.01, decimal_places)
                            tp2 = round(entry * 1.02, decimal_places)
                            sl = round(entry * 0.99, decimal_places)
                        else:
                            tp1 = round(entry * 0.99, decimal_places)
                            tp2 = round(entry * 0.98, decimal_places)
                            sl = round(entry * 1.01, decimal_places)

                        current_signal = (signal, round(entry, decimal_places), tp1, tp2, sl)

                        if last_signals.get(symbol) != current_signal:
                            message = (
                                f"<b>Sinyal {signal.upper()}</b>\n"
                                f"Pair: <code>{symbol}</code>\n"
                                f"Entry: <code>{entry}</code>\n"
                                f"TP1: <code>{tp1}</code>\n"
                                f"TP2: <code>{tp2}</code>\n"
                                f"SL: <code>{sl}</code>\n"
                                f"Risk Mode: {'ON' if risk_mode else 'OFF'}"
                            )
                            if send_telegram(message):
                                print(f"[{datetime.now()}] {symbol} SIGNAL {signal.upper()} dikirim.")
                                last_signals[symbol] = current_signal
                                signal_count += 1
                            else:
                                print(f"[{datetime.now()}] {symbol} SIGNAL {signal.upper()} gagal kirim.")

                    time.sleep(0.5)
                except Exception as e:
                    print(f"[Error {symbol}] {e}")

            if signal_count == 0:
                print(f"[{datetime.now()}] Tidak ada sinyal valid.")

            print(f"[{datetime.now()}] Selesai scan, tidur {CHECK_INTERVAL // 60} menit...\n")
            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"[Main Error] {e}")
            send_telegram(f"❌ Error saat scan: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main_loop()
