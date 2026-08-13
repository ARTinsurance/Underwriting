window.OUTLOOK_ORIGINATION_CONFIG = {
  // Microsoft Entra application (client) ID. Configure Mail.Read delegated permission.
  clientId: "00000000-0000-0000-0000-000000000000",
  // Oldest matching email opens this workflow. Supported placeholders are listed in README.md.
  brokerExtensionUrlTemplate: "https://localhost:8000/?imo={imo}&broker={broker}&subject={subject}&messageId={messageId}",
  maxMessages: 250
};
