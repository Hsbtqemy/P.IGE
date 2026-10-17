// P.IGE for Thunderbird.
// - Adds a P.IGE button to the Spaces toolbar, opening the web app in a tab.
// - Message list context menu: create a task from each selected email, linked by its
//   Message-ID header (stable across restarts and folder moves).
// - Bridge: the web app asks, through bridge.js, to reopen the email behind a task.

const SPACE_NAME = 'pige';
const MENU_ID = 'pige-create-task';
const BRIDGE_ID = 'pige-bridge';

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

function newId() {
  return crypto.randomUUID().replaceAll('-', '');
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
  if (existing) {
    await browser.spaces.update(existing.id, { url: `${serverUrl}/` }, button);
  } else {
    await browser.spaces.create(SPACE_NAME, { url: `${serverUrl}/` }, button);
  }
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
    {
      id: BRIDGE_ID,
      matches: [`${origin}/*`],
      js: ['bridge.js'],
      runAt: 'document_idle',
      persistAcrossSessions: false
    }
  ]);
}

browser.runtime.onMessage.addListener(async (message, sender) => {
  if (message?.type !== 'open-mail') return;
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
});

// ------------------------------------------------------------------ menu

function createMenu() {
  browser.menus.create({ id: MENU_ID, title: 'Créer une tâche P.IGE', contexts: ['message_list'] }, () => {
    // Ignore "duplicate id" when the menu survived a restart.
    void browser.runtime.lastError;
  });
}

async function* selectedMessages(info) {
  let page = info.selectedMessages;
  while (page) {
    for (const message of page.messages) yield message;
    page = page.id ? await browser.messages.continueList(page.id) : null;
  }
}

async function createTask(serverUrl, token, header) {
  const response = await fetch(`${serverUrl}/api/tasks`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      id: newId(),
      title: (header.subject || '(sans objet)').slice(0, 500),
      mail_message_id: header.headerMessageId ? `<${header.headerMessageId}>` : undefined
    })
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
}

browser.menus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== MENU_ID) return;
  const { serverUrl, token } = await settings();
  if (!serverUrl || !token) {
    notify('P.IGE n’est pas configuré', 'Renseigne l’adresse du serveur et le jeton dans les options de l’extension.');
    browser.runtime.openOptionsPage();
    return;
  }
  let created = 0;
  let failed = 0;
  for await (const header of selectedMessages(info)) {
    try {
      await createTask(serverUrl, token, header);
      created += 1;
    } catch {
      failed += 1;
    }
  }
  if (failed) {
    notify('Tâches non créées', `${failed} sur ${created + failed} n’ont pas pu être envoyées. Vérifie la connexion et le jeton.`);
  } else {
    notify(created > 1 ? `${created} tâches créées` : 'Tâche créée', 'Elle est dans la boîte de réception de P.IGE.');
  }
});

function notify(title, message) {
  browser.notifications.create({ type: 'basic', iconUrl: 'icons/icon-64.png', title, message });
}

// ------------------------------------------------------------------ lifecycle

async function setup() {
  await ensureSpace();
  await registerBridge();
}

browser.runtime.onInstalled.addListener(() => {
  createMenu();
  void setup();
});
browser.runtime.onStartup.addListener(() => void setup());
browser.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && ('serverUrl' in changes || 'token' in changes)) void setup();
});
