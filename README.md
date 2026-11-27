# Setup Guard

A free robot that lives on GitHub. Every 5 minutes it checks your markets
against your Varis checklist and messages you on **Telegram** (with a chart)
and **WhatsApp** (short text) when a setup moves forward or is READY.

Your laptop can be off. You only need your phone online to get the message.

It never places trades. It only watches and tells you.

---

## What it checks (your rulebook, in order)

| Step | What the guard looks for | Timeframe |
|---|---|---|
| 1 | Trend: breaks of structure by **body close** (wicks don't count). One break against the trend is treated as a trap. | Daily (4H backup) |
| 2 | The most recent break of structure in the trend direction | Daily / 4H |
| 3 | The order block that caused it, refined to 1H, and its 5 checks: broke structure, swept previous wick, left FVG, sits in the premium/discount of the daily range, liquidity in front | 4H → 1H |
| 4 | Price comes back into the zone | 15m |
| 5 | Liquidity sweep (wick takes a 15m high/low, closes back inside) | 15m |
| 6 | Sweep validated (price takes out the low/high that fed the sweep) | 15m |
| 7 | Failure to swing (pullback can't beat the sweep extreme) | 15m |
| 8 | Change in state of delivery (body close beyond the failed swing's origin) | 15m |
| 9 | Entry block (FVG or order block from the CISD leg) + stop, targets, risk-to-reward, lot size | 15m |

## Messages you get

- 👀 approaching a zone
- 🟡 price is in the zone
- 🟠 CISD done, nearly ready
- 🟢 **READY**: entry, stop loss, tight stop, T1, T2, risk-to-reward, lot size + chart
- 🔵 price reached the entry block
- 🔴 zone or setup broken

Send your Telegram bot the word **status** at any time; within about 5
minutes it replies with every market and which step it is on.

---

## One-time setup (about 15 minutes, all free)

### 1. Telegram bot
1. In Telegram, search **@BotFather**, tap Start, send `/newbot`.
2. Give it any name, then a username ending in `bot` (e.g. `austin_setup_bot`).
3. BotFather sends a long **token**, like `7123456789:AAH...`. Copy it.
4. Open your new bot and press **Start** (it can't message you until you do).
5. Search **@userinfobot**, press Start. It replies with your **Id** (a number). Copy it.

### 2. WhatsApp (CallMeBot, free for personal use)
1. Open https://www.callmebot.com/blog/free-api-whatsapp-messages/ and save the
   phone number shown there to your contacts.
2. Send it this exact WhatsApp message: `I allow callmebot to send me messages`
3. It replies with your **apikey**. (No reply in 2 minutes? Try again after 24 hours.)

### 3. GitHub
1. On github.com, create a new repository named `setup-guard`.
   Choose **Public**: GitHub's scheduled jobs are only free without limits on
   public projects. Your passwords and keys stay hidden in Secrets (next step);
   only the checklist code is public.
2. Upload these files (or let Claude push them for you).
3. Go to **Settings → Secrets and variables → Actions → New repository secret**
   and add these four:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | your Id from @userinfobot |
| `WHATSAPP_PHONE` | your WhatsApp number with country code, e.g. `+2349012345678` |
| `WHATSAPP_APIKEY` | the apikey from CallMeBot |

4. Open the **Actions** tab, enable workflows, click **Setup Guard → Run workflow**.
   Within a few minutes you get a test report on Telegram listing every market.

That's it. It now runs every 5 minutes on its own.

---

## Changing things later

Edit `config.yml` on GitHub (pencil icon):
- `markets`: add or remove markets by name
- `manual_zones`: add your own zones (top, bottom, buy/sell)
- `alerts`: turn each message type on or off
- `account`: balance and risk %

## Good to know
- GitHub runs the schedule "about" every 5 minutes. Busy times can add a few minutes of delay.
- Prices come from Deriv's free public feed. Markets Deriv doesn't offer there
  are listed in the first message and skipped.
- The checklist is turned into exact rules a computer can follow. Some calls a
  human makes by eye (a "clean" zone, a "real" impulse) are approximated, so
  always confirm on your chart before acting.
- On a $100 account, gold's smallest lot usually risks far more than 2%; the
  READY message warns you when that happens.
