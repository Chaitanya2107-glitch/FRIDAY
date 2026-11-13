import { defineConfig } from 'vite';
import { resolve } from 'node:path';
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

export default defineConfig({
  root: resolve(import.meta.dirname, 'remote'), base: './',
  build: {
    outDir: '../remote-dist', emptyOutDir: true,
    rollupOptions: { output: { entryFileNames: 'app.js', assetFileNames: 'style[extname]' } },
  },
  plugins: [{ name: 'remote-shell-version', closeBundle() {
    const dir = resolve(import.meta.dirname, 'remote-dist');
    const hash = createHash('sha256');
    for (const name of ['app.js', 'style.css', 'index.html', 'manifest.webmanifest', 'sw.js',
      'icon-192.png', 'icon-512.png', 'apple-touch-icon.png']) hash.update(readFileSync(resolve(dir, name)));
    const version = hash.digest('hex').slice(0, 16);
    const path = resolve(dir, 'sw.js');
    writeFileSync(path, readFileSync(path, 'utf8').replace('__VERSION__', version));
  } }],
});
