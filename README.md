# Teste — Telegram Source Analyzer

Independent, read-only analyzer for auditing Telegram sources and classifying the exact video/link patterns required by the project.

## Sources

Configured locally through `credentials/project.env`:

- SOURCE_1 = `-1003788989075`
- SOURCE_2 = `-1002698134896`
- SOURCE_3 = `-1002039708059`

## Patterns

The analyzer distinguishes these five patterns, preserving message order:

1. **video + link** — video and Shopee link in the same message.
2. **video → link** — standalone video followed immediately by a standalone link message.
3. **video + image + link** — grouped media in the exact order video, image, then the Shopee link.
4. **image + image + video + link** — grouped media in the exact order image, image, video, then the Shopee link.
5. **link + video** — standalone Shopee link immediately followed by a standalone video.

For grouped patterns, the link may be in the final media message or in the immediately following standalone link message. A link appearing earlier in the group is not accepted.

## First run

From the repository root:

```powershell
python -m pip install -r requirements.txt
python .\scripts\check_config.py
python .\scripts\scan_sources.py
```

On the first run, Telethon may ask for the Telegram account phone number, login code and 2FA password if enabled. The resulting user session is stored locally under:

```text
credentials/telegram/source_analyzer.session
```

That session is ignored by Git.

## Reports

The scanner creates locally:

- `reports/pattern_summary.json` — counts per source and total.
- `reports/pattern_evidence.jsonl` — one JSON evidence record per detected case.
- `reports/pattern_evidence.csv` — spreadsheet-friendly evidence.

Each evidence record contains source ID, pattern, message IDs, grouped IDs, URLs, composition, message dates and media types.

## Safety / scope

This phase is **read-only**.

It does not:

- download videos;
- publish or forward messages;
- edit messages;
- delete messages;
- create Telegram queues;
- modify the Telegram sources.

The purpose of this phase is to establish real historical evidence before any downloader is designed.

`credentials/project.env`, Telegram session files and generated reports are intentionally excluded from Git.
