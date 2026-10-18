# Déployer la preuve de concept P.IGE sur le VPS

Ce guide installe le serveur P.IGE sur le VPS d'Improliante, sous un utilisateur système
séparé, avec **des données de test uniquement**. Il ne touche ni à Improliante ni à tes
données P.IGE actuelles. Compter environ une heure.

Remplace partout `pige.example.org` par le sous-domaine choisi.

## 1. Sous-domaine

Crée chez ton registrar un enregistrement `A` (et `AAAA` si le VPS a une IPv6) de
`pige.example.org` vers l'adresse du VPS. Vérifie avec `dig +short pige.example.org`.

## 2. Utilisateur et dossiers

```sh
sudo adduser --system --group --home /opt/pige pige
sudo install -d -o pige -g pige -m 0750 /opt/pige/app /var/lib/pige /var/lib/pige/data
sudo install -d -o root -g pige -m 0750 /etc/pige
```

## 3. Code et environnement Python (3.11 ou plus)

Sur Ubuntu, le module venv est un paquet à part : `sudo apt install python3-venv git`.

```sh
sudo -u pige git clone --branch poc https://github.com/Hsbtqemy/P.IGE.git /opt/pige/app
sudo -u pige python3 -m venv /opt/pige/venv
sudo -u pige /opt/pige/venv/bin/pip install "/opt/pige/app[server]"
```

## 4. Interface web

Elle se compile avec Node 22.17 ou plus (exigé par SvelteKit 3). Si le Node du système est
plus ancien, installe un Node 22 réservé à P.IGE, sans toucher à celui du système :

```sh
cd /tmp
ARCH=$(uname -m | sed 's/x86_64/x64/; s/aarch64/arm64/')
TARBALL=$(curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep -o "node-v22[0-9.]*-linux-$ARCH.tar.xz" | head -1)
curl -fsSLO "https://nodejs.org/dist/latest-v22.x/$TARBALL"
curl -fsSL https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt | grep " $TARBALL\$" | sha256sum -c -
sudo mkdir -p /opt/pige/node && sudo tar -xJf "$TARBALL" -C /opt/pige/node --strip-components=1
sudo chown -R root:root /opt/pige/node
/opt/pige/node/bin/node --version
```

Puis, sur le VPS :

```sh
sudo -u pige sh -c 'export PATH=/opt/pige/node/bin:$PATH; cd /opt/pige/app/web && npm ci && npm run build'
```

(Si le Node du système suffit, la partie `export PATH=…;` est inutile.)

Sans Node sur le VPS : lance les deux dernières commandes sur ton ordinateur, puis copie
le dossier `web/build` vers `/opt/pige/app/web/build`.

## 5. Secrets

```sh
sudo -u pige /opt/pige/venv/bin/python -m pige.server hash-password   # mot de passe d'au moins 12 caractères
sudo -u pige /opt/pige/venv/bin/python -m pige.server new-secret
sudo -u pige /opt/pige/venv/bin/python -m pige.server new-token       # garde le jeton pour Thunderbird
sudo install -m 0640 -o root -g pige /opt/pige/app/deploy/pige.env.example /etc/pige/pige.env
sudo nano /etc/pige/pige.env
```

Colle les trois valeurs dans `/etc/pige/pige.env` (pour le jeton, seulement son
empreinte).

## 6. Service

```sh
sudo cp /opt/pige/app/deploy/pige.service /etc/systemd/system/pige.service
sudo systemctl daemon-reload
sudo systemctl enable --now pige
curl -s http://127.0.0.1:8765/api/health      # doit répondre {"status":"ok"}
```

En cas de souci : `journalctl -u pige -n 50`.

## 7. Nginx et HTTPS

Le fichier `deploy/nginx-pige.conf` contient le site et, en commentaire, deux petits
fichiers annexes (limite de débit et en-têtes du proxy) à créer aux chemins indiqués.
Nginx refuse un bloc HTTPS sans certificat : l'installation se fait donc en deux temps.

a. Certificat d'abord, avec seulement le bloc du port 80 :

```sh
sudo cp /opt/pige/app/deploy/nginx-pige.conf /etc/nginx/sites-available/pige
sudo nano /etc/nginx/sites-available/pige   # remplacer pige.example.org, commenter tout le bloc « listen 443 »
sudo ln -s /etc/nginx/sites-available/pige /etc/nginx/sites-enabled/pige
sudo nginx -t && sudo systemctl reload nginx
sudo mkdir -p /var/www/html
sudo certbot certonly --webroot -w /var/www/html -d pige.example.org
```

b. Puis HTTPS : crée les deux fichiers annexes, décommente le bloc 443 et recharge.

```sh
sudo nginx -t && sudo systemctl reload nginx
```

Avec un nginx antérieur à 1.25.1 (Debian 12, Ubuntu 24.04), remplace `http2 on;` par
`listen 443 ssl http2;`, comme indiqué dans le fichier.

## 8. Téléphone et iPad

Ouvre `https://pige.example.org` et connecte-toi.

- **Android (Chrome)** : menu ⋮, puis « Ajouter à l'écran d'accueil » ou « Installer l'application ».
- **iPad (Safari)** : bouton Partager, puis « Sur l'écran d'accueil ».

## 9. Thunderbird

Fabrique le fichier de l'extension sur ton ordinateur :

```sh
cd thunderbird
zip -r ../pige-thunderbird.xpi . -x '*.DS_Store'
```

Dans Thunderbird : Outils, Modules complémentaires et thèmes, roue dentée,
« Installer un module depuis un fichier », choisis `pige-thunderbird.xpi`. Dans les options
de l'extension, saisis `https://pige.example.org` et le jeton, puis accepte l'accès au site.
Le bouton P.IGE apparaît dans la barre des espaces, à gauche.

## 10. Vérifier les critères de réussite

1. Sur le téléphone en mode avion, crée une tâche : elle s'affiche « En attente d'envoi ».
2. Coupe le mode avion : elle part seule, sans doublon.
3. Elle apparaît dans l'onglet P.IGE de Thunderbird.
4. Clic droit sur un mail, « Créer une tâche P.IGE » : la tâche apparaît, et
   « Ouvrir le mail » la ramène au mail.
5. Dans une fenêtre privée, `https://pige.example.org/api/tasks` répond 401.

Note ce qui échoue, en particulier le point 4 : c'est là que se trouvent les inconnues
de la preuve de concept (injection du script dans l'onglet de l'espace).

## Mettre à jour

```sh
sudo -u pige git -C /opt/pige/app pull
sudo -u pige /opt/pige/venv/bin/pip install "/opt/pige/app[server]"
sudo -u pige sh -c 'export PATH=/opt/pige/node/bin:$PATH; cd /opt/pige/app/web && npm ci && npm run build'
sudo systemctl restart pige
```

## Clés d'accès (passkeys)

Elles remplacent le mot de passe sur les appareils qui les gèrent (Touch ID, Face ID,
Windows Hello, téléphone Android). Une clé est liée au nom du site : indiquer son adresse
exacte dans l'environnement, une fois.

```sh
grep -q '^PIGE_PUBLIC_ORIGIN=' /etc/pige/pige.env \
  || echo 'PIGE_PUBLIC_ORIGIN=https://pige.example.org' | sudo tee -a /etc/pige/pige.env
sudo systemctl restart pige
```

Ensuite, dans l'interface : **Réglages › Ajouter une clé d'accès sur cet appareil**, sur
chaque appareil (une clé créée sur l'iPhone sert aussi sur l'iPad et le Mac si le
trousseau iCloud est actif). Le mot de passe reste possible.

## Limites connues de la preuve de concept

- Les sessions sont enregistrées côté serveur (`auth.sqlite3`) : « Se déconnecter » et
  « Réglages › Appareils connectés » les ferment vraiment. En dernier recours : changer
  le mot de passe, ou régler `PIGE_SESSIONS_NOT_BEFORE`, puis redémarrer.
- Le serveur et l'application de bureau Tkinter ne doivent pas écrire dans le même
  dossier de données : ils ne se verrouillent pas encore l'un l'autre (étape 2 du plan).

## Retour arrière

`sudo systemctl disable --now pige`, retirer le site Nginx, supprimer `/opt/pige`,
`/var/lib/pige` et `/etc/pige`. Rien d'autre sur le VPS n'est modifié.


## Nouveau modèle de données (API /api/v2)

Depuis l'étape 3, le serveur ouvre aussi une base SQLite `pige.sqlite3` dans `PIGE_DATA_DIR`
(avec ses fichiers `-wal` et `-shm`). Elle est créée et mise à jour toute seule au démarrage.
Les anciennes routes `/api/tasks` (appli web actuelle, extension Thunderbird) continuent
d'utiliser les fichiers JSON.

### Sauvegarde quotidienne

Une copie simple de `pige.sqlite3` pendant que le service tourne peut être incohérente :
le script `pige-sauvegarde` utilise la sauvegarde intégrée de SQLite, archive aussi les
fichiers JSON, et garde 14 jours dans `/var/lib/pige/sauvegardes`.

```sh
sudo install -m 755 /opt/pige/app/deploy/pige-sauvegarde /usr/local/bin/pige-sauvegarde
sudo cp /opt/pige/app/deploy/pige-sauvegarde.service /opt/pige/app/deploy/pige-sauvegarde.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pige-sauvegarde.timer
sudo systemctl start pige-sauvegarde.service      # une première sauvegarde tout de suite
sudo ls -l /var/lib/pige/sauvegardes
```

Restaurer : arrêter le service, remplacer `pige.sqlite3` par la copie voulue (et supprimer
`pige.sqlite3-wal` et `pige.sqlite3-shm`), redémarrer.

Ces sauvegardes restent sur le VPS : pour se protéger d'une panne du serveur lui-même,
les recopier ailleurs de temps en temps (par exemple `scp` vers un autre ordinateur).

Variable facultative : `PIGE_TIMEZONE` (par défaut `Europe/Paris`), qui découpe les journées
dans les relevés de temps.
