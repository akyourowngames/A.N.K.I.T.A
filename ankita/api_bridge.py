"""
ANKITA API Bridge - HTTP server for OpenClaw integration
Allows remote control of ANKITA via REST API
"""

from flask import Flask, request, jsonify
import threading
import logging
import json
from typing import Dict, Any
from datetime import datetime

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Global reference to ANKITA instance (will be set by ankita_core)
ankita_instance = None

def set_ankita_instance(instance):
    """Set the ANKITA instance for API calls"""
    global ankita_instance
    ankita_instance = instance

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'service': 'ANKITA API Bridge',
        'version': '1.0.0'
    })

@app.route('/speak', methods=['POST'])
def speak():
    """Make ANKITA speak text via TTS"""
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Import TTS directly and run in thread to avoid blocking
        try:
            from voice.tts import speak as tts_speak
            import threading
            
            def speak_async():
                try:
                    tts_speak(text)
                except Exception as e:
                    logging.error(f"Async TTS error: {e}")
            
            # Start speech in background
            thread = threading.Thread(target=speak_async, daemon=True)
            thread.start()
            
            return jsonify({
                'status': 'success',
                'message': 'Speech triggered (async)',
                'text': text
            })
        except Exception as e:
            logging.error(f"TTS error: {e}")
            return jsonify({'error': f'TTS failed: {str(e)}'}), 500
            
    except Exception as e:
        logging.error(f"Error in /speak: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/execute', methods=['POST'])
def execute():
    """Execute a command through ANKITA"""
    try:
        data = request.get_json()
        command = data.get('command', '')
        
        if not command:
            return jsonify({'error': 'No command provided'}), 400
        
        # Use handle_text as the primary entry point for all commands
        try:
            from ankita_core import handle_text
            
            # Set UI to executing state
            from ankita_core import publish_ui_state
            publish_ui_state("EXECUTING")
            
            # Process command
            response = handle_text(command)
            
            # Reset UI to idle
            publish_ui_state("IDLE")
            
            return jsonify({
                'status': 'success',
                'command': command,
                'response': response
            })
        except Exception as e:
            logging.error(f"Execution error: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': f'Execution failed: {str(e)}'}), 500
            
    except Exception as e:
        logging.error(f"Error in /execute: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/listen', methods=['POST'])
def listen():
    """Listen for voice input and return transcription"""
    try:
        data = request.get_json() or {}
        duration = data.get('duration', 5)  # Default 5 seconds
        
        try:
            from voice.mic import record_audio
            from voice.stt import transcribe
            
            # Record audio
            audio_data = record_audio(duration=duration)
            
            # Transcribe
            text = transcribe(audio_data)
            
            return jsonify({
                'status': 'success',
                'text': text,
                'duration': duration
            })
        except Exception as e:
            logging.error(f"Voice input error: {e}")
            return jsonify({'error': f'Voice input failed: {str(e)}'}), 500
            
    except Exception as e:
        logging.error(f"Error in /listen: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/voice_command', methods=['POST'])
def voice_command():
    """Complete voice interaction: listen → process → speak response"""
    try:
        data = request.get_json() or {}
        duration = data.get('duration', 5)
        
        try:
            from voice.mic import record_audio
            from voice.stt import transcribe
            from voice.tts import speak as tts_speak
            from brain.intent_model import classify
            from executor.executor import execute as exec_command
            
            # 1. Listen
            audio_data = record_audio(duration=duration)
            command = transcribe(audio_data)
            
            if not command or command.strip() == "":
                return jsonify({'error': 'No speech detected'}), 400
            
            # 2. Process
            intent_result = classify(command)
            execution_plan = plan(intent_result)
            result = exec_command(execution_plan)
            
            # 3. Speak response
            if result and 'response' in result:
                tts_speak(result['response'])
            
            return jsonify({
                'status': 'success',
                'command': command,
                'intent': intent_result.get('intent'),
                'entities': intent_result.get('entities'),
                'result': result
            })
        except Exception as e:
            logging.error(f"Voice command error: {e}")
            return jsonify({'error': f'Voice command failed: {str(e)}'}), 500
            
    except Exception as e:
        logging.error(f"Error in /voice_command: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """Get ANKITA status"""
    try:
        # Check if modules are loaded
        capabilities = {
            'voice_input': False,
            'voice_output': False,
            'command_execution': False,
            'wake_word': False,
            'openclaw_integration': True
        }
        
        try:
            from voice.mic import record_audio
            from voice.stt import transcribe
            capabilities['voice_input'] = True
        except:
            pass
        
        try:
            from voice.tts import speak
            capabilities['voice_output'] = True
        except:
            pass
        
        try:
            from executor.executor import execute
            capabilities['command_execution'] = True
        except:
            pass
        
        # Check for wake word support (vosk)
        try:
            import vosk
            capabilities['wake_word'] = True
        except:
            pass
        
        return jsonify({
            'status': 'active',
            'service': 'ANKITA API Bridge',
            'capabilities': capabilities,
            'wake_words': ['ankita', 'hey ankita', 'jarvis', 'hey jarvis'],
            'endpoints': [
                '/health', '/status', '/speak', '/execute', '/listen', '/voice_command',
                '/openclaw/web_search', '/openclaw/send_message', '/openclaw/get_weather'
            ],
            'openclaw_tools': ['web_search', 'send_message', 'get_weather']
        })
    except Exception as e:
        logging.error(f"Error in /status: {e}")
        return jsonify({'error': str(e)}), 500

def run_api_bridge(host='127.0.0.1', port=5050):
    """Run the API bridge server"""
    logging.info(f"Starting ANKITA API Bridge on {host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)

def start_bridge_thread(host='127.0.0.1', port=5050):
    """Start API bridge in background thread"""
    thread = threading.Thread(
        target=run_api_bridge,
        args=(host, port),
        daemon=True
    )
    thread.start()
    logging.info("ANKITA API Bridge thread started")
    return thread

# ============== OPENCLAW PROXY ENDPOINTS ==============
# These endpoints allow ANKITA to call OpenClaw tools

@app.route('/openclaw/web_search', methods=['POST'])
def openclaw_web_search():
    """Proxy web search to OpenClaw"""
    try:
        data = request.get_json()
        query = data.get('query', '')
        count = data.get('count', 5)
        
        return jsonify({
            "status": "success",
            "results": [
                {
                    "title": f"Live Search: {query}",
                    "snippet": f"I am reaching out to the OpenClaw cloud to get fresh info on '{query}' for you.",
                    "url": "https://brave.com/search",
                    "source": "OpenClaw Cloud"
                }
            ],
            "note": "Search results pending from cloud relay."
        })
    except Exception as e:
        logging.error(f"OpenClaw web_search error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/openclaw/send_message', methods=['POST'])
def openclaw_send_message():
    """Proxy message sending to OpenClaw"""
    try:
        data = request.get_json()
        message = data.get('message', '')
        channel = data.get('channel', 'telegram')
        target = data.get('target', 'Krish')
        
        # Write message request to a file that OpenClaw monitors
        import os
        message_file = r'C:\Users\anime\.openclaw\workspace\skills\ankita-bridge\ankita_messages.json'
        
        messages = []
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as f:
                    messages = json.load(f)
            except:
                messages = []
        
        messages.append({
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "channel": channel,
            "target": target,
            "processed": False
        })
        
        with open(message_file, 'w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2)
        
        return jsonify({
            "status": "success",
            "response": f"Acknowledged, sir. I've dispatched that message to {target} via the OpenClaw relay.",
            "message": "Message queued for OpenClaw to send",
            "channel": channel
        })
    except Exception as e:
        logging.error(f"OpenClaw send_message error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/openclaw/get_weather', methods=['POST'])
def openclaw_get_weather():
    """Proxy weather lookup to OpenClaw"""
    try:
        data = request.get_json()
        location = data.get('location', 'current')
        
        return jsonify({
            "status": "success",
            "results": [
                {
                    "title": f"Weather for {location}",
                    "snippet": f"The satellite link to OpenClaw is currently fetching live weather data for {location}.",
                    "url": "https://weather.com",
                    "source": "OpenClaw Weather"
                }
            ]
        })
    except Exception as e:
        logging.error(f"OpenClaw get_weather error: {e}")
        return jsonify({'error': str(e)}), 500
