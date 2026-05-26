from flask import Flask, request, jsonify
import anthropic
import requests
import json
import os
import time
import tempfile
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import csv

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY')
UAZAPI_URL        = os.environ.get('UAZAPI_URL', 'https://evelinabreu.uazapi.com')
UAZAPI_TOKEN      = os.environ.get('UAZAPI_TOKEN')
INSTANCE_NAME     = os.environ.get('INSTANCE_NAME', 'evelin')
RECOVERY_INTERVAL_HOURS = float(os.environ.get('RECOVERY_INTERVAL_HOURS', '2'))
ALERT_NUMBER      = '5522998004419'

# ─── REDIS (MEMÓRIA PERSISTENTE) ─────────────────────────────────────────────
import redis as _redis_lib

REDIS_URL = os.environ.get('REDIS_URL', '')
CONV_TTL  = 7 * 24 * 3600  # 7 dias em segundos
_redis_client = None

def get_redis():
    global _redis_client
    if _redis_client is None and REDIS_URL:
        _redis_client = _redis_lib.from_url(REDIS_URL, decode_responses=True)
    return _redis_client

def get_conversation(phone):
    r = get_redis()
    if not r:
        return []
    try:
        data = r.get(f"conv:{phone}")
        return json.loads(data) if data else []
    except Exception as e:
        print(f"Redis get error: {e}")
        return []

def save_conversation(phone, messages):
    r = get_redis()
    if not r:
        return
    try:
        r.setex(f"conv:{phone}", CONV_TTL, json.dumps(messages))
    except Exception as e:
        print(f"Redis save error: {e}")

def append_message(phone, role, content):
    history = get_conversation(phone)
    history.append({"role": role, "content": content})
    save_conversation(phone, history)
    return history

# ─── MÍDIAS ──────────────────────────────────────────────────────────────────

PHOTOS = [
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.56_itxlrx.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.57_wmlvhl.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.35_eioep1.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.57_1_mszdep.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.35_1_kidkrk.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779039971/WhatsApp_Image_2026-05-17_at_13.23.34_cxhs57.jpg",
    "https://res.cloudinary.com/dd6o3z4ma/image/upload/v1779040450/Editedimage_1776197718307_ms669e.png",
]
VIDEO_URL_1 = "https://res.cloudinary.com/dd6o3z4ma/video/upload/v1779039974/WhatsApp_Video_2026-05-17_at_13.15.06_zrc6fs.mp4"
VIDEO_URL_2 = "https://res.cloudinary.com/dd6o3z4ma/video/upload/v1779039973/WhatsApp_Video_2026-05-17_at_13.19.32_b5ptia.mp4"

# ─── MENSAGENS ────────────────────────────────────────────────────────────────

GREETING = "Oi! Aqui é a Evelin Abreu, corretora de imóveis. Tô com um lançamento incrível pertinho de Búzios — lotes a poucos minutos da praia, com parcelamento direto pela incorporadora. Você já ouviu falar do Praia Rasa de Búzios 2 ou é a primeira vez?"

SYSTEM_PROMPT = """Você é Evelin Abreu, corretora de imóveis do Praia Rasa de Búzios 2.
Atenda como a própria Evelin conversando no WhatsApp — direta, simpática, profissional sem ser formal.

═══════════════════════════════════════
REGRAS CRÍTICAS — NUNCA VIOLAR:
═══════════════════════════════════════
- NUNCA se despeça ou encerre a conversa por iniciativa própria.
  Só encerre se o cliente disser EXPLICITAMENTE que não tem interesse.
- NUNCA repita uma pergunta já feita nessa conversa. Leia o histórico antes de perguntar.
- NUNCA envie saudação (Oi, Olá, Bom dia) após a primeira mensagem. A conversa já está em andamento.
- Se o cliente disser "ok", "entendido", "certo", "tá bom" — continue o fluxo, NÃO se despeça.
- Uma pergunta por vez. Máximo 2 frases por resposta. Sem textão.
- Nunca revele que é IA. Se perguntarem, diga que é a própria Evelin.
- Se o cliente escrever em espanhol, responda em espanhol.
- Use emojis com moderação — apenas 😊 🏡 👍 📍 ou similares neutros.

ERROS DE DIGITAÇÃO E INTERPRETAÇÃO:
- O cliente pode escrever errado, com gírias ou abreviações. NUNCA comente o erro.
- Interprete pela intenção mais provável: 'ou' = 'oi', 'valer' = 'valor', 'td' = 'tudo', 'blz' = 'beleza'.
- Se não entender, faça UMA pergunta curta sem mencionar o erro.

QUANDO NÃO SOUBER RESPONDER:
- Diga: "Deixa eu verificar essa informação pra você!"
- Inclua [ALERTA] no final da resposta.

QUANDO ENVIAR MÍDIAS — inclua [ENVIAR_MIDIA] quando:
- O cliente ACEITAR ver fotos/vídeos (sim, pode, quero, ok, claro, manda, etc.)
- O cliente PEDIR fotos/vídeos diretamente
Resposta: "Manda ver! Vou te mostrar como ficou 😊" + [ENVIAR_MIDIA]
IMPORTANTE: Após [ENVIAR_MIDIA], NÃO faça pergunta na mesma mensagem. As mídias já chegam com uma pergunta.

FLUXO DA CONVERSA:
1. Responda primeiro o que o cliente perguntou, depois conduza.
2. Assim que demonstrar interesse (morar, veraneio, investimento), ofereça mídias:
   "Tenho fotos e vídeos do empreendimento — quer que eu mande pra você ter uma ideia?"
3. Após aceitar as mídias, aguarde a reação do cliente.
4. Qualifique a proximidade: "Você mora aqui na região ou estava visitando por aqui?"
   - Mora perto: "Ótimo! Você teria disponibilidade esse final de semana pra dar uma passadinha lá?"
   - Visitando: "Entendido. Quando você volta pra cá? Posso já deixar agendado."
   - Pesquisando: "Faz sentido pesquisar bem. Quando você planeja vir pra região?"
5. Conduza para agendamento com aviso de plantão.

AGENDAMENTO — sempre com aviso de plantão:
"[Nome], você teria disponibilidade esse final de semana? Só te peço uma coisa: me avisa antes de ir. Meu plantão é por escala — se você chegar sem combinar comigo, outro corretor te atende e eu perco esse atendimento. Atendo qualquer dia e horário, é só confirmar aqui."

TOM RESPEITOSO:
- Clientes mais velhos: use "a senhora", "o senhor" naturalmente.
- Confirmar: "Pode ser sim", "Tá bom", "Ok", "Pode ser".
- Comentário espiritual/religioso: "Dia abençoado" ou "Amém, com certeza".
- Hesitação do cliente: "Por conta da reserva, não consigo segurar tanto 😊"
- Após visita confirmada, separado: "Ótimo! Te espero lá 😊" / "Se puder me mandar foto da habilitação e um comprovante de residência" / "Já vou adiantando o preenchimento pra ganhar tempo"

OBJEÇÕES:
"Vou ver com meu esposo/esposa":
"Faz sentido decidir junto. Que tal virem os dois esse final de semana? É muito mais fácil decidir vendo pessoalmente. Me avisa antes de ir que garanto o atendimento."

"Vou pensar":
"Sem pressão. Mas as unidades estão saindo rápido — já vendemos boa parte do empreendimento. Você teria disponibilidade esse final de semana pra dar uma olhada? Não precisa decidir nada na hora."

"Tá longe" / "Achei longe":
"Na verdade fica bem perto — são só 3 minutos da praia pela RJ-106. Você está em qual região?"

"Tá caro":
"Entendo. O parcelamento começa em R$899/mês direto pela incorporadora, sem banco e sem SPC. Você prefere ver os lotes de 300m² ou 600m²?"

GATILHOS — usar naturalmente:
- "Imagina ter um lugar pra escapar todo final de semana, a praia a 3 minutos, sem depender de hotel."
- "Quem reserva agora ainda consegue escolher o lote. As unidades estão saindo rápido."
- "Não precisa decidir nada na hora — vem conhecer pessoalmente e vê se faz sentido pra você."

URGÊNCIA — quando hesitar em visitar:
"Já vendemos a maior parte do empreendimento. Quem agenda logo ainda tem escolha de lote."

EMPREENDIMENTO — Praia Rasa de Búzios 2:

LOCALIZAÇÃO:
- Estrada dos Búzios (RJ-106), Bairro da Rasa, divisa Búzios/Cabo Frio
- 800m da Praia Rasa | 3 minutos da praia | Geribá a 8km
- Sempre diga "próximo a Búzios". Só mencione Cabo Frio se perguntarem sobre endereço.
- Maps: https://www.google.com/maps/@-22.7238716,-42.001362,493m

INFRAESTRUTURA:
- Fechado, murado, guarita com segurança 24h e monitoramento
- Meio-fio instalado, rede elétrica em andamento, água encanada em breve
- Playground, praça, quadra de praia, área verde, bosque
- Taxa de condomínio: 10% do salário mínimo (só após entrega)
- Próximo a condomínios de alto padrão, região de kitesurf
- Quadras com vista mar e vista serra

LOTES 300m²:
- A partir de R$899/mês | Entrada R$7.000 (3x sem juros ou 10x no cartão)
- À vista a partir de R$90.000 | Vista mar: a partir de R$1.199/mês

LOTES 600m²:
- A partir de R$1.599/mês | Entrada R$14.000 (3x sem juros ou 10x no cartão)
- À vista a partir de R$160.000 | Vista mar: a partir de R$1.999/mês

FINANCIAMENTO: direto pela incorporadora, sem SPC/Serasa, sem banco. Pode construir com 3 parcelas pagas. Primeira parcela em 45 dias.

DOCUMENTAÇÃO:
"Tem RGI sim. A incorporadora está finalizando o processo na prefeitura. Após a liberação, quem estiver com o lote quitado terá direito à transferência para o seu nome — é opcional, fica por sua conta."

AGENDAMENTO FINAL:
"As visitas são de terça a domingo. Você prefere sábado ou domingo? Manhã ou tarde? Me confirma aqui que já deixo anotado."
"""


# ─── FUNÇÕES DE ENVIO ─────────────────────────────────────────────────────────

def get_instance_token():
    return os.environ.get('INSTANCE_TOKEN', UAZAPI_TOKEN)


def send_message(phone, text):
    url = f"{UAZAPI_URL}/send/text"
    headers = {"token": get_instance_token(), "Content-Type": "application/json"}
    data = {"number": phone, "text": text}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"Text sent to {phone}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error sending text: {e}")
        return None


def send_image(phone, image_url, caption=""):
    headers = {"token": get_instance_token(), "Content-Type": "application/json"}
    data = {"number": phone, "type": "image", "file": image_url, "caption": caption}
    try:
        response = requests.post(f"{UAZAPI_URL}/send/media", headers=headers, json=data, timeout=30)
        print(f"Image sent to {phone}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error sending image: {e}")
        return None


def send_video(phone, video_url, caption=""):
    headers = {"token": get_instance_token(), "Content-Type": "application/json"}
    data = {"number": phone, "type": "video", "file": video_url, "caption": caption}
    try:
        response = requests.post(f"{UAZAPI_URL}/send/media", headers=headers, json=data, timeout=60)
        print(f"Video sent to {phone}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error sending video: {e}")
        return None


def send_media_package(phone):
    """Envia vídeos e fotos. Sem followup hardcoded — IA continua naturalmente."""
    try:
        send_message(phone, "Olha só os vídeos do empreendimento 👇")
        send_video(phone, VIDEO_URL_1)
        time.sleep(2)
        send_video(phone, VIDEO_URL_2)
        time.sleep(2)
        send_message(phone, "E aqui algumas fotos 📍")
        for photo_url in PHOTOS:
            send_image(phone, photo_url)
            time.sleep(1)
        time.sleep(2)
        # Pergunta única após as mídias — sem duplicar com a IA
        followup = "O que achou? 😊"
        send_message(phone, followup)
        append_message(phone, "assistant", followup)
        print(f"Media package complete for {phone}")
    except Exception as e:
        print(f"Error in send_media_package for {phone}: {e}")


def send_alert(phone_client):
    alert_msg = f"⚠️ ALERTA — Cliente {phone_client} fez uma pergunta que não soube responder. Assuma a conversa!"
    send_message(ALERT_NUMBER, alert_msg)


# ─── TRANSCRIÇÃO DE ÁUDIO ─────────────────────────────────────────────────────

def transcribe_audio(audio_url):
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = requests.get(audio_url, timeout=30)
        if response.status_code != 200:
            return None
        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name
        with open(tmp_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", file=audio_file, language="pt"
            )
        os.unlink(tmp_path)
        return transcript.text
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None


# ─── IA ───────────────────────────────────────────────────────────────────────

def get_ai_response(phone, user_message):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Adiciona mensagem do usuário ao histórico persistente
    history = append_message(phone, "user", user_message)

    # Contexto de horário (só no system prompt, sem mensagem extra)
    import pytz
    try:
        br_time = datetime.now(pytz.timezone("America/Sao_Paulo"))
        hora = br_time.strftime("%H:%M")
        hora_int = br_time.hour
        saudacao = "Bom dia" if hora_int < 12 else ("Boa tarde" if hora_int < 18 else "Boa noite")
        time_info = f"\n\n[Horário atual: {hora} — use '{saudacao}' apenas se for o primeiro contato]"
    except:
        time_info = ""

    system = SYSTEM_PROMPT + time_info

    # Monta histórico para a API: prefixo de boas-vindas + últimas 20 mensagens
    last_20 = history[-20:]
    api_messages = [
        {"role": "user",      "content": "Olá"},
        {"role": "assistant", "content": GREETING},
    ] + last_20

    response = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=400,
        system=system,
        messages=api_messages
    )

    reply = response.content[0].text
    append_message(phone, "assistant", reply)
    return reply


# ─── WEBHOOK ──────────────────────────────────────────────────────────────────

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"Webhook received: {list(data.keys()) if data else 'None'}")

    try:
        if not data:
            return jsonify({'status': 'no_data'}), 200

        message = data.get('message', {})
        if not message:
            return jsonify({'status': 'no_message'}), 200

        if message.get('fromMe', False) or message.get('wasSentByApi', False):
            return jsonify({'status': 'from_me'}), 200

        if message.get('isGroup', False):
            return jsonify({'status': 'group'}), 200

        msg_type  = message.get('type', '') or message.get('messageType', '')
        media_type = message.get('mediaType', '')

        sender_pn = message.get('sender_pn', '') or message.get('chatId', '')
        phone = sender_pn.replace('@s.whatsapp.net', '').replace('@c.us', '')

        if not phone:
            return jsonify({'status': 'no_phone'}), 200

        text = ""

        # Áudio
        is_audio = msg_type in ('audio', 'ptt', 'audioMessage', 'PTT')
        is_media_audio = msg_type == 'media' and media_type not in ('image', 'video', 'document', 'sticker')
        if is_audio or is_media_audio:
            raw = (
                message.get('url') or message.get('mediaUrl') or
                message.get('audioUrl') or message.get('content') or message.get('body')
            )
            if isinstance(raw, dict):
                audio_url = raw.get('URL') or raw.get('url') or raw.get('directPath')
                media_key = raw.get('mediaKey', '')
                if audio_url and media_key:
                    try:
                        decrypt_resp = requests.post(
                            f"{UAZAPI_URL}/media/decrypt",
                            headers={"token": get_instance_token(), "Content-Type": "application/json"},
                            json={"url": audio_url, "mediaKey": media_key, "type": "audio"},
                            timeout=30
                        )
                        if decrypt_resp.status_code == 200:
                            audio_url = decrypt_resp.json().get('url', audio_url)
                    except Exception as e:
                        print(f"Decrypt error: {e}")
            else:
                audio_url = raw

            if audio_url:
                text = transcribe_audio(audio_url)
                if not text:
                    send_message(phone, "Oi! 😊 Não consegui ouvir o áudio. Pode me mandar por texto que te respondo na hora!")
                    return jsonify({'status': 'ok'}), 200
            else:
                send_message(phone, "Oi! 😊 Não consegui ouvir o áudio. Pode me mandar por texto que te respondo na hora!")
                return jsonify({'status': 'ok'}), 200

        # Texto
        elif msg_type in ('text', 'Conversation', 'extendedTextMessage'):
            text = (
                message.get('text') or message.get('body') or
                message.get('content') or message.get('conversation') or ''
            ).strip()

        # Cliente enviou imagem/vídeo
        elif msg_type == 'media' and media_type in ('image', 'video', 'sticker', 'document'):
            reply = get_ai_response(phone, "[cliente enviou uma imagem]")
            reply = reply.replace('[ALERTA]', '').replace('[ENVIAR_MIDIA]', '').strip()
            send_message(phone, reply)
            return jsonify({'status': 'ok'}), 200
        else:
            print(f"Skipping type: {msg_type}")
            return jsonify({'status': 'not_supported'}), 200

        if not text:
            return jsonify({'status': 'no_text'}), 200

        print(f"phone='{phone}', text='{text[:80]}'")

        reply = get_ai_response(phone, text)

        alert_flag = '[ALERTA]' in reply
        media_flag = '[ENVIAR_MIDIA]' in reply

        # Fallback: detecta pedido de mídia direto no texto do cliente
        if not media_flag:
            media_keywords = ['sim', 'pode', 'quero', 'ok', 'claro', 'manda', 'foto', 'fotos',
                              'video', 'vídeo', 'videos', 'vídeos', 'queria ver', 'quero ver',
                              'manda sim', 'pode mandar', 'com certeza', 'claro que sim']
            history = get_conversation(phone)
            last_bot = next((m['content'] for m in reversed(history[:-1])
                             if m['role'] == 'assistant'), '')
            if (any(kw in text.lower() for kw in media_keywords) and
                    any(kw in last_bot.lower() for kw in ['foto', 'vídeo', 'video', 'imagens', 'mandar'])):
                media_flag = True

        reply = reply.replace('[ALERTA]', '').replace('[ENVIAR_MIDIA]', '').strip()

        print(f"Sending reply: {reply[:80]}")
        send_message(phone, reply)

        if alert_flag:
            send_alert(phone)

        if media_flag:
            threading.Thread(target=send_media_package, args=(phone,)).start()

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── RECOVERY ─────────────────────────────────────────────────────────────────

recovery_contacts = []
recovery_index = 0


def load_recovery_contacts():
    global recovery_contacts
    try:
        if os.path.exists('recovery.csv'):
            with open('recovery.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                recovery_contacts = [row for row in reader if row.get('sent', '').lower() != 'sim']
    except Exception as e:
        print(f"Error loading recovery contacts: {e}")


def send_recovery_message():
    global recovery_index, recovery_contacts
    load_recovery_contacts()
    if not recovery_contacts or recovery_index >= len(recovery_contacts):
        recovery_index = 0
        return
    contact = recovery_contacts[recovery_index]
    phone = contact.get('telefone', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    name  = contact.get('nome', '')
    custom_msg = contact.get('mensagem', '')
    if not phone:
        recovery_index += 1
        return
    message = custom_msg or f"Oi{' ' + name if name else ''}! Aqui é a Evelin 😊 Ainda temos algumas unidades no Praia Rasa de Búzios 2 — e as últimas estão saindo rápido. Você ainda tem interesse? Me avisa antes de visitar que garanto seu atendimento!"
    send_message(phone, message)
    recovery_index += 1


# ─── ROTAS ────────────────────────────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running', 'timestamp': datetime.now().isoformat()}), 200


@app.route('/recovery/start', methods=['POST'])
def start_recovery():
    load_recovery_contacts()
    return jsonify({'status': 'ok', 'contacts': len(recovery_contacts)}), 200


# ─── INICIALIZAÇÃO ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_recovery_message, 'interval', hours=RECOVERY_INTERVAL_HOURS)
    scheduler.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
