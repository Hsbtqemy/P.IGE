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

```sh
sudo -u pige git clone --branch poc https://github.com/Hsbtqemy/P.IGE.git /opt/pige/app
sudo -u pige python3 -m venv /opt/pige/venv
sudo -u pige /opt/pige/venv/bin/pip install "/opt/pige/app[server]"
```

## 4. Interface web

Elle se compile avec Node 22 ou plus. Sur le VPS :

```sh
cd /opt/pige/app/web
sudo -u pige npm ci
sudo -u pige npm run build
```

Sans Node sur le VPS : lance les deux dernières commandes sur ton ordinateur, puis copie
le dossier `web/build` vers `/opt/pige/app/web/build`.

## 5. Secrets

```sh
cd /opt/pige/app
sudo -u pige /opt/pige/venv/bin/python -m pige.server hash-password   # choisis un mot de passe d'au moins 12 caractères
sudo -u pige /opt/pige/venv/bin/python -m pige.server new-secret
sudo -u pige /opt/pige/venv/bin/python -m pige.server new-token       # garde le jeton pour Thunderbird
```

Copie `deploy/pige.env.example` vers `/etc/pige/pige.env` et colle les trois valeurs
(pour le jeton, seulement son empreinte). Puis :

```sh
sudo chown root:pige /etc/pige/pige.env
sudo chmod 0640 /etc/pige/pige.env
```

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

```sh
sudo cp /opt/pige/app/deploy/nginx-pige.conf /etc/nginx/sites-available/pige
# éditer : remplacer pige.example.org, créer les deux fichiers annexes
sudo ln -s /etc/nginx/sites-available/pige /etc/nginx/sites-enabled/pige
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d pige.example.org
```

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

## Retour arrière

`sudo systemctl disable --now pige`, retirer le site Nginx, supprimer `/opt/pige`,
`/var/lib/pige` et `/etc/pige`. Rien d'autre sur le VPS n'est modifié.
