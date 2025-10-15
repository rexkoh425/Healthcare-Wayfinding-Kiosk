const WebSocket = require("ws");

const PORT = process.env.PORT || 8080;
const wss = new WebSocket.Server({ port: PORT });

console.log(`WebSocket server listening on ws://localhost:${PORT}`);

const clientRoles = new Map(); // ws -> role string ('hologram'|'touchscreen')

function sendSafe(ws, obj) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

wss.on("connection", (ws) => {
  console.log("New client connected");

  ws.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw);
    } catch (err) {
      console.warn("Invalid JSON received:", raw.toString());
      return;
    }

    if (msg.type === "register" && (msg.role === "hologram" || msg.role === "touchscreen")) {
      clientRoles.set(ws, msg.role);
      console.log("Client registered as:", msg.role);
      sendSafe(ws, { type: "registered", role: msg.role });
      return;
    }

    // Forward subtitle to hologram clients
    if (msg.type === "subtitle" && typeof msg.text === "string") {
      for (const [client, r] of clientRoles.entries()) {
        if (r === "hologram" && client.readyState === WebSocket.OPEN) {
          sendSafe(client, { type: "subtitle", text: msg.text });
        }
      }
      return;
    }

    // actions from touchscreen
    if (msg.type === "action" && typeof msg.action === "string") {
      const role = clientRoles.get(ws) || "unknown";
      console.log(`Received action '${msg.action}' from role ${role}`);

      // Only accept action messages from touchscreen clients
      if (role !== "touchscreen") {
        console.warn("Action ignored: not from touchscreen client");
        return;
      }

      // Forward to all hologram clients (could be only one)
      for (const [client, r] of clientRoles.entries()) {
        if (r === "hologram" && client.readyState === WebSocket.OPEN) {
          if (msg.action === "talk") {
            sendSafe(client, { type: "set", video: "listen.mp4", reason: "talk" });
          } else if (msg.action === "hear") {
            sendSafe(client, { type: "set", video: "reply.mp4", reason: "hear" });
          } else if (msg.action === "idle") {
            sendSafe(client, { type: "set", video: "wave.mp4", reason: "idle" });
          } else {
            // custom actions support
            sendSafe(client, { type: "set", video: msg.video || "wave.mp4", reason: msg.action });
          }
        }
      }
    }

    console.log("Received message:", msg);
  });

  ws.on("close", () => {
    const role = clientRoles.get(ws);
    clientRoles.delete(ws);
    console.log("Connection closed", role || "");
  });

  ws.on("error", (err) => {
    console.warn("WS error:", err);
  });
});
