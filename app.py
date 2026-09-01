import time
import os
import threading
from flask import Flask
import pandas as pd
import numpy as np
import yfinance as requests_yfinance # O usa yfinance directamente
import yfinance as yf
import requests

app = Flask(__name__)

@app.route('/')
def home():
    return "¡El Bot de Señales está activo y funcionando en la nube!"

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

def calcular_indicadores(df):
    # Media Móvil Exponencial (EMA) de 50 periodos
    df['ema_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    
    # Cálculo del RSI de 14 periodos
    delta = df['Close'].diff()
    ganancia = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    perdida = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    
    rs = ganancia / perdida
    df['rsi_14'] = 100 - (100 / (1 + rs))
    return df

def tarea_analisis():
    # Espera inicial para asegurar que el servidor web arranqué bien
    time.sleep(10)
    
    while True:
        try:
            print("Analizando el mercado (EUR/USD - Temporalidad 1h)...")
            
            # Descargamos datos reales de la última semana en velas de 1 hora
            # EUR=X es el ticker de EUR/USD en Yahoo Finance
            df = yf.download(tickers="EUR=X", interval="1h", period="5d", progress=False)
            
            if not df.empty:
                df = calcular_indicadores(df)
                
                # Tomamos la última vela cerrada
                ultimo_cierre = float(df['Close'].iloc[-1].item() if hasattr(df['Close'].iloc[-1], 'item') else df['Close'].iloc[-1])
                ultima_ema = float(df['ema_50'].iloc[-1].item() if hasattr(df['ema_50'].iloc[-1], 'item') else df['ema_50'].iloc[-1])
                ultimo_rsi = float(df['rsi_14'].iloc[-1].item() if hasattr(df['rsi_14'].iloc[-1], 'item') else df['rsi_14'].iloc[-1])
                
                print(f"Precio: {ultimo_cierre:.5f} | EMA50: {ultima_ema:.5f} | RSI: {ultimo_rsi:.2f}")
                
                # Lógica de señales
                if ultimo_cierre > ultima_ema and ultimo_rsi < 30:
                    mensaje = (
                        "🚨 *NUEVA SEÑAL DETECTADA* 🚨\n\n"
                        "💱 *Activo:* EUR/USD (Velas de 1H)\n"
                        "📈 *Dirección:* COMPRA (CALL)\n"
                        f"📊 *RSI:* {ultimo_rsi:.2f}\n"
                        "⏱️ *Expiración sugerida:* 1 Hora"
                    )
                    enviar_alerta_telegram(mensaje)
                    
                elif ultimo_cierre < ultima_ema and ultimo_rsi > 70:
                    mensaje = (
                        "🚨 *NUEVA SEÑAL DETECTADA* 🚨\n\n"
                        "💱 *Activo:* EUR/USD (Velas de 1H)\n"
                        "📉 *Dirección:* VENTA (PUT)\n"
                        f"📊 *RSI:* {ultimo_rsi:.2f}\n"
                        "⏱️ *Expiración sugerida:* 1 Hora"
                    )
                    enviar_alerta_telegram(mensaje)
            
        except Exception as e:
            print(f"Error en el ciclo de análisis: {e}")
            
        # Espera 1 hora (3600 segundos) antes de volver a revisar el mercado
        time.sleep(3600)

if __name__ == '__main__':
    # Arrancamos el hilo en segundo plano para el análisis
    hilo = threading.Thread(target=tarea_analisis)
    hilo.daemon = True
    hilo.start()
    
    # Render asigna el puerto automáticamente
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
