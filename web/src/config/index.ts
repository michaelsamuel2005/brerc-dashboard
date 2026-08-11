// The ENTIRE R6 client surface: env-driven, Zod-validated, PUBLIC-only config.
// dev->prod is a swap of VITE_API_BASE_URL inside the API environment — never client code.
import { z } from "zod";

const ConfigSchema = z
  .object({
    apiBaseUrl: z.string().min(1, "VITE_API_BASE_URL is required"),
    mapStyleUrl: z.string().url().optional(),
    tileUrl: z.string().min(1).optional(),
  })
  .strict();

export type AppConfig = z.infer<typeof ConfigSchema>;

export function parseConfig(env: Record<string, string | undefined>): AppConfig {
  return ConfigSchema.parse({
    apiBaseUrl: env.VITE_API_BASE_URL ?? "/api",
    mapStyleUrl: env.VITE_MAP_STYLE_URL,
    tileUrl: env.VITE_TILE_URL,
  });
}

export const config: AppConfig = parseConfig(import.meta.env as unknown as Record<string, string | undefined>);
