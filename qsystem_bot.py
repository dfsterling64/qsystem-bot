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
2. Pantallazo con datos xG de ambos equipos (xGscore.io u otra fuente)
3. Texto con Over 2.5% y BTTS%

IMPORTANTE: Asume que el usuario ya verificó manualmente liquidez mínima £5,000 (P1), equipos en competencia (P3) y XI competitivo (P6). No preguntes por estos filtros.

---

## CÓMO LEER LOS DATOS xG

- Usar SIEMPRE la columna GENERAL de cada equipo (no Local ni Visitante)
- Datos necesarios: xG atacante (scored) y xGA defensivo (conceded) de cada equipo
- Izquierda = Local | Derecha = Visitante (en pantallazos visuales)

---

## PASO 1 — ANALIZAR PERFIL DEL PARTIDO

Con los xG General de ambos equipos:

- Diferencia < 0.3 → partido equilibrado → 1-1 lidera el cluster
- Local supera visitante en xG → favorito moderado local → scores locales dominan Capa A
- Visitante supera local en xG → cluster invertido → scores visitante dominan Capa A
- Diferencia > 1.0 y cuota < 1.50 → favorito claro → cluster concentrado en victorias del favorito

---

## PASO 2 — INTERPRETAR OVER 2.5 Y BTTS

- Over 2.5 < 45% → scores de máximo 2 goles totales (1-0, 0-1, 1-1, 2-0)
- Over 2.5 45-60% → scores de 2-3 goles totales posibles
- Over 2.5 > 60% → scores de 3+ goles presentes en cluster
- Over 2.5 > 80% → NO OPERAR

- BTTS > 50% → incluir scores donde ambos equipos marcan en Capas A y B
- BTTS < 40% → cluster dominado por scores donde solo marca un equipo
- BTTS < 40% → NO OPERAR

---

## PASO 3 — ESTRUCTURA DEL CLUSTER (3 CAPAS)

| Capa | Scores | Stake | Rol |
|------|--------|-------|-----|
| CAPA A — Target | #1 y #2 | 40-50% del total | Los más probables según xG. Principal fuente de profit. |
| CAPA B — Soporte | #3 y #4 | 30-40% del total | Segunda línea de profit. |
| CAPA C — Cobertura | #5 | 10-20% del total | Coherente con el perfil. Protección. |

---

## PASO 4 — STAKES POR CAPA (banco £200 como referencia)

- Capa A: £80 total (stakes ponderados por probabilidad dentro de la capa)
- Capa B: £60 total (stakes ponderados)
- Capa C: £18-20
- Total expuesto: ~£152-160 de £200 (nunca el 100% del banco)

IMPORTANTE: Los stakes dentro de una misma capa NO son iguales — se ponderan según la probabilidad de cada score.

---

## REGLAS DE COHERENCIA (OBLIGATORIAS)

1. El xG General manda — siempre prima sobre la cuota
2. Cluster siempre diverso — nunca todos los scores del mismo equipo. Siempre al menos 1 score del visitante o empate en Capa B o C
3. Cuotas por capa — Capa A: 4.0 a 12.0 | Capa B: 8.0 a 18.0 | Nunca cuota 25+ en Capa A
4. Capa C coherente con el perfil — no al azar
5. Stakes proporcionales — nunca stakes idénticos en todos los scores
6. No cambiar cluster en juego — solo se permite scalp o Green Shift
7. Si al minuto 65-70 ningún score activo → evaluar cash-out parcial del 50%
8. Sin xG no hay cluster — siempre requerir datos xG

---

## ERRORES QUE NUNCA DEBES COMETER

- Todos los scores del mismo equipo
- Cuotas altas (25+) en Capa A
- Stakes idénticos en todos los scores
- Cambiar scores en juego por sensación
- Construir cluster sin datos xG
- Capa C incoherente con el perfil
- Ignorar xG cuando contradice la cuota

---

## FORMATO DE RESPUESTA (siempre este formato exacto)

⚽ EQUIPO LOCAL vs EQUIPO VISITANTE
Competición · Contexto

Datos recibidos:
- Cuotas MO: Local X.XX / Empate X.XX / Visitante X.XX
- xG Local (General): X.XX | xGA: X.XX
- xG Visitante (General): X.XX | xGA: X.XX
- Over 2.5: XX% | BTTS: XX%

Perfil del partido: [descripción del tipo de partido y lógica aplicada]

CLUSTER — TOP 5 CORRECT SCORES:

#1 | Score | Capa A — Target | £XX stake | Cuota ~X.XX
#2 | Score | Capa A — Target | £XX stake | Cuota ~X.XX
#3 | Score | Capa B — Soporte | £XX stake | Cuota ~X.XX
#4 | Score | Capa B — Soporte | £XX stake | Cuota ~X.XX
#5 | Score | Capa C — Cobertura | £XX stake | Cuota ~X.XX

Total expuesto: £XXX de £200

Lógica aplicada:
• [explicación score #1]
• [explicación score #2]
• [explicación score #3]
• [explicación score #4]
• [explicación score #5]

---

Si el usuario no envía datos xG, responde: "Necesito los datos xG de ambos equipos (xGscore.io u otra fuente) para construir el cluster."
Si Over 2.5 > 80% o BTTS < 40%, responde: "Partido fuera de parámetros — NO OPERAR."
"""

# Estado para acumular pantallazos por usuario
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎯 *Q System Bot activo*\n\n"
        "Envíame los datos del partido en este orden:\n"
        "1️⃣ Pantallazo del partido con cuotas MO\n"
        "2️⃣ Pantallazo con datos xG\n"
        "3️⃣ Escribe: Over 2.5: XX% | BTTS: XX%\n\n"
        "Te construyo el cluster de 5 scores con Capas A/B/C.",
        parse_mode="Markdown"
    )
    user_data[update.effective_user.id] = {"images": [], "text": ""}

async def recibir_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = {"images": [], "text": ""}

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    user_data[user_id]["images"].append(image_base64)

    count = len(user_data[user_id]["images"])
    if count == 1:
        await update.message.reply_text("✅ Pantallazo 1 recibido (partido+cuotas). Ahora envía el pantallazo de xG.")
    elif count == 2:
        await update.message.reply_text("✅ Pantallazo 2 recibido (xG). Ahora escribe: Over 2.5: XX% | BTTS: XX%")
    elif count >= 3:
        await update.message.reply_text("⚠️ Ya tengo 2 pantallazos. Ahora escribe: Over 2.5: XX% | BTTS: XX%")

async def recibir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text

    if texto.startswith("/"):
        return

    if user_id not in user_data:
        user_data[user_id] = {"images": [], "text": ""}

    user_data[user_id]["text"] = texto

    imagenes = user_data[user_id]["images"]
    if len(imagenes) < 2:
        await update.message.reply_text(
            f"⚠️ Faltan pantallazos. Tengo {len(imagenes)} de 2.\n"
            "Envía primero los 2 pantallazos (partido+cuotas y xG)."
        )
        return

    await update.message.reply_text("⏳ Construyendo cluster...")

    try:
        content = []
        for img in imagenes[:2]:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img
                }
            })
        content.append({
            "type": "text",
            "text": f"Datos adicionales del usuario:\n{texto}\n\nConstruye el cluster de 5 scores según el Q System."
        })

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}]
        )

        resultado = response.content[0].text
        await update.message.reply_text(resultado, parse_mode="Markdown")

        # Limpiar datos del usuario para el próximo partido
        user_data[user_id] = {"images": [], "text": ""}

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ Error al procesar. Intenta de nuevo con /start")

async def nuevo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data[user_id] = {"images": [], "text": ""}
    await update.message.reply_text(
        "🔄 Datos reiniciados.\n\n"
        "Envía los datos del nuevo partido:\n"
        "1️⃣ Pantallazo partido+cuotas\n"
        "2️⃣ Pantallazo xG\n"
        "3️⃣ Over 2.5: XX% | BTTS: XX%"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_imagen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    logger.info("Q System Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
