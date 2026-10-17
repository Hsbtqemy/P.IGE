const form = document.getElementById('form');
const serverInput = document.getElementById('serverUrl');
const tokenInput = document.getElementById('token');
const result = document.getElementById('result');

browser.storage.local.get(['serverUrl', 'token']).then(({ serverUrl = '', token = '' }) => {
  serverInput.value = serverUrl;
  tokenInput.value = token;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  result.textContent = '';
  let url;
  try {
    url = new URL(serverInput.value.trim());
  } catch {
    result.textContent = 'Adresse invalide.';
    return;
  }
  const local = url.hostname === 'localhost' || url.hostname === '127.0.0.1';
  if (url.protocol !== 'https:' && !local) {
    result.textContent = 'L’adresse doit commencer par https://.';
    return;
  }
  // Must run inside the click handler: Thunderbird asks the user to allow access to this site.
  const granted = await browser.permissions.request({ origins: [`${url.origin}/*`] });
  if (!granted) {
    result.textContent = 'Accès au serveur refusé : l’extension ne pourra pas créer de tâches.';
    return;
  }
  const token = tokenInput.value.trim();
  try {
    const response = await fetch(`${url.origin}/api/tasks`, { headers: { Authorization: `Bearer ${token}` } });
    if (response.status === 401) {
      result.textContent = 'Le serveur refuse ce jeton.';
      return;
    }
    if (!response.ok) throw new Error(String(response.status));
  } catch {
    result.textContent = 'Serveur injoignable. Vérifie l’adresse.';
    return;
  }
  await browser.storage.local.set({ serverUrl: url.origin, token });
  result.textContent = 'Enregistré. Le bouton P.IGE est dans la barre des espaces, à gauche.';
});
