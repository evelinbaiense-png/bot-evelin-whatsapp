from flask import Flask, request, jsonify
import anthropic
import requests
import json
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import csv

app = Flask(__name__)

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
UAZAPI_URL = os.environ.get('UAZAPI_URL', 'https://evelinabreu.uazapi.com')
UAZAPI_TOKEN = os.environ.get('UAZAPI_TOKEN')
INSTANCE_NAME = os.environ.get('INSTANCE_NAME', 'evelin')
RECOVERY_INTERVAL_HOURS = float(os.environ.get('RECOVERY_INTERVAL_HOURS', '2'))

conversations = {}

GREETING = "✨ Olá! Que bom ter você por aqui 😊 Eu sou a Evelin Abreu, corretora de imóveis! Os lotes ficam a poucos minutos da praia, com entrada facilitada e parcelamento direto pela incorporadora. Esse é um grande passo para realizar um sonho! Me conta, você já conhece o Praia Rasa de Búzios 2 ou ainda não?"

SYSTEM_PROMPT = """Você é Evelin Abreu, corretora de imóveis.
Atenda de forma natural, humana, simpática e direta — como a própria Evelin conversando no WhatsApp.

REGRAS:
- Respostas CURTAS. Máximo 2 frases. Sem textão.
- RESPONDA PRIMEIRO o que o cliente perguntou, depois qualifique.
- Uma pergunta por vez. Nunca dispare várias perguntas seguidas.
- Se o cliente escrever em espanhol, responda em espanhol.
- Se quiser mandar áudio, responda que sim.
- Não invente informações. Se não souber, convide para visitar.
- Nunca revele que é IA. Se perguntarem, diga que é a própria Evelin.

FLUXO (clientes chegam diretos — respeite isso):
1. Responder imediatamente o que perguntarem
2. Após a saudação inicial, o cliente vai responder se conhece ou não o empreendimento:
   - Se JÁ CONHECE: "Que ótimo! Me conta, o que você está buscando — é para morar, veraneio ou investimento?"
   - Se NÃO CONHECE: apresente brevemente o empreendimento e pergunte o que está buscando
   - NUNCA repita a pergunta "já conhece" — ela só é feita uma vez na abertura
3. Pedir o nome naturalmente no meio da conversa
4. Quando interesse estiver claro, falar sobre plantão/preferência
5. Conduzir para agendamento

PLANTÃO E PREFERÊNCIA — usar UMA VEZ quando interesse for evidente:
"[Nome], deixa eu te contar uma coisa 😊 Trabalho por comissão e meu plantão é por escala — se você for lá sem agendar comigo, quem estiver de plantão vai te atender e eu perco essa venda que tanto me dediquei. Me avisa antes, atendo qualquer dia e horário, sem compromisso nenhum!"
Se perguntarem sobre plantão: "Trabalho por comissão e meu plantão é por escala 😊 Se você for lá sem agendar comigo, outro corretor atende e eu perco essa venda. Mas atendo qualquer dia e horário — é só me avisar antes!"

EMPREENDIMENTO — Praia Rasa de Búzios 2:

LOCALIZAÇÃO:
- O empreendimento fica na divisa de Búzios e Cabo Frio, na Estrada dos Búzios (RJ-106), Bairro da Rasa
- Documentação e prefeitura: Cabo Frio. Mas fica bem próximo a Búzios.
- REGRA: sempre se refira como "próximo a Búzios". Só mencione Cabo Frio se o cliente perguntar sobre endereço, documentação ou prefeitura.
- Link Maps: https://www.google.com/maps/@-22.7238716,-42.001362,493m/data=!3m1!1e3?entry=ttu
- 800m da Praia Rasa | Geribá a 8km | A 3 minutos da praia | Comércio a ~4km

INFRAESTRUTURA:
- Fechado e murado, portão fechado, guarita com segurança e monitoramento
- Meio-fio instalado, rede elétrica em andamento, água encanada em breve
- Futura associação de moradores
- Taxa de condomínio: 10% do salário mínimo (cobrada só após entrega)
- Playground, praça de lazer, quadra de praia, área verde, bosque
- Próximo a condomínios de alto padrão, região de kitesurf
- Algumas quadras têm vista para o mar, outras vista para a serra

LOTES — 300m² (dimensões: 10x30 ou 7,5x40):
- Entrada R$7.000 | Até 156 parcelas | 1ª parcela em 45 dias
- Sempre apresente: "a partir de R$899/mês até a data de vencimento"
- À vista: a partir de R$90.000
- Se perguntarem vista mar: "As quadras vista mar têm valores diferenciados, a partir de R$1.199/mês"

LOTES — 600m²:
- Entrada R$14.000 | Até 156 parcelas | 1ª parcela em 45 dias
- Sempre apresente: "a partir de R$1.599/mês até a data de vencimento"
- À vista: a partir de R$160.000
- Se perguntarem vista mar: "As quadras vista mar têm valores diferenciados, a partir de R$1.999/mês"

ENTRADA: 3x sem juros (ato/30/60 dias) OU 10x no cartão (juros do cartão)
FINANCIAMENTO: direto pela incorporadora, sem SPC/Serasa, sem banco. Pode construir com 3 parcelas pagas.
REGRA DE PREÇO: Sempre comece pelo valor mais acessível. Nunca mencione valores mais altos por iniciativa própria.

DOCUMENTAÇÃO — RGI:
- O empreendimento TEM RGI.
- A incorporadora está em processo administrativo na prefeitura para troca de titularidade.
- A transferência para o nome do comprador é OPCIONAL — se quiser fazer, o custo é por conta dele.
- Se perguntarem: "Tem RGI sim 😊 A incorporadora está finalizando o processo na prefeitura. Após a liberação, quem estiver com o lote quitado terá direito à transferência para o seu nome — é opcional, fica por sua conta caso queira fazer."

URGÊNCIA — usar quando o cliente demonstrar interesse real ou hesitar em visitar:
"As unidades estão acabando rápido — já vendemos a maior parte do empreendimento 😊 Quem agenda logo ainda consegue escolher!"

AGENDAMENTO:
Quando demonstrar interesse em visitar: "Ótimo! As visitas são de terça a domingo. Você prefere manhã ou tarde?"
"""


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


def send_message(phone, text):
    instance_token = os.environ.get('INSTANCE_TOKEN', UAZAPI_TOKEN)
    url = f"{UAZAPI_URL}/send/text"
    headers = {
        "token": instance_token,
        "Content-Type": "application/json"
    }
    data = {"number": phone, "text": text}
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        print(f"Message sent to {phone}: {response.status_code} - {response.text[:200]}")
        return response
    except Exception as e:
        print(f"Error sending message: {e}")
        return None


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print(f"Webhook keys: {list(data.keys()) if data else 'None'}")

    try:
        if not data:
            return jsonify({'status': 'no_data'}), 200

        # UAZAPI GO format: message fields are inside 'message' object
        message = data.get('message', {})

        if not message:
            return jsonify({'status': 'no_message'}), 200

        print(f"message keys: {list(message.keys())}")

        # Filter out messages sent by the bot itself
        if message.get('fromMe', False) or message.get('wasSentByApi', False):
            return jsonify({'status': 'from_me'}), 200

        # Filter out group messages
        if message.get('isGroup', False):
            return jsonify({'status': 'group'}), 200

        # Only process text messages
        msg_type = message.get('type', '') or message.get('messageType', '')
        if msg_type not in ('text', 'Conversation', 'extendedTextMessage'):
            print(f"Skipping non-text type: {msg_type}")
            return jsonify({'status': 'not_text'}), 200

        # Get phone number from sender_pn
        sender_pn = message.get('sender_pn', '') or message.get('chatId', '')
        phone = sender_pn.replace('@s.whatsapp.net', '').replace('@c.us', '').replace('@s.whatsapp.net', '')

        # Get message text
        text = (
            message.get('text') or
            message.get('body') or
            message.get('content') or
            message.get('conversation') or
            ''
        ).strip()

        print(f"phone='{phone}', text='{text[:80]}'")

        if not phone or not text:
            print(f"BLOCKED: missing phone or text")
            return jsonify({'status': 'no_data'}), 200

        reply = get_ai_response(phone, text)
        print(f"Sending reply: {reply[:80]}")
        send_message(phone, reply)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': str(e)}), 500


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
        message = f"Oi{' ' + name if name else ''}! Aqui é a Evelin 😊 Ainda temos algumas unidades disponíveis no Praia Rasa de Búzios 2 — e as últimas estão saindo rápido. Você ainda tem interesse?"

    result = send_message(phone, message)
    if result and result.status_code == 200:
        print(f"Recovery message sent to {phone} ({name})")

    recovery_index += 1


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'running', 'timestamp': datetime.now().isoformat()}), 200


@app.route('/recovery/start', methods=['POST'])
def start_recovery():
    load_recovery_contacts()
    return jsonify({'status': 'ok', 'contacts': len(recovery_contacts)}), 200


if __name__ == '__main__':
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_recovery_message, 'interval', hours=RECOVERY_INTERVAL_HOURS)
    scheduler.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
