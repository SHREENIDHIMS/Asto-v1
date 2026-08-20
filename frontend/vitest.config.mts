import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { defineConfig } from 'vitest/config';

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      '@': dirname,
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
});