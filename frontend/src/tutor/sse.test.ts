import { SseParser } from "./sse";

test("events split across chunks, CRLF and pings", () => {
  const p = new SseParser();
  expect(p.feed('event: token\r\ndata: {"text":"Hal')).toEqual([]);
  expect(p.feed('lo"}\r\n\r\n: ping\r\n\r\nevent: ping\ndata: {}\n\nevent: rewrite\ndata: {"codes":["X"]}\n\n')).toEqual([
    { event: "token", data: { text: "Hallo" } },
    { event: "rewrite", data: { codes: ["X"] } },
  ]);
});
