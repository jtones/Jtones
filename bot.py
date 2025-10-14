#!/usr/bin/env python3
import requests, pandas as pd, numpy as np, csv, os, threading
from telegram import Bot
from datetime import datetime, time
import time as t

BOT_TOKEN = "8453863878:AAF4OBU_lhkhZtwn30S0BFXrXmP_vypSgOY"
CHAT_ID = "6806374006"
PAIRS = ["EURUSD", "GBPUSD", "EURJPY", "AUDCAD"]
INTERVAL = 180
CANDLE_HISTORY = 50

SUPPORT_RESISTANCE = {
    "EURUSD": [1.0900, 1.0950],
    "GBPUSD": [1.2500, 1.2550],
    "EURJPY": [129.50, 130.00],
    "AUDCAD": [0.9100, 0.9150]
}

bot = Bot(token=BOT_TOKEN)

def send_signal(message):
    try:
        bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"Telegram error: {e}")

LOG_FILE = "signals_log.csv"
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, mode='w', newline='') as f:
        csv.writer(f).writerow(["Timestamp", "Pair", "Signal", "Strategy", "Price", "Expiry", "ExecuteAt"])

def log_signal(timestamp, pair, signal, strategy, price, expiry, execute):
    with open(LOG_FILE, mode='a', newline='') as f:
        csv.writer(f).writerow([timestamp, pair, signal, strategy, price, expiry, execute])

def is_trading_session():
    now = (datetime.utcnow() + pd.Timedelta(hours=1)).time()
    sessions = [(time(9,0), time(12,0)), (time(14,0), time(17,0))]
    return any(start <= now <= end for start, end in sessions)

def get_live_rate(pair):
    base, quote = pair[:3], pair[3:]
    try:
        r = requests.get(f"https://api.exchangerate.host/latest?base={base}&symbols={quote}").json()
        return r['rates'][quote]
    except:
        return None

def calculate_ema(prices, period): return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]
def calculate_rsi(prices, period=14):
    delta = np.diff(prices)
    gain, loss = np.where(delta > 0, delta, 0), np.where(delta < 0, -delta, 0)
    avg_gain, avg_loss = pd.Series(gain).rolling(period).mean().iloc[-1], pd.Series(loss).rolling(period).mean().iloc[-1]
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_bollinger(prices, period=20):
    s = pd.Series(prices); sma, std = s.rolling(period).mean().iloc[-1], s.rolling(period).std().iloc[-1]
    return sma+2*std, sma-2*std, s.iloc[-1]

def calculate_stochastic(prices, k_period=14, d_period=3):
    s = pd.Series(prices)
    k = 100*((s - s.rolling(k_period).min())/(s.rolling(k_period).max() - s.rolling(k_period).min()))
    d = k.rolling(d_period).mean()
    return k.iloc[-1], d.iloc[-1]

def process_pair(pair):
    price_history = []
    while True:
        try:
            if is_trading_session():
                rate = get_live_rate(pair)
                if rate:
                    price_history.append(rate)
                    if len(price_history) > CANDLE_HISTORY: price_history.pop(0)
                    if len(price_history) >= 20:
                        p = price_history
                        ema9, ema21, ema50 = calculate_ema(p,9), calculate_ema(p,21), calculate_ema(p,50)
                        rsi = calculate_rsi(p,14)
                        upper, lower, last = calculate_bollinger(p,20)
                        k, d = calculate_stochastic(p,14,3)
                        ema50_slope = ema50 - pd.Series(p[-5:]).mean()
                        signal, strategy = "WAIT", ""
                        if abs(ema50_slope) > 0.0001:
                            strategy = "Triple Confirmation"
                            prev_ema9 = pd.Series(p[-6:-1]).ewm(span=9, adjust=False).mean().iloc[-1]
                            prev_ema21 = pd.Series(p[-6:-1]).ewm(span=21, adjust=False).mean().iloc[-1]
                            if prev_ema9 < prev_ema21 and ema9 > ema21 and rsi > 55: signal = "CALL"
                            elif prev_ema9 > prev_ema21 and ema9 < ema21 and rsi < 45: signal = "PUT"
                        else:
                            strategy = "Range Bounce"
                            buffer = 0.0003
                            sr = SUPPORT_RESISTANCE.get(pair, [])
                            near_sr = any(abs(last - lvl) < buffer for lvl in sr)
                            if not near_sr:
                                if last <= lower and k > d and k < 20: signal = "CALL"
                                elif last >= upper and k < d and k > 80: signal = "PUT"
                        if signal != "WAIT":
                            timestamp = (datetime.utcnow() + pd.Timedelta(hours=1)).strftime("%H:%M:%S")
                            msg = f"PAIR: {pair}\nSignal: {signal}\nStrategy: {strategy}\nPrice: {rate:.5f}\nExpiry: 6 min\nTime: {timestamp}"
                            print(msg); send_signal(msg)
                            log_signal(timestamp, pair, signal, strategy, rate, "6 min", "Next candle open")
            else:
                print(f"{pair}: Outside trading session...")
            t.sleep(INTERVAL)
        except Exception as e:
            print(f"{pair}: Error {e}. Restarting in 5s...")
            t.sleep(5)

threads = [threading.Thread(target=process_pair, args=(pair,)) for pair in PAIRS]
[t.start() for t in threads]
[t.join() for t in threads]
