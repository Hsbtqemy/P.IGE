// Unit tests of plain TypeScript modules: no SvelteKit plugin needed.
import { defineConfig } from 'vitest/config';

export default defineConfig({
	test: { include: ['src/**/*.test.ts'], environment: 'node' }
});
