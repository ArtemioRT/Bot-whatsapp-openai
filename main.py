import json
from dotenv import load_dotenv
import os
import requests
from openai import OpenAI
from flask import Flask, request, Response
import logging
import tiktoken

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERSION = os.getenv("VERSION")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Constants
MODEL = "gpt-4o"
MAX_TOKENS = 8192  # Maximum context window for GPT-4, used for token counting
SYSTEM_PROMPT = """"""

app = Flask(__name__)

# Store conversation history
conversation_history = {}

def count_tokens(text):
    encoding = tiktoken.encoding_for_model(MODEL)
    return len(encoding.encode(text))

def send_whatsapp_message(recipient, message):
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json",
    } 
    data = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "text",
        "text": {"body": message}
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Message sent successfully: {response.json()}")
        return response
    except requests.RequestException as e:
        logger.error(f"Error sending message: {e}")
        return None

def generate_openai_response(prompt, conversation_history):
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *conversation_history,
            {"role": "user", "content": prompt}
        ]
        
        total_tokens = sum(count_tokens(msg["content"]) for msg in messages)
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages
        )
        
        ai_response = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        tokens_remaining = MAX_TOKENS - tokens_used
        
        return ai_response, tokens_used, tokens_remaining
    except Exception as e:
        logger.error(f"Error generating OpenAI response: {e}")
        return "Lo siento, hubo un problema al generar una respuesta. ¿Puedes intentarlo de nuevo? 🤖", 0, MAX_TOKENS

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode and token:
        if mode == 'subscribe' and token == VERIFY_TOKEN:
            logger.info("Webhook verified")
            return challenge, 200
        else:
            return 'Forbidden', 403
    return 'Bad Request', 400

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logger.info(f"Received webhook data: {data}")

    if data['object'] == 'whatsapp_business_account':
        try:
            for entry in data['entry']:
                for change in entry['changes']:
                    if change['field'] == 'messages':
                        for message in change['value'].get('messages', []):
                            if message['type'] == 'text':
                                sender = message['from']
                                text = message['text']['body']
                                logger.info(f"Received message from {sender}: {text}")
                                
                                if text.lower() == "reiniciar":
                                    conversation_history[sender] = []
                                    send_whatsapp_message(sender, "Hola soy tu asistente virtual. Nuestra conversación ha sido reiniciada. ¿En qué puedo ayudarte hoy? ")
                                    continue
                                
                                if sender not in conversation_history:
                                    conversation_history[sender] = []
                                    send_whatsapp_message(sender, "¿En qué puedo ayudarte hoy?")
                                    continue
                                
                                # Generate response using OpenAI
                                ai_response, tokens_used, tokens_remaining = generate_openai_response(text, conversation_history[sender])
                                logger.info(f"Generated AI response: {ai_response}")
                                
                                # Update conversation history
                                conversation_history[sender].append({"role": "user", "content": text})
                                conversation_history[sender].append({"role": "assistant", "content": ai_response})
                                
                                # Limit conversation history to last 10 messages
                                conversation_history[sender] = conversation_history[sender][-10:]
                                
                                # Prepare the full response with token information
                                full_response = f"{ai_response}\n\n[Tokens usados: {tokens_used} | Tokens restantes: {tokens_remaining}]"
                                
                                # Send the AI-generated response back to WhatsApp
                                send_result = send_whatsapp_message(sender, full_response)
                                if send_result:
                                    logger.info(f"Response sent to {sender}")
                                else:
                                    logger.error(f"Failed to send response to {sender}")
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
    
    return Response(status=200)

if __name__ == "__main__":
    logging.info("Flask app started")
    app.run(host="0.0.0.0", port=8000)
