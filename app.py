import time
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask
import yfinance as yf
import requests
from supabase import create_client, Client

app = Flask(__name__)

# Configuración de Supabase usando variables de entorno
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Conexión a Supabase inicializada correctamente.")
    except Exception as e:
        print(f"Error al conectar con Supabase: {e}")

@app.route('/')
def home():
    return "¡El Bot de Señales con Supabase está activo y funcionando en la nube!"

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
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

def verificar_y_guardar_senal(activo, direccion, rsi):
    if not supabase:
        print("Supabase no está disponible, enviando alerta sin validar historial.")
        return True
    
    try:
        # Obtenemos la hora actual en UTC
        ahora_utc = datetime.now(timezone.utc)
        # Definimos una ventana de tiempo (ej. la última hora) para evitar duplicados en el mismo ciclo
        hace_una_hora = (ahora_utc - timedelta(hours=1)).isoformat()
        
        # Consultamos si ya existe una señal similar reciente en la base de datos
        response = supabase.table('historial_senales') \
            .select('*') \
            .eq('activo', activo) \
            .eq('direccion', direccion) \
            .gte('fecha_hora', hace_una_hora) \
            .execute()
        
        # Si la respuesta trae datos, significa que ya avisamos hace poco
        if response.data and len(response.data) > 0:
            print("Señal duplicada detectada en Supabase. Omitiendo alerta.")
            return False
        
        # Si no existe, guardamos la nueva señal en Supabase
        supabase.table('historial_senales').insert({
            'activo': activo,
            'direccion': direccion,
            'rsi': float(rsi)
        }).execute()
        
        return True
    except Exception as e:
        print(f"Error interactuando con Supabase: {e}")
        return True # Ante una falla de BD, priorizamos el envío de la señal

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
    time.sleep(15)
    
    while True:
        try:
            print("Analizando el mercado (EUR/USD - Temporalidad 1h) con registro en Supabase...")
            
            df = yf.download(tickers="EUR=X", interval="1h", period="5d", progress=False)
            
            if not df.empty and 'Close' in df.columns:
                precios_cierre = df['Close'].dropna().tolist()
                
                if len(precios_cierre) > 60:
                    ultimo_cierre = float(precios_cierre[-1])
                    ema_50 = calcular_ema(precios_cierre, 50)
                    rsi_14 = calcular_rsi(precios_cierre, 14)
                    
                    print(f"Precio: {ultimo_cierre:.5f} | EMA50: {ema_50:.5f} | RSI: {rsi_14:.2f}")
                    
                    # Lógica de señales con validación en Supabase
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
            
        time.sleep(3600)

if __name__ == '__main__':
    hilo = threading.Thread(target=tarea_analisis)
    hilo.daemon = True
    hilo.start()
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
