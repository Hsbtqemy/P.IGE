// Images sent to P.IGE: photos shrunk in the browser (about 2000 px, JPEG) before leaving,
// screenshots (PNG) kept as they are when already reasonable, so the server stays light.

import { ApiError } from '../api.js';

export interface StoredImage {
	id: string;
	entry_id: string | null;
	name: string;
	mime: string;
	size: number;
	width: number | null;
	height: number | null;
	url: string;
}

const MAX_SIDE = 2000;
const KEEP_BELOW = 1.5 * 1024 * 1024;

/** The scale that brings the longest side down to ``max`` (1 when already small enough). */
export function fit(width: number, height: number, max = MAX_SIDE): number {
	const longest = Math.max(width, height);
	return longest > max ? max / longest : 1;
}

/** A name for a pasted image that has none (« capture 2026-11-03 18h05.png »). */
export function imageName(file: File, now = new Date()): string {
	if (file.name && !/^image\.(png|jpe?g|gif|webp)$/i.test(file.name)) return file.name;
	const pad = (n: number) => String(n).padStart(2, '0');
	const ext = file.type === 'image/png' ? 'png' : file.type === 'image/gif' ? 'gif' : 'jpg';
	return `capture ${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}h${pad(now.getMinutes())}.${ext}`;
}

async function prepare(file: File): Promise<{ blob: Blob; width: number; height: number }> {
	const bitmap = await createImageBitmap(file);
	const { width, height } = bitmap;
	const scale = fit(width, height);
	const keep = file.type === 'image/gif' || (scale === 1 && file.size <= KEEP_BELOW && file.type !== 'image/heic');
	if (keep) {
		bitmap.close();
		return { blob: file, width, height };
	}
	const canvas = document.createElement('canvas');
	canvas.width = Math.round(width * scale);
	canvas.height = Math.round(height * scale);
	canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
	bitmap.close();
	// A screenshot stays PNG (sharp text); a photo becomes JPEG.
	const type = file.type === 'image/png' && canvas.width * canvas.height < 2_500_000 ? 'image/png' : 'image/jpeg';
	const blob = await new Promise<Blob>((resolve, reject) =>
		canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('image illisible'))), type, 0.85)
	);
	return { blob, width: canvas.width, height: canvas.height };
}

/** Send one image (to an entry already saved, or loose until the paragraph is saved). */
export async function uploadImage(file: File, entryId?: string): Promise<StoredImage> {
	if (!file.type.startsWith('image/')) throw new ApiError(415, 'Ce n’est pas une image');
	const name = imageName(file);
	const { blob, width, height } = await prepare(file);
	const params = new URLSearchParams({ name, width: String(width), height: String(height) });
	if (entryId) params.set('entry_id', entryId);
	let response: Response;
	try {
		response = await fetch(`/api/v2/files?${params}`, {
			method: 'POST',
			credentials: 'same-origin',
			headers: { 'x-pige-client': 'web', 'content-type': blob.type || 'application/octet-stream' },
			body: blob
		});
	} catch {
		throw new ApiError(0, 'Hors connexion');
	}
	if (!response.ok) {
		let detail = response.statusText;
		try {
			const data = await response.json();
			if (typeof data.detail === 'string') detail = data.detail;
		} catch {
			/* not JSON */
		}
		throw new ApiError(response.status, detail);
	}
	return (await response.json()) as StoredImage;
}

export async function deleteImage(id: string): Promise<void> {
	const response = await fetch(`/api/v2/files/${id}`, { method: 'DELETE', credentials: 'same-origin', headers: { 'x-pige-client': 'web' } });
	if (!response.ok && response.status !== 404) throw new ApiError(response.status, 'Image non supprimée');
}

/** The images of a text, for its Markdown: « ![name](url) ». */
export function markdownImage(img: StoredImage): string {
	const alt = img.name.replace(/\.[a-z0-9]+$/i, '').replace(/[[\]]/g, '');
	return `![${alt}](${img.url})`;
}
