import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			// Static files served by the P.IGE server (PIGE_WEB_DIR=web/build).
			// 200.html: shell for the interface routes (/journal/…), served by the server for unknown pages.
			adapter: adapter({ pages: 'build', assets: 'build', fallback: '200.html', strict: true }),
			csp: {
				mode: 'hash',
				directives: {
					'default-src': ['self'],
					'script-src': ['self'],
					'style-src': ['self', 'unsafe-inline'],
					'img-src': ['self', 'data:'],
					'font-src': ['self'],
					'connect-src': ['self'],
					'manifest-src': ['self'],
					'worker-src': ['self'],
					'object-src': ['none'],
					'base-uri': ['none'],
					'form-action': ['self']
				}
			}
		})
	],
	server: {
		// During development, forward API calls to a local `python -m pige.server serve`.
		proxy: { '/api': 'http://127.0.0.1:8765' }
	}
});
