import { expect, it } from "vitest";
import { SseParser } from "./sse";

it("decodes events split across network chunks and preserves event IDs", () => {
  const parser = new SseParser();
  expect(parser.push('id: 4\nevent: model.delta\ndata: {"data":')).toEqual([]);
  expect(
    parser.push(
      '{"text":"你"}}\n\nid: 5\nevent: run.completed\ndata: {"data":{}}\n\n',
    ),
  ).toEqual([
    { id: "4", event: "model.delta", data: '{"data":{"text":"你"}}' },
    { id: "5", event: "run.completed", data: '{"data":{}}' },
  ]);
});

it("joins multi-line data and accepts CRLF boundaries", () => {
  const parser = new SseParser();
  expect(
    parser.push("event: note\r\ndata: first\r\ndata: second\r\n\r\n"),
  ).toEqual([{ id: "", event: "note", data: "first\nsecond" }]);
});
