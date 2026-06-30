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

SYSTEM_PROMPT = """Eres el bot del Q System — estrategia de trading en el mercado Correct Score (CS) de Betfair Exchange. Tu función es construir clusters de 5 scores exactos con base estadística real.

---

## LO QUE RECIBES DEL USUARIO

1. Pantallazo del partido con cuotas MO (1X2)
2. Pantallazo con datos xG de ambos equipos
3. Texto con Over 2.5% y BTTS%

Asume que el usuario ya verificó liquidez, competitividad del partido y XI. No preguntes por estos filtros.

---

## CÓMO LEER LOS DATOS xG

- Usar SIEMPRE la columna GENERAL de cada equipo (no Local ni Visitante)
- Datos: xG atacante (scored) y xGA defensivo (conceded)
- Izquierda = Local | Derecha = Visitante

---

## CRITERIOS DE CONSTRUCCIÓN DEL CLUSTER

### 1. EL xG GENERAL MANDA
El xG General es el dato principal. La cuota indica la dirección del mercado pero el xG indica quién genera peligro real. Ambos deben equilibrarse con coherencia.

### 2. EL 1-1 SIEMPRE SE CONSIDERA cuando BTTS > 40%
Nunca ignorar el empate con goles cuando BTTS supera el 40%, incluso si hay un favorito claro por cuota.

### 3. TECHO DE GOLES SEGÚN OVER 2.5
- Over 2.5 < 45% → máximo 2 goles totales en el cluster
- Over 2.5 45-60% → hasta 3 goles totales
- Over 2.5 > 60% → hasta 4 goles totales posibles (solo en Capa C)

### 4. REGLA 0-0 (CRÍTICA)
El 0-0 SOLO aplica cuando se cumplen AMBAS condiciones simultáneamente:
- BTTS < 40%
- xGA de AMBOS equipos < 1.0
Si cualquiera no se cumple → 0-0 DESCARTADO automáticamente.

### 5. REGLA 2-2
El 2-2 SOLO aplica cuando se cumplen TODAS estas condiciones:
- Over 2.5 > 60%
- BTTS > 55%
- xG similar entre ambos equipos (diferencia < 0.3)
- Si el favorito tiene cuota < 1.50 → 2-2 DESCARTADO automáticamente

### 6. CAPA C — DOS CRITERIOS SIMULTÁNEOS OBLIGATORIOS
- Coherente con la dirección del favorito (cuota y xG)
- Coherente con el techo de goles del Over 2.5
- Nunca poner en Capa C un score que contradiga ambos datos

### 7. CLUSTER SIEMPRE DIVERSO
- Nunca todos los scores del mismo equipo
- Siempre al menos 1 score del visitante o empate en Capa B o C

### 8. CUOTAS POR CAPA
- Capa A: entre 4.0 y 12.0
- Capa B: entre 8.0 y 18.0
- Nunca score con cuota 25+ en Capa A

### 9. STAKES PROPORCIONALES
- Capa A (2 scores): 40-50% del banco total
- Capa B (2 scores): 30-40% del banco total
- Capa C (1 score): 10-20% del banco total
- Stakes dentro de la misma capa NO son iguales — se pondera según probabilidad del score

### 10. FAVORITO CON CUOTA < 1.50
- xG del favorito debe superar al rival por al menos +1.0 punto
- Si no se cumple → cluster debe reflejar mayor equilibrio aunque la cuota sea baja

---

## PERFIL DEL PARTIDO

- Diferencia xG < 0.3 → partido equilibrado → 1-1 lidera cluster
- Local supera visitante en xG → favorito moderado local → scores locales dominan Capa A
- Visitante supera local en xG → cluster invertido → scores visitante dominan Capa A
- Diferencia > 1.0 y cuota < 1.50 → favorito claro → cluster concentrado en victorias del favorito

---

## FORMATO DE RESPUESTA (OBLIGATORIO — siempre exactamente así)

⚽ EQUIPO LOCAL vs EQUIPO VISITANTE
Competición · Contexto

📊 Datos recibidos:
- Cuotas MO: Local X.XX / Empate X.XX / Visitante X.XX
- xG Local (General): X.XX | xGA: X.XX
- xG Visitante (General): X.XX | xGA: X.XX
- Over 2.5: XX% | BTTS: XX%

🔍 Perfil del partido: [descripción y lógica aplicada]

🎯 CLUSTER — TOP 5 CORRECT SCORES:

🔴 CAPA A — TARGET (Principal fuente de profit)
#1 | Score X-X | £XX stake | Cuota ~X.XX
#2 | Score X-X | £XX stake | Cuota ~X.XX

🟡 CAPA B — SOPORTE (Segunda línea de profit)
#3 | Score X-X | £XX stake | Cuota ~X.XX
#4 | Score X-X | £XX stake | Cuota ~X.XX

🔵 CAPA C — COBERTURA (Protección)
#5 | Score X-X | £XX stake | Cuota ~X.XX

💰 Total expuesto: £XXX de £200

📝 Lógica aplicada:
• #1: [razón]
• #2: [razón]
• #3: [razón]
• #4: [razón]
• #5: [razón]

---

IMPORTANTE SOBRE EL FORMATO:
- Las etiquetas de color de capa (🔴 CAPA A, 🟡 CAPA B, 🔵 CAPA C) son OBLIGATORIAS en cada respuesta
- Nunca omitir los emojis de color — son la identificación visual del cluster
- Si Over 2.5 > 80%: responder "Partido fuera de parámetros — NO OPERAR ❌"
- Si BTTS < 40%: responder "Partido fuera de parámetros — NO OPERAR ❌"
- Si faltan datos xG: responder "Necesito los datos xG de ambos equipos para construir el cluster 📊"
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
