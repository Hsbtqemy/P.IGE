# Modèle d'organisation et interface

Décisions prises le 17 octobre 2026, à partir des maquettes et des données réelles de P.IGE (janvier à mars 2026). Ce document sert de référence pour l'étape 3 (service assaini) et l'étape 6 (interface web).

Maquettes : https://claude.ai/artifact/SZD7CLYPvCDiQyiqZsELBp (privées), ligne « Nouveau modèle ».

## Constats sur l'usage actuel

- L'arborescence sert de classement principal, sur 3 à 4 niveaux. Des préfixes (`- `, `Z - `, `- X -`) forcent l'ordre et distinguent les structures des projets.
- Les tags et le champ `group` répètent l'arbre, avec des variantes (`-A`, `- A`, `FoReLLIS; PPrim`).
- Les personnes sont saisies en texte libre, avec plusieurs graphies et séparateurs ; certains projets (Doctorant.es) sont en fait des listes de personnes.
- Le contenu le plus riche est dans les notes des tâches ; beaucoup d'entrées ne contiennent que le modèle vide, qui recopie les métadonnées.
- 6 tâches sur 40 ont une échéance ; certaines forment des suites numérotées.
- `context_status` (« en cours ») sert de marque-page sur les entrées.
- Aucun temps enregistré au minuteur.
- Bugs : l'abonnement d'agenda a créé 7 projets « 📅 UPoitiers » en double ; un titre est mal encodé ; projets de test restés en place.
- L'usage s'arrête après deux mois : le modèle doit coûter moins qu'il ne rapporte.

## Modèle

Chaque niveau a un seul rôle.

| Niveau | Rôle | Remarques |
| --- | --- | --- |
| Espace | Structure de rattachement (FoReLLIS, MIMMOC, MSHS, Perso et admin, Développement) | Ordre manuel. Peut recevoir des entrées générales. |
| Projet | Travail identifié | Au plus un niveau de sous-projet. Équipe (A, B…) en attribut filtrable, pas en dossier. États : actif, en veille, clos. Liens en en-tête. |
| Tâche | Ce qui est à faire | Ordre manuel. Étapes cochables à l'intérieur. États : ouverte, en cours, en attente (de quelqu'un), faite. |
| Entrée | Fait daté (note, réunion, décision, activité) | Plus d'état : ce qui reste à faire devient une tâche. Peut être liée à une tâche, ce qui forme le fil daté de la tâche. |
| Personne | Fiche à part entière | Liée aux entrées, tâches, projets et mails. « J'attends d'elle », « Je lui dois », rappel pour soi seulement. Annuaire interne, LDAP en lecture. |
| Étiquette | Ce qui traverse les espaces | Sur personnes, entrées, tâches. Épinglable : apparaît dans la colonne de gauche et dans Ctrl K. Ne répète jamais l'espace. |

## Journal

- **Feuillet du jour** : la journée s'écrit d'un seul tenant. Chaque paragraphe devient une entrée, rangée d'après son contenu :
  - nom de projet reconnu tel quel ;
  - `@personne`, `#étiquette` ;
  - `[ ]` crée une tâche, ou reconnaît une tâche existante ;
  - `Décision :` crée une décision.
- L'heure en marge vient de l'agenda ou du minuteur.
- **Rédaction longue** : page dédiée, Markdown affiché mis en forme (syntaxe visible sur la ligne en cours seulement), plan, versions, modèles (compte rendu, note de cadrage), export PDF, Word, Markdown, envoi par Thunderbird sans envoi automatique.
- Le journal d'un projet, la fiche d'une personne et le fil d'une tâche sont des vues filtrées de la même chronologie.

## Temps

- Plusieurs minuteurs peuvent tourner en même temps.
- Chevauchement : temps **partagé** par défaut (le total suit la présence), ou « compté pour les deux », ou « ne compter qu'ici ».
- Les réunions de l'agenda se comptent seules.
- « Ma journée » : frise à pistes parallèles, correction après coup, puis validation. Les bilans regroupent par espace, projet ou étiquette.

## Navigation

- Vues : Aujourd'hui, Journal, Tâches, Personnes, Agenda, À trier.
- Ctrl K : aller à un projet, une tâche, une personne, une étiquette, et lancer une action dessus.
- Tâches regroupées par projet ; les tâches en cours depuis longtemps remontent.
- Signal « rien de nouveau depuis… » sur les projets et les personnes.

## Apparence

- Mode « feuillet » : fond papier, titres en Newsreader, texte en Atkinson Hyperlegible Next, accent bordeaux `#7a2e3a`.
- Échéances en retard en ocre `#8a5300`, décisions en bleu ardoise `#3b5168`.
- Modes sobres clair et sombre conservés.

## Plus tard

- Modèles de projet réutilisables (exemple : parcours de valorisation inventaire, ShareDocs, métadonnées, Nakala, site).
- Revue hebdomadaire : ce qui a bougé, ce qui dort, ce qu'on attend, la semaine suivante.
- Bilan d'activité par espace et par période.

## Reprise des données

Non décidée. Piste : importer l'existant en lecture seule dans un espace « Archives » et reclasser au fil de l'eau les tâches encore vivantes, sans conversion automatique de l'historique.
