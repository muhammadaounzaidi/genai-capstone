# Quick Start Guide

## 🚀 Fast Setup (5 minutes)

### 1. Create Discord Bot (2 min)
1. Go to https://discord.com/developers/applications/
2. Click "New Application" → Name it → Create
3. Go to "Bot" → "Add Bot" → Enable **MESSAGE CONTENT INTENT**
4. Copy the bot token

### 2. Invite Bot to Server (1 min)
1. Go to "OAuth2" → "URL Generator"
2. Select scopes: `bot`
3. Select permissions: `Send Messages`, `Read Message History`
4. Copy URL → Open in browser → Select server → Authorize

### 3. Configure .env (1 min)
Create `.env` file:
```env
DISCORD_BOT_TOKEN=your_token_here
GOOGLE_API_KEY=your_google_api_key
GOOGLE_SHEETS_ID=your_sheet_id
GOOGLE_CREDENTIALS_FILE=path/to/service-account.json
```

### 4. Validate & Run (1 min)
```bash
# Validate configuration
python validate_env.py

# Install dependencies (if needed)
pip install -r requirements.txt

# Run the bot
python main.py
```

### 5. Test It! 🧪
1. DM your bot: `"Hi, I need grooming for my dog"`
2. Provide your name: `"My name is John"`
3. Provide phone: `"555-1234"`
4. Provide pet info: `"Golden Retriever, 3 years old, 25 lbs, long coat"`
5. Check Google Sheets - status should be "qualified" ✅

## 📋 What Gets Collected

**Required:**
- ✅ User name
- ✅ Phone number

**Optional (but collected):**
- 🐕 Pet breed
- ⚖️ Pet weight
- 🎂 Pet age
- 🎨 Pet coat type

## 🔍 Verify It Works

Check your Google Sheets "Leads" worksheet:
- Status = "qualified"
- Name, phone, and pet details are filled in

## ❓ Need Help?

See `TESTING_GUIDE.md` for detailed instructions and troubleshooting.

