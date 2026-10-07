# Teste — Telegram Source Analyzer

Independent, read-only analyzer for auditing Telegram sources and classifying video/link patterns.

## Sources

Configured locally through `credentials/project.env`:

- SOURCE_1 = `-1003788989075`
- SOURCE_2 = `-1002698134896`
- SOURCE_3 = `-1002039708059`

## Patterns

The analyzer will distinguish:

1. **video + link** — video and Shopee link in the same message.
2. **video → link** — video message followed by the link in a later message.
3. **video + image + link** — grouped media containing video, image and link.
4. **image + image + video + link** — grouped media containing two images, video and link.
5. **link + video** — link appears before the video.

The order of messages is significant.

## Security

`credentials/project.env` is local-only and ignored by Git. Do not commit Telegram API credentials or session files.

The analyzer is intended to be read-only: it should inspect Telegram history and produce evidence/reports without downloading, publishing, deleting or modifying Telegram messages.
