import os
import time
from datetime import datetime
import threading
import requests
from flask import Flask, render_template_string

app = Flask(__name__)

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Variable global para el control del bot
bot_running = True
bot_thread_started = False

# --- AUTODETECCIÓN INTELIGENTE DE CHAT ID ---
def get_telegram_chat_id():
    env_id = os.environ.get("TELEGRAM_CHAT_ID")
    if env_id:
        return env_id
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get("ok") and data.get("result"):
            for update in data["result"]:
                chat = update.get("message", {}).get("chat", {}) or update.get("edited_message", {}).get("chat", {})
                if chat:
                    detected_id = str(chat.get("id"))
                    return detected_id
    except Exception as e:
        print(f"Error auto-detectando el chat ID: {e}")
    
    return None

# --- CESTA DE ACTIVOS ---
ASSETS_LIST = [
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", 
    "USDCAD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X", 
    "BTC-USD", "ETH-USD", "GC=X", "CL=X"
]

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_yahoo_data(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&range=5d", headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        data = response.json()
        result = data['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        return [c for c in closes if c is not None]
    except Exception as e:
        print(f"Error descargando {symbol}: {e}")
        return None

def calculate_ema(prices, period=50):
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = 0, 0
    for i in range(-period, 0):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# --- MOTOR PRINCIPAL ---
def trading_bot_loop():
    print("¡Hilo del bot de trading arrancó con éxito!")
    
    chat_id = get_telegram_chat_id()
    if chat_id:
        try:
            msg = "🤖 **AnalisisBot 30m-1h Iniciado**\nEscaneando mercados globales en tiempo real..."
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Error enviando mensaje de inicio: {e}")
    else:
        print("Aviso: Envía un mensaje o /start en el grupo de Telegram para que el bot detecte el chat.")

    while True:
        global bot_running
        if not bot_running:
            time.sleep(10)
            continue

        try:
            current_chat_id = get_telegram_chat_id()

            for asset in ASSETS_LIST:
                if not bot_running:
                    break
                
                prices = get_yahoo_data(asset)
                if not prices or len(prices) < 50:
                    time.sleep(2)
                    continue

                current_price = prices[-1]
                ema50 = calculate_ema(prices, 50)
                rsi14 = calculate_rsi(prices, 14)

                signal = None
                if current_price > ema50 and rsi14 < 30:
                    signal = "CALL (COMPRA)"
                elif current_price < ema50 and rsi14 > 70:
                    signal = "PUT (VENTA)"

                if signal and current_chat_id:
                    msg = (
                        f"⚡ **SEÑAL DE TRADING** ⚡\n\n"
                        f"📊 Activo: `{asset}`\n"
                        f"🎯 Dirección: **{signal}**\n"
                        f"💲 Precio Ref: `{current_price:.5f}`\n"
                        f"📈 RSI: `{rsi14:.1f}` | EMA50: `{ema50:.5f}`\n"
                        f"⏰ Expiración: 1 Hora"
                    )
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": current_chat_id, "text": msg, "parse_mode": "Markdown"})
                    time.sleep(60)

                time.sleep(5)

        except Exception as e:
            print(f"Error en ciclo general: {e}")

        time.sleep(30)

@app.before_request
def activate_bot():
    global bot_thread_started
    if not bot_thread_started:
        bot_thread_started = True
        threading.Thread(target=trading_bot_loop, daemon=True).start()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>Bot Control</title></head>
<body style="background:#0f172a; color:#fff; text-align:center; font-family:sans-serif; margin-top:50px;">
    <h2>AnalisisBot Panel</h2>
    <p>Estado: <b>{{ 'ACTIVO' if running else 'DETENIDO' }}</b></p>
    <form method="POST" action="/toggle">
        <button type="submit" style="padding:10px 20px; font-size:16px; background:{{ '#ef4444' if running else '#22c55e' }}; color:#fff; border:none; border-radius:5px;">
            {{ 'DETENER' if running else 'INICIAR' }}
        </button>
    </form>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE, running=bot_running)

@app.route("/toggle", methods=["POST"])
def toggle():
    global bot_running
    bot_running = not bot_running
    return index()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
