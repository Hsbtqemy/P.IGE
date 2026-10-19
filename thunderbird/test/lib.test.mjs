import assert from 'node:assert/strict';
import test from 'node:test';
import { defaultSpace, entryForMail, excerpt, formatSize, localDay, mailFooter, menuItems, parseAuthor, parseMenuId, plainBody, stableId } from '../lib.js';

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

test('a long mail is kept whole, with recipients and attachments below', () => {
  const long = 'Phrase du mail. '.repeat(200);
  const entry = entryForMail({
    id: 'e'.repeat(32),
    header: {
      author: 'anne@univ.fr',
      subject: 'Long',
      date: new Date(2026, 2, 12),
      recipients: ['Hugo <hugo@univ.fr>'],
      ccList: ['Paul Durand <paul@univ.fr>', 'zoe@univ.fr']
    },
    text: long,
    attachments: [{ name: 'devis.pdf', size: 125_000 }],
    target: { space_id: 's1' },
    personIds: []
  });
  assert.ok(entry.body.includes(long.trim()));
  assert.ok(entry.body.endsWith('À : Hugo\nCc : Paul Durand, zoe@univ.fr\nPièces jointes : devis.pdf (122 Ko)'));
  // The excerpt the old extension sent is contained in the new text (so the server completes it).
  const old = `Mail de anne@univ.fr\n\n${excerpt(long)}`.replace(/…$/, '');
  assert.ok(entry.body.replace(/\s+/g, ' ').includes(old.replace(/\s+/g, ' ')));
});

test('footer and sizes', () => {
  assert.equal(mailFooter({}, []), '');
  assert.equal(formatSize(900), '900 o');
  assert.equal(formatSize(3 * 1024 * 1024 + 400_000), '3,4 Mo');
  const many = Array.from({ length: 10 }, (_, i) => `p${i}@x.fr`);
  assert.equal(mailFooter({ recipients: many }, null), `À : ${many.slice(0, 8).join(', ')} et 2 autres`);
});
