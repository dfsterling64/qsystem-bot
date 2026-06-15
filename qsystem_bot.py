import os
import base64
import logging
import json
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials
import anthropic
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN_QSYSTEM")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ADMIN_ID = 624992860
SHEET_ID = "1bkWjBDdT0MzT3MsFzUNNFqLiZHIu_9dwolAx68ptVPA"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1

def es_usuario_activo(user_id):
    try:
        sheet = get_sheet()
        registros = sheet.get_all_records()
        hoy = datetime.now().date()
        for r in registros:
            if str(r["user_id"]) == str(user_id):
                if str(r["activo"]).upper() == "SI":
                    vencimiento = datetime.strptime(str(r["vencimiento"]), "%Y-%m-%d").date()
                    if vencimiento >= hoy:
                        return True
                    else:
                        sheet.update_cell(registros.index(r) + 2, 4, "NO")
                        return False
        return False
    except Exception as e:
        logger.error(f"Error verificando usuario: {e}")
        return False

def agregar_usuario(user_id, nombre, dias):
    try:
        sheet = get_sheet()
        registros = sheet.get_all_records()
        vencimiento = (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
        for i, r in enumerate(registros):
            if str(r["user_id"]) == str(user_id):
                sheet.update(f"B{i+2}:D{i+2}", [[nombre, vencimiento, "SI"]])
                return f"✅ Usuario {nombre} actualizado. Vence: {vencimiento}"
        sheet.append_row([str(user_id), nombre, vencimiento, "SI"])
        return f"✅ Usuario {nombre} agregado. Vence: {vencimiento}"
    except Exception as e:
        return f"❌ Error: {e}"

def quitar_usuario(user_id):
    try:
        sheet = get_sheet()
        registros = sheet.get_all_records()
        for i, r in enumerate(registros):
            if str(r["user_id"]) == str(user_id):
                sheet.update_cell(i + 2, 4, "NO")
                return f"✅ Usuario {user_id} desactivado."
        return "❌ Usuario no encontrado."
    except Exception as e:
        return f"❌ Error: {e}"

def listar_usuarios():
    try:
        sheet = get_sheet()
        registros = sheet.get_all_records()
        hoy = datetime.now().date()
        activos = []
        for r in registros:
            if str(r["activo"]).upper() == "SI":
                vencimiento = datetime.strptime(str(r["vencimiento"]), "%Y-%m-%d").date()
                dias_restantes = (vencimiento - hoy).days
                if dias_restantes >= 0:
                    activos.append(f"👤 {r['nombre']} | Vence: {r['vencimiento']} ({dias_restantes} días)")
        if not activos:
            return "No hay usuarios activos."
        return "\n".join(activos)
    except Exception as e:
        return f"❌ Error: {e}"

def consultar_usuario(user_id):
    try:
        sheet = get_sheet()
        registros = sheet.get_all_records()
        for r in registros:
            if str(r["user_id"]) == str(user_id):
                return f"👤 {r['nombre']}\nEstado: {r['activo']}\nVence: {r['vencimiento']}"
        return "Usuario no encontrado."
    except Exception as e:
        return f"❌ Error: {e}"

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
7. REGLA 0-0 (CRÍTICA): El score 0-0 SOLO aplica como opción en Capa C cuando se cumplen SIMULTÁNEAMENTE estas dos condiciones: BTTS menor al 40% Y xGA de AMBOS equipos menor a 1.0. Si cualquiera de estas dos condiciones NO se cumple, el 0-0 queda DESCARTADO automáticamente. Ejemplo de error: BTTS 48% y xGA de 1.50 y 1.42 → el 0-0 NO aplica aunque parezca defensivo.

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
    if user_id == ADMIN_ID:
        await update.message.reply_text(
            "🎯 *Q System Bot — Admin activo*\n\n"
            "Comandos:\n"
            "/agregar ID dias nombre\n"
            "/quitar ID\n"
            "/lista\n"
            "/consultar ID",
            parse_mode="Markdown"
        )
    elif es_usuario_activo(user_id):
        user_sessions[user_id] = {"images": [], "text": ""}
        await update.message.reply_text(
            "🎯 *Q System Bot activo*\n\n"
            "Envía los datos en este orden:\n"
            "1️⃣ Pantallazo partido + cuotas MO\n"
            "2️⃣ Pantallazo xG\n"
            "3️⃣ Escribe: Over 2.5: XX% | BTTS: XX%",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "⛔ No tienes acceso. Contacta al administrador para adquirir tu plan."
        )

async def agregar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        args = context.args
        user_id = args[0]
        dias = int(args[1])
        nombre = " ".join(args[2:]) if len(args) > 2 else f"Usuario {user_id}"
        resultado = agregar_usuario(user_id, nombre, dias)
        await update.message.reply_text(resultado)
    except Exception:
        await update.message.reply_text("Uso: /agregar ID dias nombre\nEjemplo: /agregar 123456789 30 Juan")

async def quitar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        user_id = context.args[0]
        resultado = quitar_usuario(user_id)
        await update.message.reply_text(resultado)
    except Exception:
        await update.message.reply_text("Uso: /quitar ID\nEjemplo: /quitar 123456789")

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    resultado = listar_usuarios()
    await update.message.reply_text(f"👥 *Usuarios activos:*\n\n{resultado}", parse_mode="Markdown")

async def consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        user_id = context.args[0]
        resultado = consultar_usuario(user_id)
        await update.message.reply_text(resultado)
    except Exception:
        await update.message.reply_text("Uso: /consultar ID")

async def recibir_imagen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID and not es_usuario_activo(user_id):
        await update.message.reply_text("⛔ Tu acceso ha vencido. Contacta al administrador.")
        return

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
    if user_id != ADMIN_ID and not es_usuario_activo(user_id):
        await update.message.reply_text("⛔ Tu acceso ha vencido. Contacta al administrador.")
        return

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
    app.add_handler(CommandHandler("agregar", agregar))
    app.add_handler(CommandHandler("quitar", quitar))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("consultar", consultar))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_imagen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto))
    logger.info("Q System Bot iniciado...")
    app.run_polling()

if __name__ == "__main__":
    main()
