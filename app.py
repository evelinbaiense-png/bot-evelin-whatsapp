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
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
UAZAPI_URL = os.environ.get('UAZAPI_URL', 'https://evelinabreu.uazapi.com')
UAZAPI_TOKEN = os.environ.get('UAZAPI_TOKEN')
INSTANCE_NAME = os.environ.get('INSTANCE_NAME', 'evelin')
RECOVERY_INTERVAL_HOURS = float(os.environ.get('RECOVERY_INTERVAL_HOURS', '2'))
ALERT_NUMBER = '5522998004419'

conversations = {}

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

GREETING = "Oi! 😊 Aqui é a Evelin, corretora do Praia Rasa de Búzios 2. Você já conhece o empreendimento ou é a primeira vez?"

SYSTEM_PROMPT = """Você é Evelin Abreu, corretora de imóveis do Praia Rasa de Búzios 2.
Atenda como a própria Evelin no WhatsApp — humana, próxima, profissional sem ser rígida.

REGRA DE TOM:
- Espelhe o cliente. Se ele for informal e descontraído, relaxe também. Se for formal, mantenha o profissionalismo.
- Respostas curtas. Máximo 2 frases. Sem textão.
- Uma pergunta por vez.
- Nunca revele que é IA. Se perguntarem, diga que é a própria Evelin.
- Se o cliente escrever em espanhol, responda em espanhol.

QUANDO NÃO SOUBER RESPONDER:
- Diga: "Deixa eu verificar essa informação pra você! 😊"
- Inclua exatamente o marcador [ALERTA] no final da resposta (será removido automaticamente).

QUANDO O CLIENTE ACEITAR AS MÍDIAS:
- Inclua [ENVIAR_MIDIA] no final da resposta.
- Continue a conversa normalmente perguntando o nome.

FLUXO:
1. Responda primeiro o que o cliente perguntou, depois conduza.
2. Assim que o cliente demonstrar qualquer interesse (morar, veraneio, investimento), ofereça as mídias IMEDIATAMENTE: "Que ótimo! 😊 Posso te mandar umas fotos e vídeos do empreendimento pra você já ter uma ideia?"
3. Quando o cliente aceitar, inclua [ENVIAR_MIDIA] no final da resposta e pergunte o nome naturalmente.
4. Qualifique a proximidade com a região:
   "[Nome], você mora aqui na região ou estava visitando?"
   - Se mora perto: "Que ótimo! Você tem disponibilidade esse final de semana pra dar uma passadinha? Me avisa antes — meu plantão é por escala e quero garantir seu atendimento 😊"
   - Se estava visitando: "Quando você volta pra cá? A gente já deixa agendado 😊 Me avisa antes de ir!"
   - Se estava só pesquisando: "Faz sentido pesquisar antes! Quando você planeja vir pra região?"
5. Conduza para agendamento com aviso de plantão.

AGENDAMENTO — sempre com aviso de plantão:
"[Nome], você tem disponibilidade esse final de semana? Só te peço uma coisa: me avisa antes de ir 😊 Meu plantão é por escala — se você chegar sem agendar comigo, outro corretor te atende e eu perco essa venda. Atendo qualquer dia e horário, é só confirmar aqui!"

OBJEÇÕES:
"Vou ver com meu esposo/esposa":
"Claro! Que tal vocês dois virem juntos esse final de semana? Fica muito mais fácil decidir vendo pessoalmente 😊 Você prefere sábado ou domingo? Me avisa antes de ir — meu plantão é por escala!"

"Vou pensar":
"Sem pressão! Mas as unidades estão saindo rápido 😊 Você tem disponibilidade esse final de semana pra dar uma olhada? Não precisa decidir nada na hora — só me avisa antes de ir!"

"Tá longe" / "Achei longe":
"Pertinho! 😄 São só 3 minutinhos da praia pela RJ-106. Você está em qual região agora?"

"Tá caro":
"Entendo! O parcelamento começa em R$899/mês direto pela incorporadora, sem banco e sem SPC 😊 Você prefere ver os lotes de 300m² ou 600m²?"

GATILHOS EMOCIONAIS — usar naturalmente na conversa:
- "Já se imaginou passando o final de semana com a família, crianças brincando, a praia a 3 minutos?"
- "Esse é o momento certo de investir no litoral — as unidades estão acabando rápido."
- "Não precisa decidir nada na hora — vem conhecer pessoalmente e sente a energia do lugar."

URGÊNCIA — usar quando hesitar em visitar:
"As unidades estão acabando rápido — já vendemos a maior parte 😊 Quem agenda logo ainda escolhe o lote!"

EMPREENDIMENTO — Praia Rasa de Búzios 2:

LOCALIZAÇÃO:
- Estrada dos Búzios (RJ-106), Bairro da Rasa, divisa Búzios/Cabo Frio
- 800m da Praia Rasa | 3 minutos da praia | Geribá a 8km
- Sempre diga "próximo a Búzios". Só mencione Cabo Frio se perguntarem sobre endereço ou documentação.
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
"Tem RGI sim 😊 A incorporadora está finalizando o processo na prefeitura. Após a liberação, quem estiver com o lote quitado terá direito à transferência para o seu nome — opcional, fica por sua conta."

AGENDAMENTO FINAL:
"Ótimo! As visitas são de terça a domingo. Você prefere sábado ou domingo? Manhã ou tarde? Me confirma aqui que já anoto pra te atender pessoalmente 😊"
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
    url = f"{UAZAPI_URL}/send/image"
    headers = {"token": get_instance_token(), "Content-Type": "application/json"}
    data = {"number": phone, "image": image_url, "caption": caption}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"Image sent to {phone}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error sending image: {e}")
        return None


def send_video(phone, video_url, caption=""):
    url = f"{UAZAPI_URL}/send/video"
    headers = {"token": get_instance_token(), "Content-Type": "application/json"}
    data = {"number": phone, "video": video_url, "caption": caption}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        print(f"Video sent to {phone}: {response.status_code}")
        return response
    except Exception as e:
        print(f"Error sending video: {e}")
        return None


def send_media_package(phone):
    """Envia todas as fotos e o vídeo para o cliente"""
    send_message(phone, "Olha que lindo! 😍 Algumas fotos do empreendimento:")
    for photo_url in PHOTOS:
        send_image(phone, photo_url)
        time.sleep(1.5)
    time.sleep(2)
    send_message(phone, "E aqui os vídeos do empreendimento 🎥")
    send_video(phone, VIDEO_URL_1)
    time.sleep(3)
    send_video(phone, VIDEO_URL_2)


def send_alert(phone_client):
    """Envia alerta para Evelin quando o bot não sabe responder"""
    alert_msg = f"⚠️ ALERTA — Cliente {phone_client} fez uma pergunta que não soube responder. Assuma a conversa!"
    send_message(ALERT_NUMBER, alert_msg)


# ─── TRANSCRIÇÃO DE ÁUDIO ─────────────────────────────────────────────────────

def transcribe_audio(audio_url):
    """Transcreve áudio usando OpenAI Whisper"""
    if not OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        response = requests.get(audio_url, timeout=30)
        if response.status_code != 200:
            print(f"Failed to download audio: {response.status_code}")
            return None

        with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        with open(tmp_path, 'rb') as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="pt"
            )

        os.unlink(tmp_path)
        print(f"Transcribed: {transcript.text[:80]}")
        return transcript.text

    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return None


# ─── IA ───────────────────────────────────────────────────────────────────────

def get_ai_response(phone, user_message):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if phone not in conversations:
        conversations[phone] = []

    conversations[phone].append({"role": "user", "content": user_message})
    history = conversations[phone][-20:]

    api_messages = [
        {"role": "user", "content": "Olá"},
        {"role": "assistant", "content": GREETING},
    ] + history

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=api_messages
    )

    reply = response.content[0].text
    conversations[phone].append({"role": "assistant", "content": reply})
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

        print(f"message keys: {list(message.keys())}")

        if message.get('fromMe', False) or message.get('wasSentByApi', False):
            return jsonify({'status': 'from_me'}), 200

        if message.get('isGroup', False):
            return jsonify({'status': 'group'}), 200

        msg_type = message.get('type', '') or message.get('messageType', '')

        sender_pn = message.get('sender_pn', '') or message.get('chatId', '')
        phone = sender_pn.replace('@s.whatsapp.net', '').replace('@c.us', '')

        if not phone:
            return jsonify({'status': 'no_phone'}), 200

        text = ""

        # Áudio
        if msg_type in ('audio', 'ptt', 'audioMessage', 'PTT'):
            audio_url = (
                message.get('url') or
                message.get('mediaUrl') or
                message.get('audioUrl') or
                message.get('body')
            )
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
                message.get('text') or
                message.get('body') or
                message.get('content') or
                message.get('conversation') or
                ''
            ).strip()
        else:
            print(f"Skipping type: {msg_type}")
            return jsonify({'status': 'not_supported'}), 200

        print(f"phone='{phone}', text='{text[:80]}'")

        if not text:
            return jsonify({'status': 'no_text'}), 200

        reply = get_ai_response(phone, text)

        # Detectar marcadores especiais
        alert_flag = '[ALERTA]' in reply
        media_flag = '[ENVIAR_MIDIA]' in reply

        # Limpar marcadores
        reply = reply.replace('[ALERTA]', '').replace('[ENVIAR_MIDIA]', '').strip()

        # Enviar resposta
        print(f"Sending reply: {reply[:80]}")
        send_message(phone, reply)

        # Ações especiais
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
            print(f"Loaded {len(recovery_contacts)} recovery contacts")
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
    name = contact.get('nome', '')
    custom_msg = contact.get('mensagem', '')

    if not phone:
        recovery_index += 1
        return

    if custom_msg:
        message = custom_msg
    else:
        message = f"Oi{' ' + name if name else ''}! Aqui é a Evelin 😊 Ainda temos algumas unidades no Praia Rasa de Búzios 2 — e as últimas estão saindo rápido. Você ainda tem interesse? Me avisa antes de visitar que garanto seu atendimento!"

    result = send_message(phone, message)
    if result and result.status_code == 200:
        print(f"Recovery sent to {phone} ({name})")

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
