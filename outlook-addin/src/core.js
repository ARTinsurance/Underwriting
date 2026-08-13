const LABELED_IMO = /\bIMO(?:\s*(?:number|no\.?))?\s*[:#-]?\s*(\d[\d\s-]{5,10}\d)\b/gi;
const ANY_SEVEN_DIGITS = /(?<!\d)(\d{7})(?!\d)/g;

export function normalizeImo(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length === 7 ? digits : null;
}

export function isValidImo(value) {
  const imo = normalizeImo(value);
  if (!imo) return false;
  const checksum = [...imo.slice(0, 6)].reduce((sum, digit, index) => sum + Number(digit) * (7 - index), 0) % 10;
  return checksum === Number(imo[6]);
}

export function extractImos(text) {
  const source = String(text || "");
  const labeled = [...source.matchAll(LABELED_IMO)].map(match => normalizeImo(match[1]));
  const general = [...source.matchAll(ANY_SEVEN_DIGITS)].map(match => match[1]);
  return [...new Set([...labeled, ...general].filter(isValidImo))];
}

export function brokerMatches(message, broker) {
  const needle = String(broker || "").trim().toLocaleLowerCase();
  if (!needle) return true;
  const sender = message.sender?.emailAddress || {};
  return [sender.name, sender.address, message.from?.emailAddress?.name, message.from?.emailAddress?.address]
    .some(value => String(value || "").toLocaleLowerCase().includes(needle));
}

export function chooseFirstOrigination(messages, broker) {
  return messages
    .filter(message => brokerMatches(message, broker))
    .map(message => ({ ...message, imos: extractImos(`${message.subject || ""}\n${message.body?.content || ""}\n${message.bodyPreview || ""}`) }))
    .filter(message => message.imos.length)
    .sort((left, right) => new Date(left.receivedDateTime) - new Date(right.receivedDateTime))[0] || null;
}

export function renderBrokerUrl(template, values) {
  if (!/^https?:\/\//i.test(String(template || ""))) throw new Error("Broker workflow URL must use HTTPS or HTTP.");
  return template.replace(/\{(imo|broker|subject|messageId|receivedDateTime)\}/g, (_match, key) => encodeURIComponent(values[key] || ""));
}

export function graphSearchUrl(keyword) {
  const query = `\"${String(keyword).replace(/[\\\"]/g, " ").trim()}\"`;
  const params = new URLSearchParams({
    "$search": query,
    "$select": "id,internetMessageId,subject,sender,from,receivedDateTime,body,bodyPreview,webLink",
    "$top": "50"
  });
  return `https://graph.microsoft.com/v1.0/me/messages?${params}`;
}
