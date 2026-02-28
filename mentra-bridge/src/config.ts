import { readFileSync } from "node:fs";

function readSecret(envVar: string): string {
  const direct = process.env[envVar];
  if (direct) return direct.trim();

  const fileEnvVar = `${envVar}_FILE`;
  const filePath = process.env[fileEnvVar];
  if (filePath) {
    try {
      return readFileSync(filePath, "utf-8").trim();
    } catch (err) {
      console.error(`Failed to read secret from ${fileEnvVar}=${filePath}:`, err);
    }
  }

  throw new Error(
    `Missing required secret: set ${envVar} or ${fileEnvVar} pointing to a file`
  );
}

export interface Config {
  mentraPackageName: string;
  mentraApiKey: string;
  memchatBaseUrl: string;
  memchatWsUrl: string;
  redisUrl: string;
  port: number;
  pairingBaseUrl: string;
}

export function loadConfig(): Config {
  return {
    mentraPackageName:
      process.env.MENTRA_PACKAGE_NAME ?? "ai.cyberiad.memchat",
    mentraApiKey: readSecret("MENTRA_API_KEY"),
    memchatBaseUrl: process.env.MEMCHAT_BASE_URL ?? "http://backend:8000",
    memchatWsUrl: process.env.MEMCHAT_WS_URL ?? "ws://backend:8000",
    redisUrl: process.env.REDIS_URL ?? "redis://redis:6379/0",
    port: parseInt(process.env.MENTRA_PORT ?? "3100", 10),
    pairingBaseUrl:
      process.env.PAIRING_BASE_URL ?? "https://mentra.cyberiad.ai",
  };
}
