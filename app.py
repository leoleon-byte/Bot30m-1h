import time
import os
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "¡El Bot de Señales está activo y funcionando!"

# Simulación de la tarea que el bot hará periódicamente
def tarea_analisis():
    while True:
        print("Analizando el mercado (30m / 1h)...")
        # Aquí irá tu lógica de indicadores (EMA, RSI)
        # Aquí consultará a Supabase para evitar duplicados
        # Aquí enviará la alerta a Telegram si hay confluencia
        
        # Espera 15 minutos antes de volver a revisar el mercado
        time.sleep(900) 

if __name__ == '__main__':
    # Arrancamos el análisis en segundo plano para que Flask pueda atender el puerto web
    import threading
    hilo = threading.Thread(target=tarea_analisis)
    hilo.daemon = True
    hilo.start()
    
    # Render asigna un puerto automáticamente a través de la variable de entorno PORT
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
