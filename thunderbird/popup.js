// The P.IGE button on a displayed mail: the same actions as the right-click menu, for the
// mail shown (works wherever a mail is shown, search results included).
const form = document.getElementById('form');
const place = document.getElementById('place');
const status = document.getElementById('status');

function option(value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label;
  return o;
}

async function init() {
  const info = await browser.runtime.sendMessage({ type: 'popup-init' });
  if (!info?.configured) {
    status.textContent = 'Configure d’abord l’extension (adresse et jeton).';
    browser.runtime.openOptionsPage();
    return;
  }
  if (info.offline) {
    status.textContent = 'Serveur injoignable.';
    return;
  }
  const spaces = info.tree?.spaces || [];
  const inbox = spaces.find((s) => s.name.toLocaleLowerCase('fr') === 'à trier') || spaces[0];
  if (inbox) place.append(option(`s:${inbox.id}`, `${inbox.name}`));
  for (const space of spaces) {
    const group = document.createElement('optgroup');
    group.label = space.name;
    if (space.id !== inbox?.id) group.append(option(`s:${space.id}`, `${space.name} (sans projet)`));
    for (const p of space.projects) group.append(option(`p:${p.id}`, `${p.parent_id ? '  ' : ''}${p.name}`));
    if (group.children.length) place.append(group);
  }
  form.hidden = false;
  status.textContent = '';
}

form.addEventListener('click', async (event) => {
  const action = event.target?.dataset?.action;
  if (!action) return;
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  const value = place.value;
  const target = value.startsWith('p:') ? { project_id: value.slice(2) } : { space_id: value.slice(2) };
  status.textContent = 'Envoi…';
  for (const b of form.querySelectorAll('button')) b.disabled = true;
  const result = await browser.runtime.sendMessage({ type: 'popup-action', action, target, tabId: tab?.id });
  if (result?.ok) window.close();
  else {
    status.textContent = result?.error || 'Rien n’a été envoyé.';
    for (const b of form.querySelectorAll('button')) b.disabled = false;
  }
});

void init();
