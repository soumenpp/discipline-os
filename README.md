# 🎯 Discipline OS v3

**AI-powered Habit Tracker & Smart Task Manager** with Telegram check-ins, DeepSeek AI, and a web dashboard.

---

## 📖 What is Discipline OS?

Discipline OS is a self-hosted personal productivity system that combines:

- **Habit tracking** — Log daily habits, build consistency
- **Smart task management** — Organize tasks with AI-powered suggestions
- **Telegram bot** — Get reminders and check-ins on your phone
- **Web dashboard** — Clean UI to view your progress
- **AI integration** — DeepSeek analyzes your habits and suggests improvements

Think of it as a **personal discipline coach** that lives on your server.

---

## ✨ Benefits

| Benefit | Why It Matters |
|---------|---------------|
| 🔒 **100% Self-Hosted** | Your data stays on your server — no third-party cloud |
| 🤖 **AI-Powered** | DeepSeek analyzes patterns and gives smart suggestions |
| 📱 **Telegram Integration** | Check in from your phone, get reminders |
| 🧠 **Smart Scheduling** | Scheduler handles automated check-ins |
| 🆓 **Completely Free** | No subscriptions, no limits |
| 🔧 **Customizable** | Full source code — tweak it however you want |
| 🚀 **One-Line Install** | Deploy on any Linux server in seconds |
| 📊 **Web Dashboard** | Visualize your progress in the browser |

---

## 🚀 Installation Guide

### Option 1: One-Line Install (Recommended)

```bash
bash <(curl -sL https://raw.githubusercontent.com/soumenpp/discipline-os/master/setup.sh)
```

### Option 2: Manual Install

```bash
# Clone the repo
git clone https://github.com/soumenpp/discipline-os.git
cd discipline-os

# Make setup executable
chmod +x setup.sh

# Run setup as root
sudo ./setup.sh
```

The setup script will automatically:
1. ✅ Install Python and system dependencies
2. ✅ Create a virtual environment
3. ✅ Install Python packages
4. ✅ Generate a `.env` configuration file
5. ✅ Create a systemd service for auto-start
6. ✅ Start the application on port 5321

---

## 🔑 Configuration — How to Change Keys

After installation, you need to set your API tokens in the `.env` file:

```bash
sudo nano /root/discipline-os/.env
```

The file looks like this:

```env
SECRET_KEY=your-random-64-hex-key
PORT=5321
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
TG_TOKEN=your-telegram-bot-token
```

### What Each Key Does

| Key | Where to Get It | Purpose |
|-----|----------------|---------|
| `SECRET_KEY` | Generate with: `openssl rand -hex 32` | Encrypts user sessions |
| `DEEPSEEK_API_KEY` | [platform.deepseek.com](https://platform.deepseek.com) | Powers AI features |
| `TG_TOKEN` | [@BotFather](https://t.me/BotFather) on Telegram | Telegram bot integration |

### After Changing Keys

Always restart the service after updating tokens:

```bash
sudo systemctl restart discipline-os
```

Check if it's running:

```bash
sudo systemctl status discipline-os
```

---

## 📱 How to Use

### Web Dashboard
Open `http://<YOUR_SERVER_IP>:5321` in your browser.

### Telegram Bot
Send `/start` to your bot on Telegram.

### Commands
- `systemctl status discipline-os` — Check if running
- `journalctl -u discipline-os -f` — View live logs
- `systemctl restart discipline-os` — Restart after config changes

---

## 📤 Deploy Updates

```bash
cd /root/discipline-os
./deploy.sh
```

---

## 🛠️ Project Structure

```
discipline-os/
├── main.py           # Backend server (FastAPI + AI)
├── frontend/         # Web dashboard (HTML/CSS/JS)
├── requirements.txt  # Python dependencies
├── setup.sh          # One-click install script
├── deploy.sh         # Push updates to GitHub
└── .env              # Your keys (never shared)
```

---

Built by **Soumen** 🧠
