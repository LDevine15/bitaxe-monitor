# Quick Guide: Get Your #swarm Channel ID

## Step 1: Enable Developer Mode

1. Open Discord (desktop or web)
2. Click the **⚙️ gear icon** (User Settings) at bottom left
3. Go to **App Settings** → **Advanced**
4. Toggle **Developer Mode** to ON
5. Close settings

## Step 2: Get #swarm Channel ID

1. Go to your Discord server (the one from invite link: https://discord.gg/bneaFHwT)
2. Find the **#swarm** channel in the channel list
   - If it doesn't exist, create it: Right-click server → Create Channel → Name it "swarm"
3. **Right-click** on **#swarm** channel name
4. Click **"Copy Channel ID"**
5. Paste it somewhere - you'll need it for config.yaml

## Step 3: Update config.yaml

```yaml
discord:
  auto_report:
    enabled: true
    channel_name: "swarm"              # Just for reference
    channel_id: PASTE_YOUR_ID_HERE     # ← Paste the ID you copied
    schedule: "0 * * * *"
```

---

## What the Channel ID Looks Like

✅ **Correct**: `1234567890123456789` (18-19 digit number)
❌ **Wrong**: `https://discord.gg/bneaFHwT` (this is an invite link, not a channel ID)
❌ **Wrong**: `#swarm` (this is the channel name, not the ID)

---

## Troubleshooting

**"I don't see 'Copy Channel ID' option"**
- Make sure Developer Mode is enabled (Step 1)
- Try restarting Discord

**"I don't have a #swarm channel"**
1. Right-click your server name
2. Click "Create Channel"
3. Name it "swarm"
4. Click "Create Channel"
5. Now right-click the new #swarm channel → Copy Channel ID

**"The bot still can't post"**
- Make sure the bot has "Send Messages" permission in #swarm
- Right-click #swarm → Edit Channel → Permissions → Check bot role permissions

---

## Quick Test

Once you have the channel ID in config.yaml:

```bash
python discord_bot.py
```

The bot should say:
```
[INFO] Auto-report channel: #swarm (1234567890123456789)
```

Then in Discord, type:
```
!status
```

If the bot responds, you're all set! 🎉
