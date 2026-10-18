import assert from 'node:assert/strict';
import test from 'node:test';
import { defaultSpace, entryForMail, excerpt, localDay, menuItems, parseAuthor, parseMenuId, plainBody, stableId } from '../lib.js';

const tree = {
  spaces: [
    { id: 's1', name: 'FoReLLIS', projects: [{ id: 'p1', name: 'DICODIACHRO', parent_id: null }, { id: 'p2', name: 'Sous-projet', parent_id: 'p1' }] },
    { id: 's2', name: 'À trier', projects: [] },
    { id: 's3', name: 'PERSO/ADMIN', projects: [] }
  ]
};

test('authors are split into name and address', () => {
  assert.deepEqual(parseAuthor('Anne Martin <Anne.Martin@Univ.fr>'), { name: 'Anne Martin', email: 'anne.martin@univ.fr' });
  assert.deepEqual(parseAuthor('"Martin, Anne" <a@b.fr>'), { name: 'Martin, Anne', email: 'a@b.fr' });
  assert.deepEqual(parseAuthor('a@b.fr'), { name: '', email: 'a@b.fr' });
  assert.deepEqual(parseAuthor(''), { name: '', email: '' });
});

test('ids are stable per mail and per purpose', async () => {
  const a = await stableId('abc@mail', 'entry');
  assert.match(a, /^[0-9a-f]{32}$/);
  assert.equal(a, await stableId('abc@mail', 'entry'));
  assert.notEqual(a, await stableId('abc@mail', 'task'));
});

test('excerpt drops quoted replies and signatures', () => {
  const text = 'Bonjour,\n\nVoici le devis.\n\n-- \nAnne\n';
  assert.equal(excerpt(text), 'Bonjour,\n\nVoici le devis.');
  assert.equal(excerpt('Oui.\nLe 12 mars, Paul a écrit :\n> question'), 'Oui.');
  assert.ok(excerpt('mot '.repeat(400), 50).endsWith('…'));
});

test('plain body is found in nested parts', () => {
  const full = { contentType: 'multipart/mixed', parts: [{ contentType: 'multipart/alternative', parts: [{ contentType: 'text/plain', body: 'Texte' }, { contentType: 'text/html', body: '<p>x</p>' }] }] };
  assert.equal(plainBody(full), 'Texte');
  assert.equal(plainBody(null), '');
});

test('menu: À trier first, then spaces with their projects', () => {
  assert.equal(defaultSpace(tree).id, 's2');
  const items = menuItems(tree, 'task', 'task');
  assert.deepEqual(items.map((i) => i.title ?? '—'), ['Dans « À trier »', '—', 'FoReLLIS', 'FoReLLIS (sans projet)', 'DICODIACHRO', '   Sous-projet', 'PERSO/ADMIN']);
  assert.equal(new Set(items.map((i) => i.id)).size, items.length);
  assert.deepEqual(parseMenuId('task|p|p1'), { action: 'task', target: { project_id: 'p1' } });
  assert.deepEqual(parseMenuId('note|s|s2'), { action: 'note', target: { space_id: 's2' } });
  assert.equal(parseMenuId('task|g|s1'), null);
  assert.equal(parseMenuId('task|sep'), null);
  assert.equal(parseMenuId('other|p|x'), null);
});

test('a mail becomes a dated entry linked by its Message-ID', () => {
  const entry = entryForMail({
    id: 'e'.repeat(32),
    header: { author: 'Anne Martin <anne@univ.fr>', subject: ' Devis PPrim ', date: new Date(2026, 2, 12, 9, 30), headerMessageId: 'abc@mail' },
    text: 'Bonjour,\nci-joint.\n-- \nAnne',
    target: { project_id: 'p1' },
    personIds: ['x']
  });
  assert.equal(entry.entry_date, '2026-03-12');
  assert.equal(entry.title, 'Devis PPrim');
  assert.equal(entry.mail_message_id, '<abc@mail>');
  assert.equal(entry.source, 'mail');
  assert.equal(entry.body, 'Mail de Anne Martin <anne@univ.fr>\n\nBonjour,\nci-joint.');
  assert.deepEqual(entry.person_ids, ['x']);
  assert.equal(entry.project_id, 'p1');
  assert.equal(localDay(new Date('invalid')).length, 10);
});
