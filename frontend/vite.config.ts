/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const api = `http://localhost:${process.env.TUTOR_API_PORT ?? "8020"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    proxy: { "/tutor": api, "/healthz": api },
  },
  test: { environment: "jsdom", globals: true },
});
