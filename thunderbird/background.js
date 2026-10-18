// P.IGE for Thunderbird.
// - Adds a P.IGE button to the Spaces toolbar, opening the journal in a tab.
// - Message list context menu « P.IGE »: create a task, or note the mail in the journal,
//   in « À trier » or in a chosen project. Linked by the Message-ID header (stable across
//   restarts and folder moves); the same mail never creates the same thing twice.
// - Bridge: the web app asks, through bridge.js, to reopen the email behind an entry.

import { entryForMail, menuItems, parseAuthor, parseMenuId, plainBody, stableId } from './lib.js';

const SPACE_NAME = 'pige';
const ROOT_MENU = 'pige';
const BRIDGE_ID = 'pige-bridge';
const TREE_MAX_AGE = 60_000;

let cache = { at: 0, tree: null, people: [] };

async function settings() {
  const { serverUrl = '', token = '' } = await browser.storage.local.get(['serverUrl', 'token']);
  return { serverUrl: serverUrl.replace(/\/+$/, ''), token };
}

function originOf(url) {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

async function api(method, path, body) {
  const { serverUrl, token } = await settings();
  const response = await fetch(`${serverUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json()).detail || '';
    } catch {
      /* not JSON */
    }
    throw new Error(`HTTP ${response.status}${detail ? ` : ${detail}` : ''}`);
  }
  return response.status === 204 ? null : response.json();
}

/** Spaces, projects and people, fetched at most once a minute. */
async function knowledge(force = false) {
  if (!force && cache.tree && Date.now() - cache.at < TREE_MAX_AGE) return cache;
  const [tree, people] = await Promise.all([api('GET', '/api/v2/tree'), api('GET', '/api/v2/people')]);
  cache = { at: Date.now(), tree, people };
  return cache;
}

// ------------------------------------------------------------------ space

async function ensureSpace() {
  const { serverUrl } = await settings();
  const existing = (await browser.spaces.query({ name: SPACE_NAME, isSelfOwned: true }))[0];
  const button = { title: 'P.IGE', defaultIcons: 'icons/icon-32.png' };
  if (!serverUrl) {
    if (existing) await browser.spaces.remove(existing.id);
    return;
  }
  const url = `${serverUrl}/journal`;
  if (existing) await browser.spaces.update(existing.id, url, button);
  else await browser.spaces.create(SPACE_NAME, url, button);
}

// ------------------------------------------------------------------ bridge

async function registerBridge() {
  const { serverUrl } = await settings();
  try {
    await browser.scripting.unregisterContentScripts({ ids: [BRIDGE_ID] });
  } catch {
    /* not registered yet */
  }
  const origin = originOf(serverUrl);
  if (!origin) return;
  if (!(await browser.permissions.contains({ origins: [`${origin}/*`] }))) return;
  await browser.scripting.registerContentScripts([
    { id: BRIDGE_ID, matches: [`${origin}/*`], js: ['bridge.js'], runAt: 'document_idle', persistAcrossSessions: false }
  ]);
}

browser.runtime.onMessage.addListener((message, sender) => {
  if (message?.type !== 'open-mail') return undefined;
  return openMail(message, sender);
});

async function openMail(message, sender) {
  // Only the P.IGE page itself may ask to open an email.
  const { serverUrl } = await settings();
  if (!sender.url || originOf(sender.url) !== originOf(serverUrl)) return;
  const messageId = String(message.messageId || '');
  if (!messageId || messageId.length > 998) return;
  try {
    await browser.messageDisplay.open({ headerMessageId: messageId.replace(/^<|>$/g, ''), location: 'tab' });
  } catch {
    notify('Mail introuvable', 'Ce mail n’est plus dans tes comptes Thunderbird, ou a été supprimé.');
  }
}

// ------------------------------------------------------------------ menu

async function buildMenu() {
  await browser.menus.removeAll();
  browser.menus.create({ id: ROOT_MENU, title: 'P.IGE', contexts: ['message_list'] });
  const { serverUrl, token } = await settings();
  if (!serverUrl || !token) {
    browser.menus.create({ id: 'configure', parentId: ROOT_MENU, title: 'Configurer l’extension…', contexts: ['message_list'] });
    return;
  }
  browser.menus.create({ id: 'task', parentId: ROOT_MENU, title: 'Créer une tâche', contexts: ['message_list'] });
  browser.menus.create({ id: 'note', parentId: ROOT_MENU, title: 'Noter dans le journal', contexts: ['message_list'] });
  let tree = null;
  try {
    tree = (await knowledge()).tree;
  } catch {
    browser.menus.create({ id: 'offline', parentId: ROOT_MENU, title: 'Serveur injoignable', enabled: false, contexts: ['message_list'] });
    return;
  }
  for (const action of ['task', 'note']) {
    for (const item of menuItems(tree, action, action)) browser.menus.create({ ...item, contexts: ['message_list'] });
  }
}

// The project list follows the server: rebuilt when the menu opens if it is over a minute old.
browser.menus.onShown.addListener(async (info) => {
  if (!info.contexts.includes('message_list') || Date.now() - cache.at < TREE_MAX_AGE) return;
  await buildMenu();
  browser.menus.refresh();
});

async function* selectedMessages(info) {
  let page = info.selectedMessages;
  while (page) {
    for (const message of page.messages) yield message;
    page = page.id ? await browser.messages.continueList(page.id) : null;
  }
}

async function fileMail(header, action, target, people) {
  const msgId = header.headerMessageId || '';
  const author = parseAuthor(header.author);
  const known = author.email ? people.find((p) => (p.email || '').toLowerCase() === author.email) : null;
  let text = '';
  try {
    text = plainBody(await browser.messages.getFull(header.id));
  } catch {
    /* body unreadable (encrypted…): subject and author are enough */
  }
  const entryId = msgId ? await stableId(msgId, 'entry') : crypto.randomUUID().replaceAll('-', '');
  const entry = await api(
    'POST',
    '/api/v2/entries',
    entryForMail({ id: entryId, header, text, target, personIds: known ? [known.id] : [] })
  );
  if (action === 'task') {
    const taskId = msgId ? await stableId(msgId, 'task') : crypto.randomUUID().replaceAll('-', '');
    await api('POST', '/api/v2/tasks', {
      id: taskId,
      title: (header.subject || '(sans objet)').trim().slice(0, 500),
      ...(entry.project_id ? { project_id: entry.project_id } : { space_id: entry.space_id }),
      origin_entry_id: entry.id,
      person_ids: known ? [known.id] : []
    });
  }
  return entry;
}

function placeName(tree, target) {
  for (const space of tree?.spaces || []) {
    if (target.space_id === space.id) return space.name;
    const project = space.projects.find((p) => p.id === target.project_id);
    if (project) return project.name;
  }
  return 'P.IGE';
}

browser.menus.onClicked.addListener(async (info) => {
  if (info.menuItemId === 'configure') {
    browser.runtime.openOptionsPage();
    return;
  }
  const choice = parseMenuId(info.menuItemId);
  if (!choice) return;
  let known;
  try {
    known = await knowledge();
  } catch {
    notify('Serveur injoignable', 'Rien n’a été envoyé. Vérifie la connexion et réessaie.');
    return;
  }
  let done = 0;
  const failures = [];
  for await (const header of selectedMessages(info)) {
    try {
      await fileMail(header, choice.action, choice.target, known.people);
      done += 1;
    } catch (err) {
      failures.push(String(err?.message || err));
    }
  }
  const where = placeName(known.tree, choice.target);
  if (done) await refreshOpenTabs();
  if (failures.length) {
    notify('Envoi incomplet', `${failures.length} sur ${done + failures.length} non envoyés (${failures[0]}).`);
  } else if (choice.action === 'task') {
    notify(done > 1 ? `${done} tâches créées` : 'Tâche créée', `Dans ${where}.`);
  } else {
    notify(done > 1 ? `${done} mails notés` : 'Mail noté', `Dans le journal, ${where}.`);
  }
});

async function refreshOpenTabs() {
  const { serverUrl } = await settings();
  const origin = originOf(serverUrl);
  if (!origin) return;
  for (const tab of await browser.tabs.query({ url: `${origin}/*` })) {
    browser.tabs.sendMessage(tab.id, { type: 'refresh' }).catch(() => {
      /* tab without the bridge (still loading): it refreshes when shown */
    });
  }
}

function notify(title, message) {
  browser.notifications.create({ type: 'basic', iconUrl: 'icons/icon-64.png', title, message });
}

// ------------------------------------------------------------------ lifecycle

async function setup() {
  cache = { at: 0, tree: null, people: [] };
  await ensureSpace();
  await registerBridge();
  await buildMenu();
}

browser.runtime.onInstalled.addListener(() => void setup());
browser.runtime.onStartup.addListener(() => void setup());
browser.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && ('serverUrl' in changes || 'token' in changes)) void setup();
});
