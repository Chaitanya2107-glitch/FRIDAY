import { defineConfig } from 'vite';

export default defineConfig({
  clearScreen: false,
  build: { rollupOptions: { input: { main: 'index.html', hud: 'hud.html' } } },
  server: {
    host: '127.0.0.1', port: 1420, strictPort: true,
    watch: { ignored: ['**/src-tauri/**', '**/test-results/**'] },
  },
});
