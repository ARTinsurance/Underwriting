import test from "node:test";
import assert from "node:assert/strict";
import { chooseFirstOrigination, extractImos, graphSearchUrl, isValidImo, renderBrokerUrl } from "../src/core.js";

test("validates IMO checksum and extracts labeled values", () => {
  assert.equal(isValidImo("9342865"), true);
  assert.equal(isValidImo("9342864"), false);
  assert.deepEqual(extractImos("Vessel IMO No. 934-2865; ref 1234560"), ["9342865"]);
});

test("chooses the oldest matching broker message containing an IMO", () => {
  const messages = [
    { receivedDateTime: "2026-08-02T10:00:00Z", subject: "Origination IMO 9433066", sender: { emailAddress: { name: "Alpha Broker" } } },
    { receivedDateTime: "2026-08-01T10:00:00Z", subject: "Origination", body: { content: "IMO: 9342865" }, sender: { emailAddress: { name: "Alpha Broker" } } },
    { receivedDateTime: "2026-07-01T10:00:00Z", subject: "Origination IMO 9433066", sender: { emailAddress: { name: "Other" } } }
  ];
  assert.equal(chooseFirstOrigination(messages, "alpha").imos[0], "9342865");
});

test("creates encoded Graph and broker URLs", () => {
  assert.match(graphSearchUrl('first "origination"'), /%24search=/);
  assert.equal(renderBrokerUrl("https://uw.example/run?imo={imo}&broker={broker}", { imo: "9342865", broker: "A & B" }), "https://uw.example/run?imo=9342865&broker=A%20%26%20B");
});
