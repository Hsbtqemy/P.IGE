// P.IGE for Thunderbird.
// - Adds a P.IGE button to the Spaces toolbar, opening the journal in a tab.
// - Message list context menu « P.IGE »: create a task, or note the mail in the journal,
//   in « À trier » or in a chosen project. Linked by the Message-ID header (stable across
//   restarts and folder moves); the same mail never creates the same thing twice.
// - Bridge: the web app asks, through bridge.js, to reopen the email behind an entry.
// - Follow-up: a reply sent to a mail a task came from goes into that task's « Suivi »
//   (option, on by default); « Ajouter au suivi de la tâche » does it by hand for any mail.

import { entryForMail, followUpFor, menuItems, parseAuthor, parseMenuId, parseReferences, plainBody, stableId } from './lib.js';

const SPACE_NAME = 'pige';
const ROOT_MENU = 'pige';
const BRIDGE_ID = 'pige-bridge';
const TREE_MAX_AGE = 60_000;
// Where « P.IGE » appears: the message list (any folder, saved search or quick filter),
// and a displayed mail (its own tab or window, or opened from search results).
const CONTEXTS = ['message_list', 'page', 'selection'];

let cache = { at: 0, tree: null, people: [] };

async function settings() {
  const { serverUrl = '', token = '', followReplies = true } = await browser.storage.local.get([
    'serverUrl',
    'token',
    'followReplies'
  ]);
  return { serverUrl: serverUrl.replace(/\/+$/, ''), token, followReplies };
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
  if (message?.type === 'open-mail') return openMail(message, sender);
  // The button on a displayed mail (popup.html, inside the extension only).
  if (sender.id !== browser.runtime.id || !String(sender.url || '').startsWith(browser.runtime.getURL(''))) return undefined;
  if (message?.type === 'popup-init') return popupInit();
  if (message?.type === 'popup-action') return popupAction(message);
  return undefined;
});

async function popupInit() {
  const { serverUrl, token } = await settings();
  if (!serverUrl || !token) return { configured: false };
  try {
    const { tree } = await knowledge();
    return { configured: true, tree };
  } catch {
    return { configured: true, offline: true };
  }
}

async function* listOf(messages) {
  for (const m of messages) yield m;
}

async function popupAction({ action, target, tabId }) {
  const shown = await displayedMessages({ id: tabId });
  if (!shown.length) return { ok: false, error: 'Aucun mail affiché.' };
  if (!['task', 'note', 'follow'].includes(action)) return { ok: false };
  // Answer at once so the popup closes; the outcome comes as a notification.
  const work = action === 'follow' ? followMails(listOf(shown)) : fileMails({ action, target }, listOf(shown));
  work.catch((err) => notify('Rien n’a été envoyé', String(err?.message || err)));
  return { ok: true };
}

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
  browser.menus.create({ id: ROOT_MENU, title: 'P.IGE', contexts: CONTEXTS });
  const { serverUrl, token } = await settings();
  if (!serverUrl || !token) {
    browser.menus.create({ id: 'configure', parentId: ROOT_MENU, title: 'Configurer l’extension…', contexts: CONTEXTS });
    return;
  }
  browser.menus.create({ id: 'task', parentId: ROOT_MENU, title: 'Créer une tâche', contexts: CONTEXTS });
  browser.menus.create({ id: 'note', parentId: ROOT_MENU, title: 'Noter dans le journal', contexts: CONTEXTS });
  browser.menus.create({ id: 'follow', parentId: ROOT_MENU, title: 'Ajouter au suivi de la tâche', contexts: CONTEXTS });
  let tree = null;
  try {
    tree = (await knowledge()).tree;
  } catch {
    browser.menus.create({ id: 'offline', parentId: ROOT_MENU, title: 'Serveur injoignable', enabled: false, contexts: CONTEXTS });
    return;
  }
  for (const action of ['task', 'note']) {
    for (const item of menuItems(tree, action, action)) browser.menus.create({ ...item, contexts: CONTEXTS });
  }
}

// The project list follows the server: rebuilt when the menu opens if it is over a minute old.
browser.menus.onShown.addListener(async (info, tab) => {
  // Hidden only in web pages (the P.IGE tab or any site): everywhere mails are shown,
  // including search results, it is there.
  const onMail = info.contexts.includes('message_list') || tab?.type !== 'content';
  if (onMail && Date.now() - cache.at >= TREE_MAX_AGE) await buildMenu();
  await browser.menus.update(ROOT_MENU, { visible: onMail });
  browser.menus.refresh();
});

/** The mails shown in a tab (a message tab or window, or the preview pane). */
async function displayedMessages(tab) {
  if (!tab?.id) return [];
  try {
    const shown = await browser.messageDisplay.getDisplayedMessages(tab.id);
    return Array.isArray(shown) ? shown : shown?.messages || [];
  } catch {
    return [];
  }
}

async function* selectedMessages(info, tab) {
  let page = info.selectedMessages;
  if (!page) {
    // Right-click in a displayed mail: that mail; else what the tab has selected.
    const shown = await displayedMessages(tab);
    if (shown.length) {
      for (const message of shown) yield message;
      return;
    }
    try {
      page = await browser.mailTabs.getSelectedMessages(tab.id);
    } catch {
      return;
    }
  }
  while (page) {
    for (const message of page.messages) yield message;
    page = page.id ? await browser.messages.continueList(page.id) : null;
  }
}

/** The mail's text: its plain part, else its HTML part turned into text, else ''. */
async function mailText(messageId) {
  try {
    const parts = await browser.messages.listInlineTextParts(messageId);
    const plain = parts.find((p) => p.contentType === 'text/plain' && p.content?.trim());
    if (plain) return plain.content;
    const html = parts.find((p) => p.contentType === 'text/html' && p.content?.trim());
    if (html) return await browser.messengerUtilities.convertToPlainText(html.content);
  } catch {
    /* older API or unreadable part: try the raw structure */
  }
  try {
    return plainBody(await browser.messages.getFull(messageId));
  } catch {
    return ''; // body unreadable (encrypted…): subject and author are enough
  }
}

async function fileMail(header, action, target, people) {
  const msgId = header.headerMessageId || '';
  const author = parseAuthor(header.author);
  const known = author.email ? people.find((p) => (p.email || '').toLowerCase() === author.email) : null;
  const text = await mailText(header.id);
  let attachments = [];
  try {
    attachments = await browser.messages.listAttachments(header.id);
  } catch {
    /* no list: the text is enough */
  }
  const entryId = msgId ? await stableId(msgId, 'entry') : crypto.randomUUID().replaceAll('-', '');
  const entry = await api(
    'POST',
    '/api/v2/entries',
    entryForMail({ id: entryId, header, text, attachments, target, personIds: known ? [known.id] : [] })
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

browser.menus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'configure') {
    browser.runtime.openOptionsPage();
    return;
  }
  if (info.menuItemId === 'follow') {
    await followSelected(info, tab);
    return;
  }
  const choice = parseMenuId(info.menuItemId);
  if (!choice) return;
  await fileMails(choice, selectedMessages(info, tab));
});

/** « Créer une tâche » / « Noter dans le journal » for some mails (an async iterable). */
async function fileMails(choice, headers) {
  let known;
  try {
    known = await knowledge();
  } catch {
    notify('Serveur injoignable', 'Rien n’a été envoyé. Vérifie la connexion et réessaie.');
    return;
  }
  let done = 0;
  const failures = [];
  for await (const header of headers) {
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
}

/** Ask open P.IGE pages to reload what changed. Filtering tabs by address would need the
 * « tabs » permission: every tab is asked, and only those running the bridge (P.IGE pages)
 * answer. Never fails: what was sent has been sent. */
async function refreshOpenTabs() {
  try {
    for (const tab of await browser.tabs.query({})) {
      browser.tabs.sendMessage(tab.id, { type: 'refresh' }).catch(() => {
        /* not a P.IGE page, or still loading: nothing to do */
      });
    }
  } catch {
    /* no tab list: the pages refresh when shown */
  }
}

function notify(title, message) {
  browser.notifications.create({ type: 'basic', iconUrl: 'icons/icon-64.png', title, message });
}

// ------------------------------------------------------------------ follow-up

/** The References of a message (its In-Reply-To and References headers). */
async function referencesOf(messageId) {
  try {
    const full = await browser.messages.getFull(messageId);
    const h = full.headers || {};
    return parseReferences(h['in-reply-to'] || [], h.references || []);
  } catch {
    return [];
  }
}

async function attachmentsOf(messageId) {
  try {
    return await browser.messages.listAttachments(messageId);
  } catch {
    return [];
  }
}

function isSentFolder(folder) {
  if (!folder) return false;
  return folder.type === 'sent' || (Array.isArray(folder.specialUse) && folder.specialUse.includes('sent'));
}

/** « Ajouter au suivi de la tâche »: the selected mails, sent or received, into their task. */
async function followSelected(info, tab) {
  await followMails(selectedMessages(info, tab));
}

async function followMails(headers) {
  let added = 0;
  let unknown = 0;
  let origin = 0;
  const failures = [];
  let taskTitle = '';
  for await (const header of headers) {
    if (!header.headerMessageId) continue;
    try {
      const references = await referencesOf(header.id);
      const sent = isSentFolder(header.folder);
      const result = await api(
        'POST',
        '/api/v2/mail-followups',
        followUpFor({
          messageId: header.headerMessageId,
          references,
          direction: sent ? 'sent' : 'received',
          date: header.date ? new Date(header.date) : new Date(),
          author: parseAuthor(header.author).name || parseAuthor(header.author).email,
          recipients: header.recipients,
          subject: header.subject,
          text: await mailText(header.id),
          attachments: await attachmentsOf(header.id)
        })
      );
      added += 1;
      taskTitle = result.task.title;
    } catch (err) {
      const text = String(err?.message || err);
      if (text.startsWith('HTTP 404')) unknown += 1;
      else if (text.startsWith('HTTP 409')) origin += 1;
      else failures.push(text);
    }
  }
  if (added) await refreshOpenTabs();
  if (failures.length) notify('Suivi incomplet', `${failures.length} mail(s) non ajouté(s) (${failures[0]}).`);
  else if (added) notify('Ajouté au suivi', added > 1 ? `${added} mails, tâche « ${taskTitle} ».` : `Tâche « ${taskTitle} ».`);
  if (unknown) notify('Pas de tâche liée', 'Ce mail ne répond à aucun mail dont tu as fait une tâche.');
  if (origin) {
    notify(
      'C’est le mail de la tâche',
      'Il est déjà en tête de la tâche. Le suivi sert aux réponses : la tienne, ou celle de ton interlocuteur.'
    );
  }
}

// Replies being sent: what they answer and their text, kept until the send succeeds.
const sending = new Map();

browser.compose.onBeforeSend.addListener(async (tab, details) => {
  if (!details.relatedMessageId || !String(details.type || '').startsWith('reply')) return;
  const { followReplies, serverUrl, token } = await settings();
  if (!followReplies || !serverUrl || !token) return;
  let text = details.isPlainText ? details.plainTextBody || '' : '';
  if (!text && details.body) {
    try {
      text = await browser.messengerUtilities.convertToPlainText(details.body);
    } catch {
      text = '';
    }
  }
  let attachments = [];
  try {
    attachments = await browser.compose.listAttachments(tab.id);
  } catch {
    /* no list */
  }
  const to = (Array.isArray(details.to) ? details.to : [details.to]).filter((x) => typeof x === 'string');
  sending.set(tab.id, { relatedMessageId: details.relatedMessageId, to, subject: details.subject, text, attachments });
});

browser.compose.onAfterSend.addListener(async (tab, sendInfo) => {
  const pending = sending.get(tab.id);
  sending.delete(tab.id);
  if (!pending || sendInfo.error) return;
  try {
    const related = await browser.messages.get(pending.relatedMessageId);
    if (!related?.headerMessageId) return;
    const references = [`<${related.headerMessageId}>`, ...(await referencesOf(related.id))];
    const sentId = sendInfo.headerMessageId || sendInfo.messages?.[0]?.headerMessageId || `${crypto.randomUUID()}@pige.local`;
    const result = await api(
      'POST',
      '/api/v2/mail-followups',
      followUpFor({
        messageId: sentId,
        references,
        direction: 'sent',
        date: new Date(),
        author: '',
        recipients: pending.to,
        subject: pending.subject,
        text: pending.text,
        attachments: pending.attachments
      })
    );
    await refreshOpenTabs();
    notify('Réponse ajoutée au suivi', `Tâche « ${result.task.title} ».`);
  } catch {
    /* no task behind this mail (404), or server unreachable: nothing to say */
  }
});

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
