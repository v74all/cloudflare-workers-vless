import { connect } from "cloudflare:sockets";

const DEFAULT_UUID = "d3b07384-d113-49d6-a2a4-b885315e34b1";

export default {
  async fetch(request, env, ctx) {
    const upgradeHeader = request.headers.get("Upgrade");
    if (upgradeHeader !== "websocket") {
      const url = new URL(request.url);
      if (url.pathname === "/status") {
        return new Response("OK", { status: 200 });
      }
      return new Response(
        "<!DOCTYPE html><html><head><title>Edge Gateway</title></head><body><h1>Service Active</h1></body></html>",
        {
          status: 200,
          headers: { "Content-Type": "text/html; charset=utf-8" }
        }
      );
    }
    const webSocketPair = new WebSocketPair();
    const [client, server] = Object.values(webSocketPair);
    server.accept();
    handleVlessSession(server, env).catch(() => {
      try {
        server.close();
      } catch (_) {}
    });
    return new Response(null, {
      status: 101,
      webSocket: client
    });
  }
};

async function handleVlessSession(ws, env) {
  const targetUUID = (env && env.UUID) || DEFAULT_UUID;
  let remoteSocket = null;
  let writer = null;

  ws.addEventListener("message", async (event) => {
    try {
      const buffer = event.data;
      if (typeof buffer === "string") {
        return;
      }
      if (!remoteSocket) {
        const { hasError, message, address, port, rawClientData } = parseVlessHeader(buffer, targetUUID);
        if (hasError) {
          ws.close(1008, message);
          return;
        }
        remoteSocket = connect({ hostname: address, port: port });
        writer = remoteSocket.writable.getWriter();
        const vlessResponseHeader = new Uint8Array([buffer[0], 0]);
        ws.send(vlessResponseHeader);
        if (rawClientData && rawClientData.byteLength > 0) {
          await writer.write(rawClientData);
        }
        pipeRemoteToWebSocket(remoteSocket.readable, ws);
      } else {
        if (writer) {
          await writer.write(buffer);
        }
      }
    } catch (_) {
      try {
        ws.close();
      } catch (_) {}
    }
  });

  ws.addEventListener("close", () => {
    if (remoteSocket) {
      try {
        remoteSocket.close();
      } catch (_) {}
    }
  });

  ws.addEventListener("error", () => {
    if (remoteSocket) {
      try {
        remoteSocket.close();
      } catch (_) {}
    }
  });
}

function parseVlessHeader(buffer, expectedUUID) {
  if (buffer.byteLength < 24) {
    return { hasError: true, message: "Invalid payload length" };
  }
  const view = new DataView(buffer);
  const version = view.getUint8(0);
  const clientUUID = formatUUID(new Uint8Array(buffer.slice(1, 17)));
  if (clientUUID.toLowerCase() !== expectedUUID.toLowerCase()) {
    return { hasError: true, message: "Authentication failed" };
  }
  const optLength = view.getUint8(17);
  let cursor = 18 + optLength;
  const command = view.getUint8(cursor);
  cursor += 1;
  if (command !== 1) {
    return { hasError: true, message: "Unsupported command" };
  }
  const port = view.getUint16(cursor);
  cursor += 2;
  const addressType = view.getUint8(cursor);
  cursor += 1;
  let address = "";
  if (addressType === 1) {
    address = [
      view.getUint8(cursor),
      view.getUint8(cursor + 1),
      view.getUint8(cursor + 2),
      view.getUint8(cursor + 3)
    ].join(".");
    cursor += 4;
  } else if (addressType === 2) {
    const domainLength = view.getUint8(cursor);
    cursor += 1;
    address = new TextDecoder().decode(buffer.slice(cursor, cursor + domainLength));
    cursor += domainLength;
  } else if (addressType === 3) {
    const ipv6 = [];
    for (let i = 0; i < 8; i++) {
      ipv6.push(view.getUint16(cursor + i * 2).toString(16));
    }
    address = ipv6.join(":");
    cursor += 16;
  } else {
    return { hasError: true, message: "Unsupported address type" };
  }
  const rawClientData = buffer.slice(cursor);
  return { hasError: false, address, port, rawClientData };
}

async function pipeRemoteToWebSocket(readable, ws) {
  const reader = readable.getReader();
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      if (ws.readyState === 1) {
        ws.send(value);
      }
    }
  } catch (_) {
  } finally {
    try {
      ws.close();
    } catch (_) {}
  }
}

function formatUUID(bytes) {
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
