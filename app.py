import time
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask
import yfinance as yf
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "¡El Bot de Trading EUR/USD está activo, operando y conectado a Supabase!"

def enviar_alerta_telegram(mensaje):
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        print("Telegram no configurado: faltan variables de entorno.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': mensaje,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

def verificar_y_guardar_senal(activo, direccion, rsi):
    supabase_url = os.environ.get('SUPABASE_URL')
    supabase_key = os.environ.get('SUPABASE_KEY')
    
    if not supabase_url or not supabase_key:
        print("Supabase no configurado, enviando alerta sin validar historial.")
        return True
    
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    rest_url = f"{supabase_url}/rest/v1/historial_senales"
    
    try:
        # Ventana de tiempo de 1 hora para evitar duplicados seguidos
        ahora_utc = datetime.now(timezone.utc)
        hace_una_hora = (ahora_utc - timedelta(hours=1)).isoformat()
        
        params = {
            "activo": f"eq.{activo}",
            "direccion": f"eq.{direccion}",
            "fecha_hora": f"gte.{hace_una_hora}"
        }
        response = requests.get(rest_url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 200:
            registros = response.json()
            if registros and len(registros) > 0:
                print("Señal duplicada detectada en Supabase. Omitiendo alerta.")
                return False
                
        # Guardar la nueva señal en la base de datos
        payload = {
            "activo": activo,
            "direccion": direccion,
            "rsi": float(rsi)
        }
        requests.post(rest_url, headers=headers, json=payload, timeout=10)
        return True
        
    except Exception as e:
        print(f"Error interactuando con Supabase REST: {e}")
        return True

def calcular_ema(precios, periodos=50):
    k = 2 / (periodos + 1)
    ema = precios[0]
    for precio in precios[1:]:
        ema = (precio * k) + (ema * (1 - k))
    return ema

def calcular_rsi(precios, periodos=14):
    if len(precios) < periodos + 1:
        return 50.0
    
    ganancias = []
    perdidas = []
    
    for i in range(1, len(precios)):
        cambio = precios[i] - precios[i-1]
        if cambio > 0:
            ganancias.append(cambio)
            perdidas.append(0)
        else:
            ganancias.append(0)
            perdidas.append(abs(cambio))
            
    ganancia_promedio = sum(ganancias[-periodos:]) / periodos
    perdida_promedio = sum(perdidas[-periodos:]) / periodos
    
    if perdida_promedio == 0:
        return 100.0
    
    rs = ganancia_promedio / perdida_promedio
    rsi = 100 - (100 / (1 + rs))
    return rsi

def tarea_analisis():
    # Pequeña pausa inicial para dar tiempo a que levante el servidor web
    time.sleep(15)
    
    while True:
        try:
            print("Iniciando ciclo de análisis técnico (EUR/USD - Temporalidad 1h)...")
            
            df = yf.download(tickers="EUR=X", interval="1h", period="5d", progress=False)
            
            if not df.empty and 'Close' in df.columns:
                precios_cierre = df['Close'].dropna().tolist()
                
                if len(precios_cierre) > 60:
                    ultimo_cierre = float(precios_cierre[-1])
                    ema_50 = calcular_ema(precios_cierre, 50)
                    rsi_14 = calcular_rsi(precios_cierre, 14)
                    
                    print(f"Precio Actual: {ultimo_cierre:.5f} | EMA50: {ema_50:.5f} | RSI(14): {rsi_14:.2f}")
                    
                    # Condición de COMPRA: Precio por encima de EMA50 y RSI sobrevendido (< 30)
                    if ultimo_cierre > ema_50 and rsi_14 < 30:
                        if verificar_y_guardar_senal("EUR/USD", "COMPRA", rsi_14):
                            mensaje = (
                                "🚨 *NUEVA SEÑAL DETECTADA* 🚨\n\n"
                                "💱 *Activo:* EUR/USD (Velas de 1H)\n"
                                "📈 *Dirección:* COMPRA (CALL)\n"
                                f"📊 *RSI:* {rsi_14:.2f}\n"
                                "⏱️ *Expiración sugerida:* 1 Hora\n"
                                "💾 *Estado:* Guardado en Supabase"
                            )
                            enviar_alerta_telegram(mensaje)
                        
                    # Condición de VENTA: Precio por debajo de EMA50 y RSI sobrecomprado (> 70)
                    elif ultimo_cierre < ema_50 and rsi_14 > 70:
                        if verificar_y_guardar_senal("EUR/USD", "VENTA", rsi_14):
                            mensaje = (
                                "🚨 *NUEVA SEÑAL DETECTADA* 🚨\n\n"
                                "💱 *Activo:* EUR/USD (Velas de 1H)\n"
                                "📉 *Dirección:* VENTA (PUT)\n"
                                f"📊 *RSI:* {rsi_14:.2f}\n"
                                "⏱️ *Expiración sugerida:* 1 Hora\n"
                                "💾 *Estado:* Guardado en Supabase"
                            )
                            enviar_alerta_telegram(mensaje)
            
        except Exception as e:
            print(f"Error en el ciclo de análisis: {e}")
            
        # Esperar 1 hora exacta antes del siguiente escaneo del mercado
        time.sleep(3600)

if __name__ == '__main__':
    # Lanzar el bucle de análisis en segundo plano
    hilo = threading.Thread(target=tarea_analisis)
    hilo.daemon = True
    hilo.start()
    
    # Arrancar el servidor web para Render y UptimeRobot
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
