export interface SseFrame {
  id: string;
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";

  push(chunk: string): SseFrame[] {
    this.buffer += chunk;
    const frames: SseFrame[] = [];
    while (true) {
      const boundary = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer);
      if (!boundary) break;
      const block = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      const frame = this.parse(block);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  private parse(block: string): SseFrame | null {
    let id = "";
    let event = "message";
    const data: string[] = [];
    for (const line of block.split(/\r\n|\r|\n/)) {
      if (!line || line.startsWith(":")) continue;
      const colon = line.indexOf(":");
      const field = colon < 0 ? line : line.slice(0, colon);
      const raw = colon < 0 ? "" : line.slice(colon + 1);
      const value = raw.startsWith(" ") ? raw.slice(1) : raw;
      if (field === "id") id = value;
      if (field === "event") event = value;
      if (field === "data") data.push(value);
    }
    return data.length ? { id, event, data: data.join("\n") } : null;
  }
}
