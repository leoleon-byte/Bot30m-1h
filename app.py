import os
import time
from datetime import datetime, timedelta
import threading
import requests
import json
from flask import Flask, render_template_string

app = Flask(__name__)

# --- CONFIGURACIÓN DE CREDENCIALES ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

HEADERS_SUPABASE = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# Variable global para el control de Start / Stop del bot
bot_running = True

# --- CESTA AMPLIADA DE ACTIVOS (Forex, Criptos y Commodities - Cero OTC) ---
ASSETS_LIST = [
    # Forex - Majors
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", 
    "USDCAD=X", "NZDUSD=X", "USDCHF=X",
    # Forex - Crosses
    "EURGBP=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X", 
    "EURAUD=X", "EURCAD=X", "GBPCAD=X", "AUDNZD=X",
    "CHFJPY=X", "NZDJPY=X", "CADJPY=X",
    # Criptomonedas (24/7 Globales)
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", 
    "ADA-USD", "AVAX-USD", "DOGE-USD", "LINK-USD",
    # Materias Primas / Commodities
    "GC=X",     # Oro
    "SI=X",     # Plata
    "CL=X",     # Petróleo Crudo WTI
    "HG=X",     # Cobre
    "PL=X"      # Platino
]

# --- SESIÓN HTTP SIMULADA PARA YAHOO FINANCE ---
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
        
        # Limpiar valores nulos
        closes = [c for c in closes if c is not None]
        return closes
    except Exception as e:
        print(f"Error descargando {symbol}: {e}")
        return None

# --- CÁLCULOS MATEMÁTICOS (EMA Y RSI) ---
def calculate_ema(prices, period=50):
    if len(prices) < period:
        return prices[-1] if prices else 0
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period  # SMA inicial
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
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- GESTIÓN DE EXIGENCIA EN SUPABASE ---
def get_exigency_level(asset):
    try:
        res = requests.get(f"{SUPABASE_URL}/rest/v1/config_exigencia?asset=eq.{asset}", headers=HEADERS_SUPABASE)
        data = res.json()
        if data:
            return data[0].get("exigency_level", 0)
        else:
            # Si no existe, crearlo en nivel 0
            requests.post(f"{SUPABASE_URL}/rest/v1/config_exigencia", headers=HEADERS_SUPABASE, json={"asset": asset, "exigency_level": 0})
            return 0
    except:
        return 0

def increment_exigency(asset):
    try:
        current = get_exigency_level(asset)
        new_level = current + 1
        requests.patch(f"{SUPABASE_URL}/rest/v1/config_exigencia?asset=eq.{asset}", headers=HEADERS_SUPABASE, json={"exigency_level": new_level})
        print(f"[{asset}] Exigencia aumentada a nivel {new_level} por fallo.")
    except Exception as e:
        print(f"Error actualizando exigencia: {e}")

# --- VERIFICAR RESULTADOS PENDIENTES ---
def check_pending_results():
    try:
        now = datetime.utcnow()
        res = requests.get(f"{SUPABASE_URL}/rest/v1/historial_senales?result=eq.PENDIENTE", headers=HEADERS_SUPABASE)
        signals = res.json()
        
        for sig in signals:
            expiry_time = datetime.fromisoformat(sig["expiry_time"].replace("Z", ""))
            if now >= expiry_time:
                asset = sig["asset"]
                direction = sig["direction"]
                entry_price = sig["entry_price"]
                
                prices = get_yahoo_data(asset)
                if not prices:
                    continue
                current_price = prices[-1]
                
                won = False
                if direction == "CALL" and current_price > entry_price:
                    won = True
                elif direction == "PUT" and current_price < entry_price:
                    won = True
                
                result_str = "GANADA" if won else "PERDIDA"
                
                requests.patch(f"{SUPABASE_URL}/rest/v1/historial_senales?id=eq.{sig['id']}", headers=HEADERS_SUPABASE, json={"result": result_str})
                
                if not won:
                    increment_exigency(asset)
                
                msg = f"📊 **RESULTADO DE OPERACIÓN**\nActivo: {asset}\nDirección: {direction}\nPrecio Entrada: {entry_price}\nPrecio Salida: {current_price}\nResultado: **{result_str}**"
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error evaluando resultados: {e}")

# --- FILTRO ANTI-SPAM POR HORA Y ACTIVO ---
def already_signaled_this_hour(asset):
    try:
        now_hour = datetime.utcnow().strftime("%Y-%m-%d %H:00:00")
        res = requests.get(f"{SUPABASE_URL}/rest/v1/historial_senales?asset=eq.{asset}&entry_time=gte.{now_hour}", headers=HEADERS_SUPABASE)
        data = res.json()
        return len(data) > 0
    except:
        return False

# --- MOTOR PRINCIPAL EN SEGUNDO PLANO ---
def trading_bot_loop():
    print("Hilo del bot de trading ampliado iniciado...")
    while True:
        global bot_running
        if not bot_running:
            time.sleep(10)
            continue

        try:
            check_pending_results()

            for asset in ASSETS_LIST:
                if not bot_running:
                    break
                
                if already_signaled_this_hour(asset):
                    continue

                prices = get_yahoo_data(asset)
                if not prices or len(prices) < 60:
                    time.sleep(3)
                    continue

                current_price = prices[-1]
                ema50 = calculate_ema(prices, 50)
                rsi14 = calculate_rsi(prices, 14)

                exigency = get_exigency_level(asset)
                
                buy_rsi_limit = 30 - (exigency * 2)   
                sell_rsi_limit = 70 + (exigency * 2)  

                signal = None
                if current_price > ema50 and rsi14 < buy_rsi_limit:
                    signal = "CALL"
                elif current_price < ema50 and rsi14 > sell_rsi_limit:
                    signal = "PUT"

                if signal:
                    now = datetime.utcnow()
                    entry_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                    expiry_dt = now + timedelta(hours=1)
                    expiry_time_str = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

                    payload = {
                        "asset": asset,
                        "direction": signal,
                        "entry_price": current_price,
                        "entry_time": now.isoformat(),
                        "expiry_time": expiry_dt.isoformat(),
                        "result": "PENDIENTE",
                        "rsi_at_entry": rsi14
                    }
                    requests.post(f"{SUPABASE_URL}/rest/v1/historial_senales", headers=HEADERS_SUPABASE, json=payload)

                    msg = (
                        f"🚨 **NUEVA SEÑAL DETECTADA** 🚨\n"
                        f"📈 Activo: `{asset}`\n"
                        f"🎯 Dirección: **{signal}**\n"
                        f"💲 Precio Actual: `{current_price:.5f}`\n"
                        f"📊 RSI({rsi14:.1f}) | EMA50({ema50:.5f})\n"
                        f"⚠️ Exigencia Actual: Nivel {exigency}\n"
                        f"⏰ Expiración: Vela de 1 Hora"
                    )
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

                # Pausa escalonada corta para recorrer eficientemente la lista grande
                time.sleep(10)

        except Exception as e:
            print(f"Error en ciclo general del bot: {e}")

        time.sleep(30)

# Lanzar hilo en segundo plano
threading.Thread(target=trading_bot_loop, daemon=True).start()

# --- INTERFAZ WEB CON BOTONES START / STOP ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Bot de Trading - Control</title>
    <style>
        body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; background: #0f172a; color: #f8fafc; }
        .card { background: #1e293b; padding: 30px; border-radius: 12px; display: inline-block; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
        .status { font-size: 24px; font-weight: bold; margin-bottom: 20px; }
        .running { color: #22c55e; }
        .stopped { color: #ef4444; }
        .btn { padding: 12px 24px; font-size: 16px; font-weight: bold; border: none; border-radius: 6px; cursor: pointer; margin: 10px; }
        .btn-start { background: #22c55e; color: white; }
        .btn-stop { background: #ef4444; color: white; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Panel de Control Multi-Asset Bot</h2>
        <div class="status">Estado: <span class="{{ 'running' if running else 'stopped' }}">{{ 'ACTIVO Y ESCANEANDO' if running else 'DETENIDO' }}</span></div>
        <form method="POST" action="/toggle">
            {% if running %}
                <button type="submit" class="btn btn-stop">DETENER (STOP)</button>
            {% else %}
                <button type="submit" class="btn btn-start">INICIAR (START)</button>
            {% endif %}
        </form>
    </div>
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
    
