# 🎉 Hype Bot - Auto Hype for Quiz Announcements

## What Does It Do?

When the quiz admin posts "Ready for this week's quiz!" with an image, the bot automatically posts:
- "Let's gooo! 🔥"
- "LET'S GO! 💪"
- "Ready! Let's goooo! 🚀"
- Or other hype messages (randomly chosen)

## How to Use

### Option 1: Run Hype Bot Only

```bash
cd c:\Users\hp\replay_bot
python hype_bot.py
```

This only posts hype messages, doesn't answer questions.

### Option 2: Run BOTH Bots (Recommended for Saturday)

Open **2 terminals**:

**Terminal 1 (Quiz Answering):**
```bash
cd c:\Users\hp\replay_bot
python bot.py
```

**Terminal 2 (Hype Messages):**
```bash
cd c:\Users\hp\replay_bot
python hype_bot.py
```

## What It Detects

The hype bot triggers when it sees:
- ✅ "ready" in message
- ✅ "starts" or "starting"
- ✅ "begin" or "get ready"
- ✅ "20$" (quiz prize)
- ✅ "quiz time"
- ✅ Any image post with text (likely an announcement)

## Timing

- **Detection:** Instant
- **Reply Delay:** 2-5 seconds (looks natural, not botty)
- **Messages:** Random from 9 different hype phrases

## Example Flow

```
[11:40] ADMIN: "Ready for this week $20 quiz! 🎯" [IMAGE]
         ↓
[11:40] YOU: "Let's gooo! 🔥" (auto-posted by hype bot)
         ↓
[12:00] QUIZ STARTS
         ↓
[12:00] Main bot answers questions in 1-2s
```

## Safety

- ✅ Won't spam (only replies once per announcement)
- ✅ Natural delay (2-5s random wait)
- ✅ Random messages (doesn't look automated)
- ✅ Can react to others' hype with emojis (10% chance)

## Stop the Bot

Press `Ctrl+C` in the terminal.

## Notes

- Hype bot is separate from quiz bot
- You can run both at the same time
- Or just run hype bot before quiz, then switch to main bot when quiz starts
