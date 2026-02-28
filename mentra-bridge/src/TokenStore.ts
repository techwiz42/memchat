import { Redis } from "ioredis";
import type { PairingRequest, UserMapping } from "./types.js";

const PAIRING_TTL = 300; // 5 minutes
const USER_MAPPING_TTL = 30 * 24 * 60 * 60; // 30 days

export class TokenStore {
  private redis: Redis;

  constructor(redisUrl: string) {
    this.redis = new Redis(redisUrl);
  }

  // --- Pairing codes ---

  async storePairingCode(
    code: string,
    mentraUserId: string
  ): Promise<void> {
    const data: PairingRequest = {
      mentraUserId,
      createdAt: Date.now(),
    };
    await this.redis.setex(
      `mentra:pair:${code}`,
      PAIRING_TTL,
      JSON.stringify(data)
    );
  }

  async consumePairingCode(code: string): Promise<PairingRequest | null> {
    const raw = await this.redis.get(`mentra:pair:${code}`);
    if (!raw) return null;
    await this.redis.del(`mentra:pair:${code}`);
    return JSON.parse(raw) as PairingRequest;
  }

  // --- User mappings ---

  async storeUserMapping(
    mentraUserId: string,
    mapping: UserMapping
  ): Promise<void> {
    await this.redis.setex(
      `mentra:user:${mentraUserId}`,
      USER_MAPPING_TTL,
      JSON.stringify(mapping)
    );
  }

  async getUserMapping(mentraUserId: string): Promise<UserMapping | null> {
    const raw = await this.redis.get(`mentra:user:${mentraUserId}`);
    if (!raw) return null;
    return JSON.parse(raw) as UserMapping;
  }

  async updateAccessToken(
    mentraUserId: string,
    accessToken: string,
    expiresAt: number
  ): Promise<void> {
    const mapping = await this.getUserMapping(mentraUserId);
    if (!mapping) throw new Error(`No mapping for mentra user ${mentraUserId}`);
    mapping.memchatAccessToken = accessToken;
    mapping.accessTokenExpiresAt = expiresAt;
    await this.storeUserMapping(mentraUserId, mapping);
  }

  async updateConversationId(
    mentraUserId: string,
    conversationId: string
  ): Promise<void> {
    const mapping = await this.getUserMapping(mentraUserId);
    if (!mapping) throw new Error(`No mapping for mentra user ${mentraUserId}`);
    mapping.conversationId = conversationId;
    await this.storeUserMapping(mentraUserId, mapping);
  }

  async removeUserMapping(mentraUserId: string): Promise<void> {
    await this.redis.del(`mentra:user:${mentraUserId}`);
  }

  async disconnect(): Promise<void> {
    await this.redis.quit();
  }
}
