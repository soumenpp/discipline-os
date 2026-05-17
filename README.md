# Discipline OS v3 🎯

AI-powered habit tracker & task manager with Telegram check-ins.

## 🚀 Quick Start (Fresh Server)

**One-line install:**
```bash
bash <(curl -sL https://raw.githubusercontent.com/soumenpp/discipline-os/master/setup.sh)
```

Or clone + run:
```bash
git clone https://github.com/soumenpp/discipline-os.git
cd discipline-os
chmod +x setup.sh
sudo ./setup.sh
```

The setup script will:
- Install Python + system deps
- Create a virtual environment
- Generate an `.env` file for you to fill in
- Create & start the systemd service

## 🔧 Configuration

Edit `.env` with your tokens:

```bash
nano .env
```

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Random 64-char hex string |
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `TG_TOKEN` | Telegram bot token |
| `PORT` | Web server port (default: 5321) |

## 📤 Deploy Updates

```bash
./deploy.sh
```

## 📋 Commands

- `systemctl status discipline-os` — Check status
- `journalctl -u discipline-os -f` — Watch logs
- `systemctl restart discipline-os` — Restart

## 🌐 Access

Dashboard: `http://<YOUR_SERVER_IP>:5321`

---

Built by Soumen 🧠
