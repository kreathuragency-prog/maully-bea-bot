"""
Test local de Bea — Chatea en la terminal sin WhatsApp
Usa: python test_chat.py
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Verificar API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key or api_key.startswith("sk-proj-TU"):
    print("\n!! Necesitas configurar tu OPENAI_API_KEY en el archivo .env")
    print("   Copia .env.example a .env y agrega tu key de OpenAI\n")
    exit(1)

from brain import generar_respuesta, cargar_info_web
from scraper import scrape_maully


async def main():
    print("=" * 50)
    print("  BEA — Importadora Maully (Test Local)")
    print("=" * 50)
    print("  Escribe un mensaje para hablar con Bea.")
    print("  Escribe 'salir' para terminar.")
    print("  Escribe 'reset' para limpiar el historial.")
    print("=" * 50)
    print()

    # Intentar cargar info de la web
    print("[Sistema] Cargando info de importadoramaully.cl...")
    try:
        info = await scrape_maully()
        if info:
            cargar_info_web(info)
            print("[Sistema] Info de la web cargada OK")
        else:
            print("[Sistema] No se pudo cargar la web, usando solo prompt base")
    except Exception as e:
        print(f"[Sistema] Scraper fallo: {e} — usando solo prompt base")

    print()

    historial = []

    while True:
        try:
            msg = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nChao!")
            break

        if not msg:
            continue
        if msg.lower() == "salir":
            print("\nChao! Gracias por probar a Bea.")
            break
        if msg.lower() == "reset":
            historial = []
            print("[Sistema] Historial limpiado. Nueva conversacion.\n")
            continue

        respuesta = await generar_respuesta(msg, historial)

        # Guardar en historial (como lo hace el bot real)
        historial.append({"role": "user", "content": msg})
        historial.append({"role": "assistant", "content": respuesta})

        # Mantener solo ultimos 20 mensajes
        if len(historial) > 40:
            historial = historial[-40:]

        print(f"\nBea: {respuesta}\n")


if __name__ == "__main__":
    asyncio.run(main())
