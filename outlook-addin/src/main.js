import { createNestablePublicClientApplication, InteractionRequiredAuthError } from "@azure/msal-browser";
import { chooseFirstOrigination, graphSearchUrl, renderBrokerUrl } from "./core.js";

const config = window.OUTLOOK_ORIGINATION_CONFIG || {};
let msalApp;

function status(message, type = "") {
  const element = document.getElementById("status");
  element.textContent = message;
  element.className = type;
}

async function initializeAuth() {
  if (!config.clientId || /^0{8}-/.test(config.clientId)) throw new Error("Set the Entra clientId in config.js first.");
  msalApp = await createNestablePublicClientApplication({ auth: { clientId: config.clientId, authority: "https://login.microsoftonline.com/common" }, cache: { cacheLocation: "localStorage" } });
}

async function getToken() {
  if (!msalApp) await initializeAuth();
  const request = { scopes: ["Mail.Read"], account: msalApp.getActiveAccount() || msalApp.getAllAccounts()[0] };
  try {
    const response = request.account ? await msalApp.acquireTokenSilent(request) : await msalApp.acquireTokenPopup(request);
    if (response.account) msalApp.setActiveAccount(response.account);
    return response.accessToken;
  } catch (error) {
    if (!(error instanceof InteractionRequiredAuthError)) throw error;
    const response = await msalApp.acquireTokenPopup(request);
    if (response.account) msalApp.setActiveAccount(response.account);
    return response.accessToken;
  }
}

async function searchMessages(token, keyword) {
  let next = graphSearchUrl(keyword);
  const messages = [];
  const limit = Math.min(Math.max(Number(config.maxMessages) || 250, 1), 1000);
  while (next && messages.length < limit) {
    const response = await fetch(next, { headers: { Authorization: `Bearer ${token}`, ConsistencyLevel: "eventual", Prefer: 'outlook.body-content-type="text"' } });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.error?.message || `Outlook search failed (${response.status}).`);
    }
    const page = await response.json();
    messages.push(...(page.value || []));
    next = page["@odata.nextLink"];
  }
  return messages.slice(0, limit);
}

function showResult(message) {
  const sender = message.sender?.emailAddress || {};
  document.getElementById("result-imo").textContent = message.imos[0];
  document.getElementById("result-broker").textContent = sender.name || sender.address || "Unknown";
  document.getElementById("result-date").textContent = new Date(message.receivedDateTime).toLocaleString();
  document.getElementById("result-subject").textContent = message.subject || "(no subject)";
  document.getElementById("result").hidden = false;
}

Office.onReady(() => {
  document.getElementById("search-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("run");
    const keyword = document.getElementById("keyword").value.trim();
    const broker = document.getElementById("broker").value.trim();
    button.disabled = true;
    document.getElementById("result").hidden = true;
    try {
      status("Signing in and searching Outlook…");
      const messages = await searchMessages(await getToken(), keyword);
      const match = chooseFirstOrigination(messages, broker);
      if (!match) throw new Error(`No matching email with a valid IMO was found in the first ${messages.length} Outlook results.`);
      showResult(match);
      const sender = match.sender?.emailAddress || {};
      const url = renderBrokerUrl(config.brokerExtensionUrlTemplate, {
        imo: match.imos[0], broker: sender.name || sender.address, subject: match.subject,
        messageId: match.internetMessageId || match.id, receivedDateTime: match.receivedDateTime
      });
      status(`IMO ${match.imos[0]} found. Opening broker workflow…`, "success");
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (error) {
      status(error.message || String(error), "error");
    } finally {
      button.disabled = false;
    }
  });
});
