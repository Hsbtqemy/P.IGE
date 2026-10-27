// The checkboxes of a long text (« - [ ] … ») and the tasks made from them.

export interface Box {
	title: string;
	done: boolean;
	line: number;
}

const BOX = /^\s*[-*+]\s+\[([ xX])\]\s+(.*?)\s*$/;

/** Every « - [ ] » / « - [x] » line, outside code blocks. */
export function boxes(text: string): Box[] {
	const out: Box[] = [];
	let fence = false;
	text.split('\n').forEach((line, i) => {
		if (/^\s*(```|~~~)/.test(line)) fence = !fence;
		if (fence) return;
		const m = line.match(BOX);
		if (m && m[2]) out.push({ title: m[2].slice(0, 500), done: m[1] !== ' ', line: i + 1 });
	});
	return out;
}

/** Same words, whatever the spaces and the case: how a box and its task are matched. */
export function sameTitle(a: string, b: string): boolean {
	const plain = (s: string) => s.split(/\s+/).filter(Boolean).join(' ').toLocaleLowerCase('fr');
	return plain(a) === plain(b);
}
