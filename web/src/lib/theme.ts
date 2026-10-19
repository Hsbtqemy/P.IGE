// Light or dark: by default P.IGE follows the device; a choice made in Réglages is kept on
// this device only (localStorage) and applied as data-theme on <html> (see app.html, which
// applies it before the first paint, and app.css / carnet.css).

export type Theme = 'auto' | 'light' | 'dark';

const KEY = 'pige-theme';
const BAR = { light: '#eef1f4', dark: '#14181d' };

export function getTheme(): Theme {
	try {
		const value = localStorage.getItem(KEY);
		return value === 'light' || value === 'dark' ? value : 'auto';
	} catch {
		return 'auto';
	}
}

export function setTheme(theme: Theme): void {
	try {
		if (theme === 'auto') localStorage.removeItem(KEY);
		else localStorage.setItem(KEY, theme);
	} catch {
		/* private mode: applies to this visit only */
	}
	applyTheme(theme);
}

export function applyTheme(theme: Theme): void {
	const root = document.documentElement;
	if (theme === 'auto') delete root.dataset.theme;
	else root.dataset.theme = theme;
	// The browser bar colour: forced to the chosen theme, else per the device's scheme.
	for (const meta of document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
		const scheme = meta.media.includes('dark') ? 'dark' : 'light';
		meta.content = BAR[theme === 'auto' ? scheme : theme];
	}
}
