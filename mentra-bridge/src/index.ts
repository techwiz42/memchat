import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { loadConfig } from "./config.js";
import { TokenStore } from "./TokenStore.js";
import { PairingManager } from "./PairingManager.js";
import { MentraApp } from "./MentraApp.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

async function main(): Promise<void> {
  const config = loadConfig();
  console.log("Mentra Bridge starting...");
  console.log(`  Package: ${config.mentraPackageName}`);
  console.log(`  Memchat API: ${config.memchatBaseUrl}`);
  console.log(`  Redis: ${config.redisUrl}`);
  console.log(`  Port: ${config.port}`);

  const tokenStore = new TokenStore(config.redisUrl);
  const pairingManager = new PairingManager(tokenStore, config);

  // Create the Mentra app (handles glasses WebSocket sessions via MentraOS cloud)
  const app = new MentraApp(config, tokenStore, pairingManager);

  // Serve the pairing page and API on the same Express app that AppServer creates
  const expressApp = app.getExpressApp();

  const pairHtmlPath = join(__dirname, "..", "pair.html");
  const pairHtml = readFileSync(pairHtmlPath, "utf-8");

  expressApp.get("/pair", (_req: any, res: any) => {
    res.type("html").send(pairHtml);
  });

  expressApp.post("/api/pair", async (req: any, res: any) => {
    try {
      const { code, email, password } = req.body ?? {};

      if (!code || !email || !password) {
        res.status(400).json({ error: "Missing required fields" });
        return;
      }

      const result = await pairingManager.handlePairRequest(
        code,
        email,
        password
      );

      if (result.success) {
        res.json({ success: true });
      } else {
        res.status(400).json({ error: result.error });
      }
    } catch (err) {
      console.error("Pairing request error:", err);
      res.status(500).json({ error: "Internal server error" });
    }
  });

  // Start the app (express server + MentraOS cloud connection)
  await app.start();
  console.log(`Mentra Bridge running on port ${config.port}`);
  console.log(`Pairing page: ${config.pairingBaseUrl}/pair`);

  // Graceful shutdown
  const shutdown = async () => {
    console.log("Shutting down...");
    await app.stop();
    await tokenStore.disconnect();
    process.exit(0);
  };

  process.on("SIGTERM", shutdown);
  process.on("SIGINT", shutdown);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
