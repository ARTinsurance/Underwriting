# Outlook origination IMO add-in

This Outlook task-pane add-in searches the signed-in mailbox for a keyword, optionally restricts results to a broker sender, chooses the **oldest** matching message that contains a checksum-valid seven-digit IMO, and opens the configured broker workflow.

## Configure

1. Register a single-page application in Microsoft Entra ID. Add the SPA redirect `brk-multihub://localhost:3000` (replace the host in production) and grant delegated Microsoft Graph `Mail.Read` permission.
2. Copy `config.example.js` to `config.js`, enter the application client ID, and set `brokerExtensionUrlTemplate`. Supported placeholders: `{imo}`, `{broker}`, `{subject}`, `{messageId}`, and `{receivedDateTime}`.
3. Replace every `https://localhost:3000` and `https://localhost:8000` URL in `manifest.xml` for production. Outlook add-ins must be HTTPS-hosted.

## Run locally

```bash
cp config.example.js config.js
npm install
npm run dev
```

Supply valid icon files named `icon-16.png`, `icon-32.png`, `icon-64.png`, `icon-80.png`, and `icon-128.png`, then sideload `manifest.xml` in Outlook. The task pane uses nested app authentication; the first mailbox search can prompt for `Mail.Read` consent.

Run unit tests with `npm test` and create a production bundle with `npm run build`.

## Operational notes

- Mail content is fetched directly from Microsoft Graph in the add-in and is not sent to this repository's web service.
- `maxMessages` limits pagination (default 250, hard cap 1000). “First” means the oldest received matching message within that result window.
- Broker filtering compares the entered text with the sender display name and address.
- A URL is the portable handoff between separately sandboxed Office/browser extensions. Configure the broker extension to accept `imo` from its query string, or point the template at the underwriting workbench included in this repository.
