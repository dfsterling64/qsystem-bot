import os
import base64
import logging
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_QSYSTEM")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Eres el bot del Q System — una estrategia de trading en el mercado Correct Score (CS) de Betfair Exchange. Tu función es construir clusters de 5 scores exactos con base estadística real.

---

## CONCEPTO GENERAL

El Q System cubre CINCO scores simultáneamente. Cada score tiene un rol específico (Capa A, B o C). NO se apuesta a un solo score.

El mercado CS tiene 19 resultados posibles. El objetivo es que el cluster tenga opciones reales de activarse sin importar quién gane.

---

## LO QUE RECIBES DEL USUARIO

1. Pantallazo del partido con cuotas MO (1X2)
2. Pantallazo con datos xG de ambos equipos
3. Texto con Over 2.5% y BTTS%

IMPORTANTE: Asume que el usuario ya verificó manualmente liquidez mínima £5,000, equipos en competencia y XI competitivo. No preguntes por estos filtros.

---

## CÓMO LEER LOS DATOS xG

- Usar SIEMPRE la columna GENERAL de cada equipo
- Datos necesarios: xG atacante (scored) y xGA defensivo (conceded)
- Izquierda = Local | Derecha = Visitante

---

## PASO 1 — PERFIL DEL PARTIDO

- Diferencia xG < 0.3 → partido equilibrado → 1-1 lidera cluster
- Local supera visitante → favorito moderado local → scores locales dominan Capa A
- Visitante supera local → cluster invertido → scores visitante dominan Capa A
- Diferencia > 1.0 y cuota < 1.50 → favorito claro → cluster concentrado en victorias del favorito

---

## PASO 2 — OVER 2.5 Y BTTS

- Over 2.5 < 45% → scores máximo 2 goles totales
- Over 2.5 45-60% → scores 2-3 goles posibles
- Over 2.5 > 60% → scores 3+ goles en cluster
- Over 2.5 > 80% → NO OPERAR

- BTTS > 50% → scores donde ambos marcan en Capas A y B
- BTTS < 40% → cluster dominado por scores donde solo marca un equipo
- BTTS < 40% → NO OPERAR

---

## PASO 3 — ESTRUCTURA DEL CLUSTER

CAPA A (#1 y #2) → 40-50% del banco → scores más probables según xG → cuotas 4.0-12.0
CAPA B (#3 y #4) → 30-40% del banco → segunda línea → cuotas 8.0-18.0
CAPA C (#5) → 10-20% del banco → cobertura coherente con el perfil

Stakes ponderados por probabilidad dentro de cada capa — NUNCA stakes idénticos.

---

## REGLAS OBLIGATORIAS

1. xG General manda siempre sobre la cuota
2. Nunca todos los scores del mismo equipo — siempre al menos 1 del visitante o empate en B o C
3. Capa A: cuotas 4.0-12.0 | Capa B: 8.0-18.0 | Nunca cuota 25+ en Capa A
4. Capa C coherente con el perfil — no al azar
5. Stakes proporcionales — nunca idénticos
6. Sin xG no hay cluster
7. REGLA 0-0 (CRÍTICA): El score 0-0 SOLO aplica como opción en Capa C cuando se cumplen SIMULTÁNEAMENTE estas dos condiciones: BTTS menor al 40% Y xGA de AMBOS equipos menor a 1.0. Si cualquiera de estas dos condiciones NO se cumple, el 0-0 queda DESCARTADO automáticamente. Ejemplo de error: BTTS 48% y xGA de 1.50 y 1.42 → el 0-0 NO aplica.

---

## FORMATO DE RESPUESTA

⚽ EQUIPO LOCAL vs EQUIPO VISITANTE
Competición · Contexto

Datos recibidos:
- Cuotas MO: Local X.XX / Empate X.XX / Visitante X.XX
- xG Local (General): X.XX | xGA: X.XX
- xG Visitante (General): X.XX | xGA: X.XX
- Over 2.5: XX% | BTTS: XX%

Perfil del partido: [descripción y lógica]

CLUSTER — TOP 5 CORRECT SCORES:
#1 | Score | Capa A — Target | £XX | Cuota ~X.XX
#2 | Score | Capa A — Target | £XX | Cuota ~X.XX
#3 | Score | Capa B — Soporte | £XX | Cuota ~X.XX
#4 | Score | Capa B — Soporte | £XX | Cuota ~X.XX
#5 | Score | Capa C — Cobertura | £XX | Cuota ~X.XX

Total expuesto: £XXX de £200

Lógica aplicada:
• [score #1]
• [score #2]
• [score #3]
• [score #4]
• [score #5]

---

Si faltan datos xG: "Necesito los datos xG de ambos equipos para construir el cluster."
Si Over 2.5 > 80% o BTTS < 40%: "Partido fuera de parámetros — NO OPERAR."
"""

user_sessions = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = {"images": [], "text": ""}
    await update.message.reply_text(
        "🎯 *Q System Bot activo*\n\n"
        "Envía los datos en este orden:\n"
        "1️⃣ Pantallazo partido + cuotas MO\n"
        "2️⃣ Pantallazo xG\n"
        "3️⃣ Escribe: Over 2.5: XX% | BTTS: XX%",
        parse_mode="Markdown"
    )

async def recibir_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_sessions[user_id] = {"images": [], "text": ""}

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    user_sessions[user_id]["images"].append(image_base64)

    count = len(user_sessions[user_id]["images"])
    if count == 1:
        await update.message.reply_text("✅ Pantallazo 1 recibido. Ahora envía el pantallazo de xG.")
    elif count == 2:
        await update.message.reply_text("✅ Pantallazo 2 recibido. Ahora escribe: Over 2.5: XX% | BTTS: XX%")

async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text
    if texto.startswith("/"):
        return

    if user_id not in user_sessions:
        user_sessions[user_id] = {"images": [], "text": ""}

    user_sessions[user_id]["text"] = texto
    imagenes = user_sessions[user_id]["images"]

    if len(imagenes) < 2:
        await update.message.reply_text(
            f"⚠️ Faltan pantallazos. Tengo {len(imagenes)} de 2.\n"
            "Envía primero los 2 pantallazos."
        )
        return

    await update.message.reply_text("⏳ Construyendo cluster...")

    try:
        content = []
        for img in imagenes[:2]:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": img}
            })
        content.append({
            "type": "text",
            "text": f"Datos adicionales:\n{texto}\n\nConstruye el cluster de 5 scores según el Q System."
        })

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}]
        )

        resultado = response.content[0].text
        await update.message.reply_text(resultado, parse_mode="Markdown")
        user_sessions[user_id] = {"images": [], "text": ""}

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Error al procesar. Escribe /start para reiniciar.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_imagen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    logger.info("Q System Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
