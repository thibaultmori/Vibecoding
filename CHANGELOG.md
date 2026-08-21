# Journal des versions — Passerelle

## 2.2.0 — 2026-08-21 · Pilotage & intégrations avancées (phase 3)

La feuille de route initiale est complète.

- **Page « Pilotage »** : le serveur historise créations, transitions d'étape et décisions (table dédiée, écrite au fil des écritures) et sert des agrégats (`/api/stats`) — MEP par mois (12 mois, complétées par les dates réelles des fiches antérieures), temps moyen par étape, délai médian création→MEP, décisions Go/No-Go, pages DMEX à rafraîchir, synchronisations anciennes.
- **Création de tickets Jira depuis les actions** : bouton « Ticket Jira » sur chaque action (mode partagé) — le serveur appelle `POST /rest/api/3/issue` (vérifié sur la spec du jour) avec description **ADF**, type résolu en id via le nouveau `createmeta`, label `passerelle` (retiré automatiquement si l'écran du projet ne l'accepte pas) ; la clé revient en chip-lien sur l'action et au journal. Projet et type configurables (Paramètres, admin) ; le compte de service doit avoir « Browse projects » + « Create issues ».
- **Synchronisation Atlassian automatique** : le serveur rafraîchit lui-même tickets et pages DMEX toutes les `ATL_SYNC_MINUTES` (défaut 30) et diffuse en SSE — plus besoin du bouton Synchroniser (conservé pour l'immédiat). Choix assumé à la place des webhooks entrants, qui exigeraient d'exposer l'application depuis Internet. Sonde : `POST /api/atlassian/sync-now` (admin).
- **API machine (CMDB/ITSM)** : `GET /api/v1/platforms` (+ `/{id}`) en lecture seule sous jetons dédiés (`API_TOKENS`), avec statut dérivé et score calculés côté serveur.
- **Flux iCalendar** : `GET /api/calendar.ics?token=…` — dates cibles des fiches actives + MEP réalisées (90 j), événements journée entière conformes RFC 5545 (UID stables, fin exclusive, échappement, CRLF pliés). Outlook n'authentifie pas les calendriers abonnés (jeton en URL) ; Outlook web relit le flux depuis le cloud Microsoft — documenté.
- **Export CSV** du portefeuille (fiches filtrées, séparateur `;`, BOM Excel) depuis la vue Plateformes ; **rapport de revue imprimable** enrichi (en-tête d'édition, bloc signatures proposeur / contre-validateur).
- Tests : 179 contrôles automatisés en CI (82 applicatifs, 73 serveur — dont création Jira sur stub avec vérification du corps ADF, stats, synchro auto, API v1, ICS —, 24 relais).

## 2.1.0 — 2026-08-21 · Collaboration & gouvernance (phase 2)

- **Notifications** (mode partagé) : balayage quotidien à heure fixe — un e-mail par équipe (adresse du champ contact) listant ses éléments de checklist dus sous 7 jours ou en retard, plus une synthèse globale (dates cibles dépassées, actions bloquantes en retard, revues à tenir, décisions à contre-valider) vers une adresse de direction et/ou une **carte Teams** (webhook Workflows, format Adaptive Card v1.2 — les connecteurs O365 historiques sont retirés) ; digest hebdomadaire ; en-têtes d'automate anti-réponses d'absence ; aucun envoi s'il n'y a rien à dire ; endpoint d'exploitation `POST /api/notify/run` (admin).
- **Double validation Go/No-Go (« quatre yeux »)** : sur les criticités configurées (défaut C1 et C2), une décision est d'abord *proposée* puis doit être **contre-validée par un autre contributeur** avant de prendre effet — le serveur garantit les signatures (identité SSO, proposeur ≠ contre-validateur, 403 sinon). Alerte « à contre-valider » au tableau de bord et dans les notifications.
- **Référentiel de checklist administrable** : nouvelle vue « Référentiel » (admin) — catégories, éléments et **criticités applicables** par élément, versionné côté serveur ; les nouvelles fiches sont instanciées selon leur criticité ; « Appliquer aux fiches en cours » ajoute les éléments manquants ; un changement de criticité complète automatiquement la checklist.
- **Vue « Activité »** : le journal d'audit nominatif du serveur, consultable et filtrable par tous.
- **Recherche globale** : nouvelle vue (raccourci `/`) sur fiches, checklists, actions, journaux, tickets Jira et pages DMEX, extraits surlignés.
- **Champs personnalisés** : champs texte définis par les administrateurs (ex. code CMDB), saisis à l'édition et affichés dans l'en-tête des fiches.
- Tests : 152 contrôles automatisés en CI (77 applicatifs Playwright dont le parcours de contre-validation multi-navigateurs, 51 API/serveur dont notifications sur stubs SMTP/Teams, 24 relais).

## 2.0.0 — 2026-08-20 · Référentiel partagé multi-utilisateurs (phase 1)

Le passage en production : les données quittent le navigateur de chacun pour un référentiel commun, authentifié et supervisé.

- **`server.py`** (nouveau, Python standard — aucun paquet) : un seul service qui sert le front, expose l'API REST sur **SQLite (WAL)** et intègre le relais Atlassian (même liste blanche que `relay.py`, accès authentifié).
- **Front double mode** : servie par `server.py`, l'application bascule automatiquement en mode partagé (l'interface et les gestes ne changent pas) ; ouverte en fichier ou via `relay.py`, elle reste en mode local v1.
- **Concurrence optimiste** : révision par fiche, conflit → 409, rechargement automatique de la version courante avec le nom de l'auteur.
- **Temps réel (SSE)** : les créations, modifications et suppressions des autres utilisateurs apparaissent en direct, reconnexion avec resynchronisation.
- **Identité SSO** (oauth2-proxy / Entra ID, en-têtes configurables) : journal et décisions Go/No-Go signés automatiquement, **audit nominatif côté serveur** (qui / quoi / quand, consultable via `/api/audit`).
- **Rôles** : admin / contributeur / lecteur (`ADMIN_EMAILS`, `WRITE_EMAILS`) — appliqués par l'API et reflétés dans l'interface (lecture seule, réglages communs réservés aux administrateurs).
- **Migration en un clic** : l'export JSON v1 s'importe tel quel (Paramètres → Importer, administrateurs) ; l'export v2 reste compatible v1.
- **Exploitation** : `/healthz`, `/metrics` (Prometheus), journaux JSON (sans query string), sauvegarde SQLite quotidienne compressée avec rétention (`BACKUP_KEEP`), sauvegarde avant chaque import, `Dockerfile` + `docker-compose.yml` (oauth2-proxy inclus en exemple).
- **Tests** : 33 contrôles API/rôles/SSE (`tests/server.sh`) et scénario Playwright multi-utilisateurs réel (deux navigateurs : propagation SSE en direct, lecture seule appliquée, conflit 409) — 98 contrôles automatisés au total en CI.

## 1.3.0 — 2026-08-20 · Durcissement « prod ready » (phase 0)

Robustesse et intégrité des données :
- Normalisation défensive complète des états chargés/importés : plateformes nulles filtrées, identifiants dédoublonnés, statuts/dates/criticités/étapes inconnus ramenés à des valeurs sûres, seuil re-validé — un import corrompu ne peut plus rendre l'application inutilisable au démarrage.
- Formatteurs de dates défensifs (valeur invalide → « — ») ; horodatages du journal avec année.
- Garde-fou multi-onglets : l'écriture d'un autre onglet recharge l'état au lieu de l'écraser silencieusement.
- Sauvegardes locales rotatives (5 instantanés) : automatique quotidienne, avant chaque import, effacement ou rechargement de démo ; restauration depuis Paramètres ; rappel d'export après 7 jours sans export.
- Version applicative affichée (pied de navigation, Paramètres) et incluse dans les exports ; avertissement à l'import d'un export issu d'une version plus récente.

Sécurité :
- Les URLs issues de données (liens tickets, pages DMEX, configuration) sont restreintes à http(s) — neutralisation de `javascript:`/`data:` ; `rel="noopener noreferrer"` sur tous les liens externes.
- Relais : en-têtes de sécurité (CSP, nosniff, X-Frame-Options, Referrer-Policy), jeton d'accès optionnel (`RELAY_ACCESS_TOKEN` / en-tête `X-Relay-Token`), redirections amont jamais suivies (le jeton ne peut pas fuir vers un `Location` tiers), taille de réponse plafonnée, `--open-cors` refusé hors 127.0.0.1.

Fiabilité de l'interface :
- Les saisies en cours (commentaire de revue, note de journal, URL DMEX, zone d'import) survivent aux re-rendus asynchrones (fin de synchronisation…).
- Le clic qui suit immédiatement la saisie d'un champ (JQL → Synchroniser) n'est plus « avalé ».
- Bouton Synchroniser toujours réarmé même en cas d'erreur inattendue ; recherches DMEX successives sans résultats obsolètes ; synchronisation d'une fiche supprimée entre-temps sans effet de bord.
- Impression : la fiche imprime désormais toutes les catégories de la checklist, repliées comprises.
- Les items d'une catégorie retirée du référentiel restent visibles (« Hors référentiel ») au lieu de plomber invisiblement le score.

Gouvernance légère :
- Signature (« Votre nom », Paramètres) apposée aux notes du journal et aux décisions Go/No-Go.
- Suppression d'action : confirmation + trace au journal ; modification de fiche journalisée ; le bandeau de démonstration disparaît à la création de la première fiche réelle.
- Correction de l'affichage « J−-n » pour les plateformes déjà en production.

Qualité :
- Suite de tests versionnée dans `tests/` (57 contrôles applicatifs Playwright + 24 contrôles du relais) et intégration continue GitHub Actions.
- Relais : healthcheck `/healthz`, journaux horodatés avec code de statut.

## 1.2.0 — 2026-08-20 · Recherche DMEX par label

- Recherche CQL des pages Confluence portant le label DMEX (défaut `asset-dip`, configurable), rattachement en un clic, métadonnées reprises sans re-synchronisation.

## 1.1.0 — 2026-08-20 · Intégration Jira & Confluence Cloud

- Tickets Jira par JQL sur chaque fiche (tableau, compteurs par statut) ; pages DMEX rattachées par URL (titre, espace, version, auteur, fraîcheur).
- Relais interne en lecture seule `relay.py` (liste blanche, jeton Atlassian côté serveur uniquement).

## 1.0.0 — 2026-08-19 · Version initiale

- Pipeline de mise en exploitation en 8 étapes (kanban), checklist d'exploitabilité de 33 points en 9 chantiers, score de préparation, décision Go/No-Go, actions et réserves, journal, équipes, tableau de bord, export/import JSON, thèmes clair/sombre, impression.
