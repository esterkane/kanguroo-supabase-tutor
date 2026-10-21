// Server-Sent Events over a POST response body (EventSource only does GET).
import type { StreamEvent } from "./types";

export class SseParser {
  private buffer = "";

  /** Feed a decoded chunk; returns the complete events it finished. */
  feed(chunk: string): StreamEvent[] {
    this.buffer += chunk.replace(/\r\n/g, "\n");
    const events: StreamEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) >= 0) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      let name = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length && name !== "ping") {
        try {
          events.push({ event: name, data: JSON.parse(data.join("\n")) } as StreamEvent);
        } catch {
          // ignore keep-alive comments and malformed blocks
        }
      }
    }
    return events;
  }
}
