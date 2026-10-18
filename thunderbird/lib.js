// Pure helpers of the extension (no Thunderbird API here, so they can be tested with node).

/** "Anne Martin <anne.martin@univ.fr>" -> { name: "Anne Martin", email: "anne.martin@univ.fr" } */
export function parseAuthor(author) {
  const text = String(author || '').trim();
  const angle = text.match(/^\s*"?([^"<]*?)"?\s*<([^<>\s]+@[^<>\s]+)>\s*$/);
  if (angle) return { name: angle[1].trim(), email: angle[2].toLowerCase() };
  const bare = text.match(/^([^\s@]+@[^\s@]+)$/);
  if (bare) return { name: '', email: bare[1].toLowerCase() };
  return { name: text, email: '' };
}

/** A 32-hex id derived from the mail's Message-ID: the same mail always gives the same entry or task. */
export async function stableId(headerMessageId, purpose) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${purpose}|${headerMessageId}`));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
}

export function randomId() {
  return crypto.randomUUID().replaceAll('-', '');
}

/** The local calendar day of a date, AAAA-MM-JJ. */
export function localDay(date) {
  const d = date instanceof Date && !Number.isNaN(date.getTime()) ? date : new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/** The first lines of the mail's text, without quoted replies or signature. */
export function excerpt(text, max = 600) {
  const lines = [];
  for (const raw of String(text || '').replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd();
    if (/^-- ?$/.test(line)) break; // signature
    if (/^>/.test(line)) continue; // quoted reply
    if (/^(Le .+ a écrit|On .+ wrote)\s*:$/.test(line.trim())) break;
    lines.push(line);
  }
  const joined = lines.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  return joined.length > max ? `${joined.slice(0, max - 1).replace(/\s+\S*$/, '')}…` : joined;
}

/** The plain text of a full message (messages.getFull), or ''. */
export function plainBody(part) {
  if (!part) return '';
  if (part.contentType === 'text/plain' && typeof part.body === 'string') return part.body;
  for (const child of part.parts || []) {
    const text = plainBody(child);
    if (text) return text;
  }
  return '';
}

/** Where unsorted things go: the « À trier » space, else the first one. */
export function defaultSpace(tree) {
  const spaces = tree?.spaces || [];
  return spaces.find((s) => s.name.toLocaleLowerCase('fr') === 'à trier') || spaces[0] || null;
}

/**
 * The menu under « P.IGE » for one action: À trier first, then each space with its projects.
 * Returns plain items { id, title, parentId?, type? } for browser.menus.create.
 */
export function menuItems(tree, action, parentId) {
  const items = [];
  const fallback = defaultSpace(tree);
  if (fallback) items.push({ id: `${action}|s|${fallback.id}`, parentId, title: `Dans « ${fallback.name} »` });
  const spaces = (tree?.spaces || []).filter((s) => s.id !== fallback?.id || s.projects.length);
  if (spaces.length) items.push({ id: `${action}|sep`, parentId, type: 'separator' });
  for (const space of spaces) {
    if (!space.projects.length) {
      items.push({ id: `${action}|s|${space.id}`, parentId, title: space.name });
      continue;
    }
    const group = `${action}|g|${space.id}`;
    items.push({ id: group, parentId, title: space.name });
    items.push({ id: `${action}|s|${space.id}`, parentId: group, title: `${space.name} (sans projet)` });
    for (const project of space.projects) {
      const prefix = project.parent_id ? '   ' : '';
      items.push({ id: `${action}|p|${project.id}`, parentId: group, title: `${prefix}${project.name}` });
    }
  }
  return items;
}

/** "task|p|<id>" -> { action: 'task', target: { project_id } } ; null for groups and separators. */
export function parseMenuId(id) {
  const [action, kind, value] = String(id).split('|');
  if (!['task', 'note'].includes(action) || !value) return null;
  if (kind === 'p') return { action, target: { project_id: value } };
  if (kind === 's') return { action, target: { space_id: value } };
  return null;
}

/** The entry for a mail: dated the day it arrived, linked by its Message-ID. */
export function entryForMail({ id, header, text, target, personIds }) {
  const author = parseAuthor(header.author);
  const subject = (header.subject || '(sans objet)').trim();
  const from = author.name ? `${author.name} <${author.email}>` : author.email || 'expéditeur inconnu';
  const body = [`Mail de ${from}`, excerpt(text)].filter(Boolean).join('\n\n');
  return {
    id,
    entry_date: localDay(header.date ? new Date(header.date) : new Date()),
    ...target,
    kind: 'note',
    title: subject.slice(0, 500),
    body,
    source: 'mail',
    mail_message_id: header.headerMessageId ? `<${header.headerMessageId}>` : undefined,
    person_ids: personIds
  };
}
