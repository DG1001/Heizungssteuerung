import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const mqttTarget = env.VITE_MQTT_URL || 'ws://localhost:9001';

  return {
    server: {
      host: '0.0.0.0',
      port: 3000,
      allowedHosts: true,
      proxy: {
        '/mqtt-proxy': {
          target: mqttTarget,
          ws: true,
          rewrite: () => '/',
        },
      },
    },
    define: {
      global: 'globalThis',
    },
  };
});
