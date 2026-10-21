#!/usr/bin/env node
// pige-envoyer — envoie à P.IGE le journal pilote du dépôt courant.
//
//   pige-envoyer               exporte avec pilote et envoie (à lancer dans un dépôt)
//   pige-envoyer --configurer  enregistre l'adresse de P.IGE et le jeton d'accès
//   pige-envoyer --aide        ceci
//
// Le jeton est le même que celui de l'extension Thunderbird. Il est lu dans PIGE_TOKEN
// (et l'adresse dans PIGE_URL), sinon dans ~/.config/pige/envoyer.json (droits 600).
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

if (args.includes("--configurer")) {
  const url = (await ask("Adresse de P.IGE (https://…) : ")).replace(/\/+$/, "");
  if (!/^https:\/\/[^\s/]+/.test(url) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(url)) {
    console.error("L'adresse doit commencer par https://.");
    process.exit(2);
  }
  const token = await ask("Jeton d'accès (celui de Thunderbird, rien ne s'affiche) : ", true);
  if (!token) { console.error("Jeton vide : rien n'est enregistré."); process.exit(2); }
  mkdirSync(join(homedir(), ".config", "pige"), { recursive: true });
  writeFileSync(CONFIG, JSON.stringify({ url, token }, null, 2), { mode: 0o600 });
  try { chmodSync(CONFIG, 0o600); } catch { /* Windows: the user's profile protects it */ }
  console.log(`Enregistré dans ${CONFIG}.`);
  process.exit(0);
}

function settings() {
  let file = {};
  if (existsSync(CONFIG)) {
    try { file = JSON.parse(readFileSync(CONFIG, "utf8")); } catch { /* unreadable: env only */ }
  }
  const url = (process.env.PIGE_URL || file.url || "").replace(/\/+$/, "");
  const token = process.env.PIGE_TOKEN || file.token || "";
  if (!url || !token) {
    console.error("P.IGE n'est pas configuré : lance une fois « pige-envoyer --configurer ».");
    process.exit(2);
  }
  return { url, token };
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
  const shell = process.platform === "win32";
  const tries = [
    ["npx", ["--no-install", "pilote", "exporter", dir]],
    ["npx", ["--yes", "github:Hsbtqemy/pilote", "exporter", dir]],
  ];
  for (const [cmd, argv] of tries) {
    const run = spawnSync(cmd, argv, { encoding: "utf8", shell, stdio: ["ignore", "pipe", "pipe"] });
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

const { url, token } = settings();
const repo = repoName();
const journal = exportJournal();
let response;
try {
  response = await fetch(`${url}/api/v2/code/export?repo=${encodeURIComponent(repo)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: journal,
  });
} catch {
  console.error(`P.IGE injoignable (${new URL(url).host}).`);
  process.exit(1);
}
let body = {};
try { body = await response.json(); } catch { /* not JSON */ }
if (!response.ok) {
  const why = response.status === 401 ? "jeton refusé (relance « pige-envoyer --configurer »)" : body.detail || `HTTP ${response.status}`;
  console.error(`Non envoyé : ${why}`);
  process.exit(1);
}
for (const p of body.projects || []) {
  const days = p.days ? `${p.days} jour${p.days > 1 ? "s" : ""} mis à jour` : "rien de nouveau";
  console.log(`Envoyé à P.IGE · ${repo} → « ${p.project} » : ${days}, ${p.fiches} chantier${p.fiches > 1 ? "s" : ""}.`);
}
