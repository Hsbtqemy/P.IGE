#!/usr/bin/env node
// pige-envoyer — envoie à P.IGE le journal pilote du dépôt courant.
//
//   pige-envoyer               exporte avec pilote et envoie (à lancer dans un dépôt)
//   pige-envoyer --configurer  enregistre l'adresse de P.IGE et le jeton d'accès
//   pige-envoyer --proxy URL   enregistre un proxy (réseau d'université…), « --proxy aucun » l'enlève
//   pige-envoyer --aide        ceci
//
// Le jeton est le même que celui de l'extension Thunderbird. Il est lu dans PIGE_TOKEN
// (et l'adresse dans PIGE_URL), sinon dans ~/.config/pige/envoyer.json (droits 600).
// Si P.IGE ne répond pas en direct et qu'un proxy est connu (fichier, ou HTTPS_PROXY),
// l'envoi passe par lui (Node 22.21+ ou 24.5+). Chez soi, l'envoi reste direct.
// Rien n'est publié : le journal va du dépôt au serveur P.IGE, public ou privé.
// Aucune dépendance. Node 18+.

import { execFileSync, spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import { createInterface } from "node:readline";

const args = process.argv.slice(2);
const CONFIG = join(homedir(), ".config", "pige", "envoyer.json");

if (args.includes("--aide") || args.includes("--help") || args.includes("-h")) {
  console.log(`pige-envoyer — envoie à P.IGE le journal pilote du dépôt courant.

  pige-envoyer               dans un dépôt : exporte avec pilote, envoie à P.IGE
  pige-envoyer --configurer  enregistre l'adresse de P.IGE et le jeton (une fois)
  pige-envoyer --proxy URL   enregistre un proxy, utilisé seulement si le direct échoue
                             (« --proxy aucun » l'enlève)

Le dépôt doit être relié à un projet dans P.IGE (page du projet › Relier un dépôt de
code). Dans le package.json du dépôt :  "scripts": { "pige": "pige-envoyer" }`);
  process.exit(0);
}

function ask(question, hidden = false) {
  return new Promise((resolve) => {
    const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    if (hidden) {
      // The token is typed without being shown.
      rl._writeToOutput = (s) => { if (s.includes(question)) rl.output.write(s); };
    }
    rl.question(question, (answer) => {
      rl.close();
      if (hidden) process.stdout.write("\n");
      resolve(answer.trim());
    });
  });
}

function readConfig() {
  if (!existsSync(CONFIG)) return {};
  try { return JSON.parse(readFileSync(CONFIG, "utf8")); } catch { return {}; }
}

function saveConfig(config) {
  mkdirSync(join(homedir(), ".config", "pige"), { recursive: true });
  writeFileSync(CONFIG, JSON.stringify(config, null, 2), { mode: 0o600 });
  try { chmodSync(CONFIG, 0o600); } catch { /* Windows: the user's profile protects it */ }
}

const PROXY_RE = /^https?:\/\/[^\s/]+\/?$/;

if (args.includes("--proxy")) {
  const value = (args[args.indexOf("--proxy") + 1] || "").trim();
  const config = readConfig();
  if (value === "aucun" || value === "none") {
    delete config.proxy;
    saveConfig(config);
    console.log("Proxy enlevé : l'envoi sera toujours direct.");
    process.exit(0);
  }
  if (!PROXY_RE.test(value)) {
    console.error("Indique le proxy ainsi : pige-envoyer --proxy http://adresse:port");
    process.exit(2);
  }
  config.proxy = value.replace(/\/+$/, "");
  saveConfig(config);
  console.log(`Proxy enregistré (${config.proxy}) : utilisé seulement quand P.IGE ne répond pas en direct.`);
  process.exit(0);
}

if (args.includes("--configurer")) {
  const url = (await ask("Adresse de P.IGE (https://…) : ")).replace(/\/+$/, "");
  if (!/^https:\/\/[^\s/]+/.test(url) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(url)) {
    console.error("L'adresse doit commencer par https://.");
    process.exit(2);
  }
  const token = await ask("Jeton d'accès (celui de Thunderbird, rien ne s'affiche) : ", true);
  if (!token) { console.error("Jeton vide : rien n'est enregistré."); process.exit(2); }
  const config = readConfig();
  const proxy = (await ask(`Proxy, si ton réseau en impose un (Entrée : ${config.proxy ? `garder ${config.proxy}` : "aucun"}) : `)).replace(/\/+$/, "");
  if (proxy && !PROXY_RE.test(proxy)) { console.error("Proxy : http://adresse:port attendu. Rien n'est enregistré."); process.exit(2); }
  saveConfig({ url, token, ...(proxy || config.proxy ? { proxy: proxy || config.proxy } : {}) });
  console.log(`Enregistré dans ${CONFIG}.`);
  process.exit(0);
}

function settings() {
  const file = readConfig();
  const url = (process.env.PIGE_URL || file.url || "").replace(/\/+$/, "");
  const token = process.env.PIGE_TOKEN || file.token || "";
  if (!url || !token) {
    console.error("P.IGE n'est pas configuré : lance une fois « pige-envoyer --configurer ».");
    process.exit(2);
  }
  const proxy = (file.proxy || process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy || "").trim();
  return { url, token, proxy };
}

/** « owner/name » of the origin remote (GitHub). */
function repoName() {
  let remote = "";
  try {
    remote = execFileSync("git", ["remote", "get-url", "origin"], { encoding: "utf8" }).trim();
  } catch {
    console.error("Pas de dépôt git ici (ou pas de remote « origin »).");
    process.exit(2);
  }
  const m = remote.match(/github\.com[/:]([^/]+)\/(.+?)(?:\.git)?\/?$/);
  if (!m) { console.error(`Remote non GitHub : ${remote}`); process.exit(2); }
  return `${m[1]}/${m[2]}`;
}

/** pilote's journal.json for this repository (the local pilote if installed, else npx). */
function exportJournal() {
  const dir = mkdtempSync(join(tmpdir(), "pige-"));
  const tries = [
    ["--no-install", "pilote", "exporter", dir],
    ["--yes", "github:Hsbtqemy/pilote", "exporter", dir],
  ];
  for (const argv of tries) {
    // Windows runs npx through cmd (npx.cmd): one command line, the temporary folder quoted
    // (the only argument that is not a fixed word). Elsewhere, no shell at all.
    const run =
      process.platform === "win32"
        ? spawnSync(["npx", ...argv.map((a) => (a === dir ? `"${a}"` : a))].join(" "), {
            encoding: "utf8", shell: true, stdio: ["ignore", "pipe", "pipe"],
          })
        : spawnSync("npx", argv, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    const file = join(dir, "journal.json");
    if (run.status === 0 && existsSync(file)) {
      const text = readFileSync(file, "utf8");
      rmSync(dir, { recursive: true, force: true });
      return text;
    }
  }
  rmSync(dir, { recursive: true, force: true });
  console.error("pilote n'a pas pu exporter le journal (dossier pilotage/ absent ? pilote installé ?).");
  process.exit(1);
}

/** Does P.IGE answer directly? A short check, so a network that blocks it costs seconds, not a minute. */
async function reachable(url) {
  try {
    await fetch(`${url}/api/health`, { signal: AbortSignal.timeout(5000) });
    return true;
  } catch {
    return false;
  }
}

/** Node's own proxy support (NODE_USE_ENV_PROXY) exists from 22.21 and 24.5. */
function nodeKnowsProxies() {
  const [major, minor] = process.versions.node.split(".").map(Number);
  return major > 24 || (major === 24 && minor >= 5) || (major === 22 && minor >= 21);
}

// Run in a child Node started with NODE_USE_ENV_PROXY: the journal comes on stdin, the
// token through the environment (never on the command line), the answer back as JSON.
const VIA_PROXY = `
const chunks = [];
for await (const c of process.stdin) chunks.push(c);
try {
  const r = await fetch(process.env.PIGE_POST_URL, {
    method: "POST",
    headers: { Authorization: "Bearer " + process.env.PIGE_TOKEN, "content-type": "application/json" },
    body: Buffer.concat(chunks),
  });
  process.stdout.write(JSON.stringify({ status: r.status, text: await r.text() }));
} catch (e) {
  process.stdout.write(JSON.stringify({ error: String(e?.cause?.code || e?.message || e) }));
}`;

function postViaProxy(target, token, proxy, journal) {
  const run = spawnSync(process.execPath, ["--input-type=module", "-e", VIA_PROXY], {
    input: journal,
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
    env: { ...process.env, NODE_USE_ENV_PROXY: "1", HTTPS_PROXY: proxy, HTTP_PROXY: proxy, PIGE_POST_URL: target, PIGE_TOKEN: token },
  });
  try { return JSON.parse(run.stdout); } catch { return { error: (run.stderr || "").trim().split("\n").pop() || "échec" }; }
}

async function postDirect(target, token, journal) {
  try {
    const r = await fetch(target, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
      body: journal,
    });
    return { status: r.status, text: await r.text() };
  } catch (e) {
    return { error: String(e?.cause?.code || e?.message || e) };
  }
}

const { url, token, proxy } = settings();
const repo = repoName();
const journal = exportJournal();
const target = `${url}/api/v2/code/export?repo=${encodeURIComponent(repo)}`;
const host = new URL(url).host;

let result;
if (await reachable(url)) {
  result = await postDirect(target, token, journal);
} else if (!proxy) {
  console.error(`P.IGE injoignable (${host}).
Si ton navigateur l'ouvre quand même, ton réseau passe sans doute par un proxy :
  pige-envoyer --proxy http://adresse:port`);
  process.exit(1);
} else if (!nodeKnowsProxies()) {
  console.error(`P.IGE injoignable en direct (${host}), et Node ${process.versions.node} ne sait pas passer par un proxy : installe Node 24 (LTS).`);
  process.exit(1);
} else {
  result = postViaProxy(target, token, proxy, journal);
}
if (result.error) {
  console.error(`P.IGE injoignable (${host}${proxy ? `, proxy ${proxy} compris` : ""}) : ${result.error}.`);
  process.exit(1);
}
let body = {};
try { body = JSON.parse(result.text); } catch { /* not JSON */ }
if (result.status < 200 || result.status >= 300) {
  const why = result.status === 401 ? "jeton refusé (relance « pige-envoyer --configurer »)" : body.detail || `HTTP ${result.status}`;
  console.error(`Non envoyé : ${why}`);
  process.exit(1);
}
for (const p of body.projects || []) {
  const days = p.days ? `${p.days} jour${p.days > 1 ? "s" : ""} mis à jour` : "rien de nouveau";
  const open = typeof p.open === "number" ? `${p.open} ouvert${p.open > 1 ? "s" : ""} sur ` : "";
  console.log(`Envoyé à P.IGE · ${repo} → « ${p.project} » : ${days}, ${open}${p.fiches} chantier${p.fiches > 1 ? "s" : ""}.`);
}
