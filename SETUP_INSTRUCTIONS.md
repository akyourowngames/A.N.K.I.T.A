# J.A.R.V.I.S Setup Instructions

## Current Status

✅ Sarvam TTS integrated and configured  
✅ Frontend configured with backend  
✅ All services initialized successfully  
⚠️ **ACTION REQUIRED**: Add Groq API keys

## Required: Add Groq API Keys

The system needs valid Groq API keys to function. Currently, the keys in `.env` are empty.

### Steps to Add API Keys:

1. **Get Groq API Keys:**
   - Visit: https://console.groq.com/keys
   - Sign up or log in
   - Create one or more API keys

2. **Add Keys to `.env` file:**
   - Open `Newai/.env`
   - Replace the empty values with your real keys:
   
   ```env
   GROQ_API_KEY=gsk_your_actual_key_here
   GROQ_API_KEY_2=gsk_your_second_key_here  # Optional
   GROQ_API_KEY_3=gsk_your_third_key_here   # Optional
   ```

3. **Restart the server:**
   - Stop the current server (Ctrl+C)
   - Run: `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

## Voice Input (Speech Recognition)

### Current Configuration:
- Uses Web Speech API (built into Chrome/Edge)
- Works best on PC with Chrome or Edge browsers
- Auto-restart mode: mic stays on after each response

### If Voice Input Not Working:

1. **Check Browser Permissions:**
   - Click the microphone icon in the address bar
   - Allow microphone access
   - Refresh the page

2. **Browser Compatibility:**
   - ✅ Best: Chrome, Edge (PC)
   - ⚠️ Limited: Safari (Mac/iOS)
   - ❌ Not supported: Firefox

3. **Test Voice Input:**
   - Click the microphone button (bottom right)
   - Speak clearly
   - You should see your words appear in real-time
   - Message sends automatically after you stop speaking

### Voice Input Flow:
1. Click mic button → starts listening
2. Speak your message → see transcript in real-time
3. Stop speaking → brief pause → message sends automatically
4. AI responds (text + voice)
5. After AI finishes → mic automatically restarts (auto-listen mode)
6. Click mic again to turn off auto-listen

## TTS (Text-to-Speech)

### Current Configuration:
- ✅ Sarvam TTS integrated
- ✅ Voice: Shubh (Indian English)
- ✅ Auto-enabled for all responses
- ✅ API Key configured

### TTS Features:
- Automatic speech for every AI response
- Streaming audio (starts playing before full response complete)
- Visual orb animation during speech
- Toggle on/off with speaker button (bottom right)

## Troubleshooting

### "Something went wrong" Error:
- **Cause**: Invalid or missing Groq API keys
- **Fix**: Add valid keys to `.env` and restart server

### Voice Not Capturing:
- **Cause**: Browser permissions or unsupported browser
- **Fix**: 
  1. Use Chrome or Edge
  2. Allow microphone access
  3. Check system microphone settings

### No Audio Output:
- **Cause**: Sarvam API issue or network problem
- **Fix**: Check server logs for TTS errors

### 404 Errors for Audio Files:
- **Cause**: Missing thinking sound files (optional feature)
- **Impact**: None - system works without them
- **Fix**: Ignore or disable thinking sounds in settings

## Server Access

- **Frontend**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

## Features

### Chat Modes:
1. **Jarvis Mode** (Default): AI decides whether to use web search
2. **General Mode**: Pure LLM, no web search
3. **Realtime Mode**: Always uses Tavily web search

### Voice Features:
- Speech-to-text (Web Speech API)
- Text-to-speech (Sarvam TTS)
- Auto-listen mode
- Real-time transcript display

### UI Features:
- Activity panel (left): Shows AI decision flow
- Search results panel (right): Shows web search results
- Animated orb: Visual feedback during speech
- Settings panel: Configure auto-open behaviors

## Next Steps

1. ✅ Add Groq API keys to `.env`
2. ✅ Restart the server
3. ✅ Test voice input (click mic button)
4. ✅ Test chat (type or speak a message)
5. ✅ Verify TTS is working (should hear responses)

## Support

If you encounter issues:
1. Check server logs for error messages
2. Verify all API keys are valid
3. Test in Chrome/Edge browser
4. Check microphone permissions
5. Ensure internet connection is stable
