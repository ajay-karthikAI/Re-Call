const { defineConfig } = require("vite");

module.exports = defineConfig(async () => {
  const { default: react } = await import("@vitejs/plugin-react");

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
