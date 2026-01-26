# Testing Guide: Lead Qualification Bot

This guide will help you set up a Discord server and test the lead qualification functionality.

## Prerequisites

1. **Discord Account** - You'll need a Discord account
2. **Google Cloud Project** - For Google Sheets API access
3. **Python 3.8+** - Installed on your system

## Step 1: Create a Discord Bot Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications/)
2. Click **"New Application"** button
3. Give your application a name (e.g., "Pet Grooming Bot")
4. Click **"Create"**

## Step 2: Create a Bot User

1. In your application, go to the **"Bot"** section in the left sidebar
2. Click **"Add Bot"** and confirm
3. Under **"Privileged Gateway Intents"**, enable:
   - ✅ **MESSAGE CONTENT INTENT** (Required for reading messages)
4. Under **"Token"**, click **"Reset Token"** or **"Copy"** to get your bot token
   - ⚠️ **Save this token** - you'll need it for your `.env` file

## Step 3: Set Up Your Discord Server

1. Open Discord and create a new server (or use an existing one)
2. Go back to the [Discord Developer Portal](https://discord.com/developers/applications/)
3. Select your application
4. Go to **"OAuth2"** → **"URL Generator"**
5. Under **"Scopes"**, select:
   - ✅ `bot`
   - ✅ `applications.commands` (optional, for slash commands)
6. Under **"Bot Permissions"**, select:
   - ✅ `Send Messages`
   - ✅ `Read Message History`
   - ✅ `View Channels`
7. Copy the generated URL at the bottom
8. Open the URL in your browser
9. Select your server and click **"Authorize"**
10. Complete the CAPTCHA if prompted

## Step 4: Configure Environment Variables

1. Create a `.env` file in the project root (if it doesn't exist)
2. Add the following variables:

```env
# Discord Bot Configuration
DISCORD_BOT_TOKEN=your_discord_bot_token_here

# Google API Configuration
GOOGLE_API_KEY=your_google_api_key_here
GOOGLE_SHEETS_ID=your_google_sheets_id_here

# Google Sheets Authentication (choose one method)
# Option 1: Use a service account JSON file
GOOGLE_CREDENTIALS_FILE=path/to/your/service-account-credentials.json

# Option 2: Or use JSON string directly (not recommended)
# GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

### Getting Your Google API Key

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the **Google Sheets API** and **Generative AI API**
4. Go to **"APIs & Services"** → **"Credentials"**
5. Create an **API Key** for Generative AI
6. Create a **Service Account** for Google Sheets:
   - Go to **"IAM & Admin"** → **"Service Accounts"**
   - Click **"Create Service Account"**
   - Download the JSON key file
   - Share your Google Sheet with the service account email

### Getting Your Google Sheets ID

1. Create a new Google Sheet or open an existing one
2. The Sheet ID is in the URL: `https://docs.google.com/spreadsheets/d/SHEET_ID_HERE/edit`
3. Copy the `SHEET_ID_HERE` part

## Step 5: Validate Configuration

Run the validation script to check your setup:

```bash
python validate_env.py
```

This will verify:
- ✅ All required environment variables are set
- ✅ Google Sheets authentication is configured correctly
- ✅ Service account JSON is valid

## Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

## Step 7: Run the Bot

```bash
python main.py
```

You should see:
```
INFO - BotName#1234 has connected to Discord!
```

## Step 8: Test Lead Qualification

### Test Scenario 1: Direct Message (DM)

1. In Discord, find your bot in the server member list
2. Right-click on the bot and select **"Message"**
3. Send a message like: `"Hi, I need grooming services for my dog"`

The bot should:
- ✅ Create a lead in Google Sheets with status "initiated"
- ✅ Respond with a greeting
- ✅ Start collecting qualification information

### Test Scenario 2: Collecting Qualification Details

Continue the conversation by providing information:

**User:** "Hi, I need grooming services for my dog"

**Bot:** (Should ask for your name)

**User:** "My name is John Smith"

**Bot:** (Should ask for phone number)

**User:** "My phone is 555-1234"

**Bot:** (Should ask about pet details)

**User:** "I have a Golden Retriever, he's 3 years old, weighs about 25 pounds, and has a long coat"

**Bot:** (Should confirm and update lead status to "qualified")

### Verify in Google Sheets

1. Open your Google Sheet
2. Check the **"Leads"** worksheet
3. You should see:
   - A new row with your user_id and username
   - Status should be "qualified" (after providing name and phone)
   - Columns should be populated:
     - `name`: John Smith
     - `phone`: 555-1234
     - `pet_breed`: Golden Retriever
     - `pet_weight`: 25 pounds
     - `pet_age`: 3 years old
     - `pet_coat`: long

## Troubleshooting

### Bot doesn't respond to messages

1. **Check bot permissions**: Make sure the bot has "Send Messages" permission
2. **Check intents**: Verify "MESSAGE CONTENT INTENT" is enabled in Discord Developer Portal
3. **Check bot is online**: Look for green dot next to bot name in Discord

### "Privileged intents" error

- Go to Discord Developer Portal → Your Application → Bot
- Enable **"MESSAGE CONTENT INTENT"** under Privileged Gateway Intents
- Restart the bot

### Google Sheets errors

1. **"Permission denied"**: Share your Google Sheet with the service account email
2. **"Worksheet not found"**: The bot will create the "Leads" worksheet automatically
3. **"Invalid credentials"**: Check your `GOOGLE_CREDENTIALS_FILE` path and JSON validity

### Lead not being qualified

1. **Check logs**: Look for error messages in the console
2. **Verify information**: Make sure you provided both name and phone number
3. **Check Google Sheets**: Verify the lead was created and check the status column

## Testing Checklist

- [ ] Bot connects to Discord successfully
- [ ] Bot responds to DMs
- [ ] Lead is created in Google Sheets when first message is sent
- [ ] Bot collects user name and phone number
- [ ] Bot collects pet details (breed, weight, age, coat)
- [ ] Lead status updates to "qualified" in Google Sheets
- [ ] All qualification fields are populated correctly in the sheet

## Next Steps

After testing lead qualification, you can:
- Test service selection functionality
- Test appointment booking
- Add more conversation flows
- Customize the system prompt for your business needs

