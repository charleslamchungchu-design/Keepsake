# Keepsake API

FastAPI backend for the Keepsake companion mobile app.

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd my_companion
pip install -r api/requirements.txt
```

### 2. Configure Environment

```bash
# Copy example env file
cp api/.env.example api/.env

# Edit with your credentials
# - OPENAI_API_KEY: Your OpenAI API key
# - SUPABASE_URL: Your Supabase project URL
# - SUPABASE_KEY: Your Supabase service role key
# - SUPABASE_JWT_SECRET: Your Supabase JWT secret
```

### 3. Run the Server

```bash
# From project root
uvicorn api.main:app --reload

# Or run directly
python -m api.main
```

### 4. View API Docs

Open http://localhost:8000/docs for interactive Swagger UI.

---

## 📁 Project Structure

```
api/
├── main.py              # FastAPI app entry point
├── config.py            # Settings & tier configuration
├── models/
│   └── schemas.py       # Pydantic request/response models
├── routes/
│   ├── auth.py          # /auth/* - Registration, login
│   ├── chat.py          # /chat/* - Messaging, streaming
│   ├── user.py          # /user/* - Profile management
│   ├── memory.py        # /memory/* - Facts, sync
│   ├── scenes.py        # /scenes/* - Available scenes
│   └── deps.py          # Auth dependencies
├── services/
│   ├── ai.py            # OpenAI logic, prompts, routing
│   └── memory.py        # Supabase memory operations
├── requirements.txt     # Python dependencies
└── .env.example         # Environment template
```

---

## 🔌 API Endpoints

### Authentication (`/auth`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create new user |
| POST | `/auth/login` | Login, get tokens |
| POST | `/auth/refresh` | Refresh access token |
| POST | `/auth/logout` | Logout (client-side) |

### Chat (`/chat`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/chat/message` | Send message (non-streaming) |
| POST | `/chat/message/stream` | Send message (SSE streaming) |
| POST | `/chat/greeting` | Get session greeting |
| GET | `/chat/history` | Get chat history |

### User (`/user`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/user/profile` | Get profile & stats |
| PUT | `/user/profile` | Update profile |
| POST | `/user/avatar/{id}` | Set avatar/persona |
| GET | `/user/balance` | Get coin balance |
| POST | `/user/spend/{amount}` | Spend coins |

### Memory (`/memory`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/memory/facts` | Get stored facts |
| DELETE | `/memory/facts` | Clear all facts |
| POST | `/memory/sync` | Force cloud sync |
| GET | `/memory/emotional-state` | Get emotional scores |
| GET | `/memory/stats` | Get memory statistics |

### Scenes (`/scenes`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/scenes` | List all scenes |
| GET | `/scenes/{name}` | Get scene details |

---

## 🔐 Authentication

All endpoints except `/auth/*` require a Bearer token:

```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:8000/user/profile
```

Get a token by calling `/auth/login`:

```bash
curl -X POST http://localhost:8000/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "user@example.com", "password": "secret"}'
```

---

## 📡 Streaming (SSE)

The `/chat/message/stream` endpoint returns Server-Sent Events:

```javascript
const eventSource = new EventSource('/chat/message/stream', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    message: "Hello!",
    vibe: 50,
    scene: "Lounge"
  })
});

eventSource.onmessage = (event) => {
  if (event.data === '[DONE]') {
    eventSource.close();
    return;
  }
  // Append chunk to UI
  console.log(event.data);
};
```

---

## 🎯 Tier System

| Tier | Name | Message Limit | Memory | Scenes | RAG |
|------|------|---------------|--------|--------|-----|
| 0 | Free | 15/day | 48 hours | 2 | ❌ |
| 1 | Plus | Unlimited | Permanent | 4 | ✅ |
| 2 | Premium | Unlimited | Permanent | 5 | ✅ |

---

## 🌐 Deployment

### Railway

```bash
# Install Railway CLI
npm i -g @railway/cli

# Login & deploy
railway login
railway init
railway up
```

### Render

1. Connect GitHub repo
2. Set environment variables
3. Build command: `pip install -r api/requirements.txt`
4. Start command: `uvicorn api.main:app --host 0.0.0.0 --port $PORT`

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r api/requirements.txt
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 🔗 FlutterFlow Integration

1. In FlutterFlow, go to **API Calls**
2. Add new API group with base URL: `https://your-api.railway.app`
3. Add header: `Authorization: Bearer [authToken]`
4. Create API calls for each endpoint

Example for `/chat/message`:
- Method: POST
- Body: `{"message": "[userMessage]", "vibe": [vibeValue], "scene": "[currentScene]"}`
- Response: Parse `response`, `emotional_state`, `balance`

---

## 🐛 Troubleshooting

**401 Unauthorized**
- Check your JWT token is valid and not expired
- Verify SUPABASE_JWT_SECRET matches your Supabase project

**500 Internal Server Error**
- Check OPENAI_API_KEY is valid
- Verify Supabase connection with SUPABASE_URL and SUPABASE_KEY

**CORS Errors**
- Update CORS_ORIGINS in .env to include your app domain

---

## 📝 License

Proprietary - Keepsake

