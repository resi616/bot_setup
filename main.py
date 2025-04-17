import ccxt
import time
import requests
import numpy as np
import pandas as pd
import pandas_ta as ta
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta
import os
import logging
import tempfile
import signal
from prometheus_client import start_http_server, Counter, Gauge, Histogram

# Configuration
TELEGRAM_TOKEN = '7881384249:AAFLRCsETKh6Mr4Dh0s3KdSjrDdNdwNn2G4'
CHAT_ID = '-1002520925418'
EXCHANGE = ccxt.binance({'enableRateLimit': True})
TIMEFRAME = '15m'
CHECK_INTERVAL = 60 * 15  # 15 minutes
MIN_VOLUME_24H = 100000
EMA_PERIOD = 50
SYMBOL_LIMIT = 50
SENT_SIGNALS_MAX_AGE = 24 * 60 * 60  # Clear signals older than 24 hours
sent_signals = {}  # Changed to dict to store timestamp

# Logging
logging.basicConfig(filename='trading_bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Prometheus metrics
signals_total = Counter('trading_signals_total', 'Total trading signals generated', ['symbol'])
errors_total = Counter('trading_errors_total', 'Total errors encountered', ['type'])
scan_duration = Histogram('trading_scan_duration_seconds', 'Time taken for each scan')
symbols_processed = Gauge('trading_symbols_processed', 'Number of symbols processed per scan')

def send_telegram(msg, chart_path=None):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        if chart_path:
            with open(chart_path, 'rb') as img:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto", files={"photo": img}, data={"chat_id": CHAT_ID}, timeout=10)
            os.remove(chart_path)
        logging.info(f"Telegram message sent: {msg}")
    except Exception as e:
        errors_total.labels(type='telegram').inc()
        logging.error(f"Failed to send Telegram message: {e}")

def refresh_exchange():
    global EXCHANGE
    try:
        EXCHANGE = ccxt.binance({'enableRateLimit': True})
        logging.info("Binance connection refreshed")
    except Exception as e:
        errors_total.labels(type='exchange_refresh').inc()
        logging.error(f"Failed to refresh Binance connection: {e}")

def get_ohlcv(symbol, timeframe='15m', limit=100):
    for attempt in range(3):
        try:
            return np.array(EXCHANGE.fetch_ohlcv(symbol, timeframe, limit=limit))
        except ccxt.RateLimitExceeded:
            errors_total.labels(type='ratelimit').inc()
            logging.warning(f"Rate limit exceeded for {symbol}, retrying in 60s...")
            time.sleep(60)
        except Exception as e:
            errors_total.labels(type='ohlcv').inc()
            logging.error(f"Error fetching OHLCV for {symbol}: {e}")
            time.sleep(1)
    return None

def compute_stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3):
    try:
        df = pd.Series(closes).to_frame(name='close')
        stoch = ta.stochrsi(df['close'], length=rsi_period, rsi_length=rsi_period, k=smooth_k, d=smooth_d)
        return (
            stoch[f'STOCHRSIk_{rsi_period}_{rsi_period}_{smooth_k}'].values,
            stoch[f'STOCHRSId_{rsi_period}_{rsi_period}_{smooth_d}'].values
        )
    except Exception as e:
        errors_total.labels(type='stochrsi').inc()
        logging.error(f"Error computing Stochastic RSI: {e}")
        return None, None

def compute_ema(closes, period=50):
    try:
        return pd.Series(closes).ewm(span=period, adjust=False).mean().values
    except Exception as e:
        errors_total.labels(type='ema').inc()
        logging.error(f"Error computing EMA: {e}")
        return None

def is_cross_up(k, d, price, ema, threshold=20):
    if any(np.isnan([k[-2], k[-1], d[-2], d[-1]])) or ema is None:
        return False
    return k[-2] < d[-2] and k[-1] > d[-1] and k[-1] < threshold and price > ema[-1]

def generate_chart(symbol, data):
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            chart_file = tmp.name
        df = pd.DataFrame(data, columns=["Time", "Open", "High", "Low", "Close", "Volume"])
        df["Time"] = pd.to_datetime(df["Time"], unit='ms')
        df.set_index("Time", inplace=True)
        fig, axlist = mpf.plot(df, type='candle', style='charles', volume=True, title=f"{symbol} ({TIMEFRAME})", returnfig=True)
        fig.savefig(chart_file)
        plt.close(fig)
        logging.info(f"Chart generated for {symbol}: {chart_file}")
        return chart_file
    except Exception as e:
        errors_total.labels(type='chart').inc()
        logging.error(f"Error generating chart for {symbol}: {e}")
        return None

def get_symbols():
    try:
        all_symbols = [m['symbol'] for m in EXCHANGE.load_markets().values() if m['quote'] == 'USDT' and m['spot'] and '/' in m['symbol']]
        symbols = []
        for s in all_symbols:
            try:
                ticker = EXCHANGE.fetch_ticker(s)
                if ticker['quoteVolume'] > MIN_VOLUME_24H:
                    symbols.append(s)
                time.sleep(0.1)
            except Exception as e:
                errors_total.labels(type='ticker').inc()
                logging.warning(f"Error fetching ticker for {s}: {e}")
        symbols = sorted(symbols, key=lambda x: EXCHANGE.fetch_ticker(x)['quoteVolume'], reverse=True)
        return symbols[:SYMBOL_LIMIT]
    except Exception as e:
        errors_total.labels(type='symbols').inc()
        logging.error(f"Error fetching symbols: {e}")
        return []

def clean_sent_signals():
    current_time = time.time()
    expired = [key for key, timestamp in sent_signals.items() if current_time - timestamp > SENT_SIGNALS_MAX_AGE]
    for key in expired:
        del sent_signals[key]
    logging.info(f"Cleaned {len(expired)} expired signals")

def scan():
    with scan_duration.time():
        logging.info(f"Starting scan at {datetime.now()}")
        try:
            clean_sent_signals()
            refresh_exchange()
            symbols = get_symbols()
            if not symbols:
                logging.warning("No symbols found, retrying in next scan")
                return

            symbols_processed.set(len(symbols))
            for symbol in symbols:
                try:
                    data = get_ohlcv(symbol, TIMEFRAME, limit=100)
                    if data is None or len(data) < 50:
                        logging.warning(f"Insufficient data for {symbol}")
                        continue

                    closes = data[:, 4]
                    k, d = compute_stoch_rsi(closes)
                    ema = compute_ema(closes, EMA_PERIOD)
                    if k is None or d is None or ema is None:
                        continue

                    if is_cross_up(k, d, closes[-1], ema):
                        price = closes[-1]
                        time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                        signal_key = f"{symbol}-{time_str}-{price:.2f}"
                        if signal_key in sent_signals:
                            continue
                        sent_signals[signal_key] = time.time()

                        signals_total.labels(symbol=symbol).inc()
                        msg = (
                            f"⚡ STOCH RSI CROSSING ({symbol})\n"
                            f"Cross at oversold (K={k[-1]:.2f}, D={d[-1]:.2f})\n"
                            f"Price: {price:.4f} (Above EMA{EMA_PERIOD})\n"
                            f"Time: {time_str}"
                        )
                        chart = generate_chart(symbol, data)
                        send_telegram(msg, chart)
                        logging.info(f"SIGNAL! {symbol} at {price:.4f}")

                except Exception as e:
                    errors_total.labels(type='symbol_processing').inc()
                    logging.error(f"Error processing {symbol}: {e}")
                    continue

            logging.info(f"Scan completed, waiting {CHECK_INTERVAL/60} minutes...")
        except Exception as e:
            errors_total.labels(type='scan').inc()
            logging.error(f"Critical error in scan: {e}")
            send_telegram(f"⚠️ CRITICAL ERROR: {e}")

def run_loop():
    next_run = datetime.now().replace(second=0, microsecond=0)
    while True:
        current_time = datetime.now()
        if current_time >= next_run:
            scan()
            next_run = (current_time + timedelta(seconds=CHECK_INTERVAL)).replace(second=0, microsecond=0)
        time.sleep(1)

def signal_handler(sig, frame):
    logging.info("Shutting down bot gracefully")
    send_telegram("⚠️ Bot stopped")
    exit(0)

if __name__ == "__main__":
    start_http_server(8000)
    logging.info("Starting trading bot...")
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    run_loop()