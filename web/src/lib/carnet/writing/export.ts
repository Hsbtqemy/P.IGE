// What a long text can become: Markdown, Word, PDF (through printing), a mail draft.
// Nothing is ever sent: the mail opens in the mail program (Thunderbird) for review.

import DOMPurify from 'dompurify';
import { marked } from 'marked';

/** ``breaks``: a line break in the text is one on screen too (as in the editor). */
export function toHtml(text: string, breaks = false): string {
	const html = marked.parse(text, { async: false, gfm: true, breaks }) as string;
	return DOMPurify.sanitize(html);
}

/** « Compte rendu : réunion du 12 » -> « Compte rendu - reunion du 12 » (safe on every system). */
export function fileName(title: string, extension: string): string {
	const base =
		title
			.normalize('NFKD')
			.replace(/\p{M}/gu, '')
			.replace(/[\\/:*?"<>|]+/g, ' - ')
			.replace(/\s+/g, ' ')
			.trim()
			.slice(0, 80) || 'texte';
	return `${base}.${extension}`;
}

function download(name: string, type: string, content: string) {
	const url = URL.createObjectURL(new Blob([content], { type }));
	const link = document.createElement('a');
	link.href = url;
	link.download = name;
	document.body.append(link);
	link.click();
	link.remove();
	setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadMarkdown(title: string, text: string) {
	download(fileName(title, 'md'), 'text/markdown;charset=utf-8', text);
}

const PAGE_CSS = `
	body { font-family: Georgia, 'Times New Roman', serif; font-size: 11.5pt; line-height: 1.5; color: #1e2320; max-width: 42em; margin: 2em auto; padding: 0 1em; }
	h1, h2, h3 { line-height: 1.25; }
	h1 { font-size: 1.7em; } h2 { font-size: 1.35em; margin-top: 1.4em; } h3 { font-size: 1.1em; }
	blockquote { margin-left: 0; padding-left: 1em; border-left: 3px solid #7a2e3a; color: #58625a; }
	code { font-family: Menlo, Consolas, monospace; font-size: 0.9em; }
	table { border-collapse: collapse; } td, th { border: 1px solid #d6dbd4; padding: 4px 8px; }
	@page { margin: 2cm; }
`;

function page(title: string, text: string): string {
	const safeTitle = title.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c] as string);
	return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>${safeTitle}</title><style>${PAGE_CSS}</style></head><body>${toHtml(text)}</body></html>`;
}

/** A .doc that Word and LibreOffice open as a formatted document. */
export function downloadWord(title: string, text: string) {
	download(fileName(title, 'doc'), 'application/msword;charset=utf-8', `﻿${page(title, text)}`);
}

/** Opens the formatted text alone and the print dialog, where « Enregistrer en PDF » is offered. */
export function printPdf(title: string, text: string): boolean {
	const win = window.open('', '_blank');
	if (!win) return false;
	win.document.open();
	win.document.write(page(title, text));
	win.document.close();
	win.focus();
	setTimeout(() => win.print(), 250);
	return true;
}

/** Plain text for a mail: the Markdown signs that would look odd are removed. */
export function plainText(text: string): string {
	return text
		.replace(/^#{1,6}\s+/gm, '')
		.replace(/\*\*(.+?)\*\*/g, '$1')
		.replace(/(^|[^*])\*(?!\s)(.+?)\*/g, '$1$2')
		.replace(/(^|\W)_(?!\s)(.+?)_(?=\W|$)/g, '$1$2')
		.replace(/`([^`]+)`/g, '$1')
		.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '$1 ($2)');
}

/** A mail draft in the mail program. Long texts are cut by some programs: then copy instead. */
export function mailLink(title: string, text: string): { href: string; tooLong: boolean } {
	const body = plainText(text);
	const href = `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
	return { href, tooLong: href.length > 1900 };
}

export async function copyFormatted(text: string): Promise<void> {
	const html = toHtml(text);
	const plain = plainText(text);
	if (typeof ClipboardItem !== 'undefined' && navigator.clipboard?.write) {
		await navigator.clipboard.write([
			new ClipboardItem({
				'text/html': new Blob([html], { type: 'text/html' }),
				'text/plain': new Blob([plain], { type: 'text/plain' })
			})
		]);
	} else {
		await navigator.clipboard.writeText(plain);
	}
}

export const TEMPLATES: { id: string; label: string; kind: 'note' | 'meeting'; body: (title: string, date: string) => string }[] = [
	{ id: 'vide', label: 'Page blanche', kind: 'note', body: (title) => `# ${title}\n\n` },
	{
		id: 'cr',
		label: 'Compte rendu de réunion',
		kind: 'meeting',
		body: (title, date) =>
			`# ${title}\n\n**Date :** ${date}  \n**Présent·es :** \n\n## Ordre du jour\n\n- \n\n## Échanges\n\n\n\n## Décisions\n\n- \n\n## Suites à donner\n\n- [ ] \n`
	},
	{
		id: 'cadrage',
		label: 'Note de cadrage',
		kind: 'note',
		body: (title) =>
			`# ${title}\n\n## Contexte\n\n\n\n## Objectifs\n\n- \n\n## Périmètre\n\n\n\n## Acteurs\n\n\n\n## Calendrier\n\n\n\n## Moyens\n\n\n\n## Risques et points de vigilance\n\n`
	}
];
