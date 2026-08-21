# Passerelle — Gestion des mises en exploitation (MEE)

Interface de gestion des **mises en exploitation de nouvelles plateformes** pour les équipes de la Direction Infrastructures & Production.

Deux modes d'exécution, avec la même interface :

- **Mode partagé (v2, recommandé pour une équipe)** : `server.py` — un seul service Python standard (aucun paquet) qui sert l'application, stocke les données dans un **référentiel commun** (SQLite sauvegardée), applique des **rôles** (admin / contributeur / lecteur), signe chaque geste avec l'**identité SSO** (oauth2-proxy / Entra ID) et diffuse les modifications **en temps réel** à tous les navigateurs connectés.
- **Mode local (v1)** : `index.html` seul, zéro dépendance, données dans le navigateur (localStorage) + `relay.py` pour l'intégration Atlassian — parfait pour découvrir l'outil ou un usage individuel.

## Démarrage

**Mode partagé (équipe)** :

```bash
docker compose up -d        # image + volume de données + oauth2-proxy (voir docker-compose.yml)
```

ou sans Docker : `ADMIN_EMAILS=chef@… python3 server.py` derrière votre proxy SSO — détails, variables et sécurité dans `EXPLOITATION.md`. Pour une maquette sans SSO : `AUTH_MODE=none python3 server.py --port 8080` puis `http://localhost:8080`. La migration depuis le mode local se fait en un clic : export JSON → Paramètres → Importer.

**Mode local (individuel)** :

1. **Ouvrir le fichier** : double-cliquez sur `index.html` — l'application démarre avec un jeu de démonstration.
2. **Servir en local** : `python3 -m http.server` dans le dossier, puis `http://localhost:8000`.
3. **Publier sur un intranet / GitHub Pages** : le fichier est statique, n'importe quel hébergement web suffit.

## Fonctionnalités

- **Tableau de bord** : indicateurs (en cours, prêtes, bloquées, en retard, en exploitation), file « À traiter » (actions bloquantes, retards, revues à tenir), prochaines mises en production, répartition du pipeline par étape et reste à faire par équipe.
- **Pipeline en 8 étapes** : Cadrage → Construction → Recette technique → Pré-production → Revue Go/No-Go → Mise en production → VSR/Stabilisation → En exploitation. Vue kanban avec glisser-déposer.
- **Fiche plateforme** :
  - **Checklist d'exploitabilité** de 33 points répartis en 9 chantiers (supervision, sauvegarde, PRA, sécurité, réseau & certificats, documentation, astreinte, capacité, référentiels & conformité), chacun affecté à une équipe responsable. États : à faire / en cours / fait / N/A, échéances, commentaires, éléments personnalisés.
  - **Score de préparation** calculé automatiquement (les N/A sont exclus du calcul), seuil « prête » configurable (90 % par défaut).
  - **Décision Go / No-Go** : Go, Go avec réserves, No-Go, avec commentaire de revue ; un Go bascule automatiquement la plateforme en « Mise en production ».
  - **Actions & réserves** avec indicateur bloquant (une action bloquante ouverte bloque la plateforme).
  - **Journal** horodaté : événements automatiques (changement d'étape, décisions, actions bloquantes) et notes manuelles.
  - **Fiche imprimable** pour la revue de mise en exploitation.
- **Liste des plateformes** : recherche, filtres (étape, criticité, statut, équipe), tris.
- **Équipes** : référentiel des équipes de la direction, affectées aux éléments de checklist.
- **Notifications** (mode partagé) : e-mail quotidien par équipe (échéances sous 7 jours et retards), synthèse globale et digest hebdomadaire vers une adresse de direction et/ou un canal Teams (webhook Workflows) — voir EXPLOITATION.md.
- **Double validation Go/No-Go** : sur les criticités configurées (défaut C1/C2), la décision proposée doit être contre-validée par un autre contributeur — signatures garanties par le serveur.
- **Référentiel administrable** (mode partagé, admin) : catégories, éléments et criticités applicables, versionné ; application aux fiches en cours en un clic.
- **Activité** : journal d'audit nominatif consultable ; **Recherche globale** (touche `/`) sur tout le contenu ; **champs personnalisés** définis par les administrateurs.
- **Pilotage** (mode partagé) : tendances historisées — MEP par mois, temps moyen par étape, délai création→MEP, décisions tracées, fraîcheur DMEX.
- **Tickets Jira depuis les actions** : un clic crée le ticket (projet/type configurables) et lie sa clé à l'action ; **synchronisation Atlassian automatique** côté serveur (SSE), le bouton Synchroniser devient optionnel.
- **API machine** (`/api/v1/platforms`, jetons dédiés) pour la CMDB/ITSM et **flux iCalendar** des dates cibles (`/api/calendar.ics`) ; **export CSV** du portefeuille filtré ; **rapport de revue imprimable** avec bloc signatures.
- **Paramètres** : export JSON (téléchargement ou copie), import (fichier ou collage), seuil de préparation, réinitialisation.
- **Intégration Jira & Confluence Cloud** : tickets du chantier récupérés par JQL et pages DMEX (Dossier de Mise En eXploitation) rattachées à chaque fiche, avec version, auteur et fraîcheur — voir la section dédiée ci-dessous.
- **Thèmes clair et sombre** (suit le réglage du système), interface responsive (poste de travail, tablette, mobile).
- **Robustesse** : sauvegardes locales rotatives (5 instantanés + rappel d'export), garde-fou multi-onglets, imports corrompus neutralisés, signature des notes et décisions (« Votre nom » dans Paramètres), version affichée et tracée dans les exports (voir `CHANGELOG.md`).

## Données

- Stockage : clé localStorage `passerelle-mee:v1`, propre à chaque navigateur.
- Sauvegarde / partage : **Paramètres → Exporter / importer**. L'export JSON contient tout l'état (plateformes, checklists, équipes, journal, réglages).
- Premier lancement : un jeu de démonstration (7 plateformes, 7 équipes) est chargé pour découvrir l'outil ; « Repartir de zéro » l'efface en conservant les équipes types.

## Personnalisation

Tout le paramétrage métier est en tête du `<script>` de `index.html` :

| Constante | Rôle |
|---|---|
| `STAGES` | Les étapes du pipeline de mise en exploitation |
| `TEMPLATE` | Le référentiel de la checklist d'exploitabilité (chantiers, points de contrôle, équipe par défaut) |
| `CRITICITY` | Les niveaux de criticité (C1 à C4) |
| `TYPES` | Les types de plateformes |
| `seedTeams()` | Les équipes proposées par défaut |

Modifier `TEMPLATE` ne touche que les plateformes créées ensuite ; les fiches existantes conservent leur checklist.

## Intégration Jira & Confluence (Cloud)

Chaque fiche plateforme peut afficher **les tickets Jira** de son chantier (champ JQL + bouton « Synchroniser ») et **les pages Confluence de son DMEX** : collez l'URL des pages, ou cliquez sur **« Rechercher »** pour retrouver directement les pages portant le **label DMEX** (par défaut `asset-dip`, modifiable dans Paramètres) et les rattacher en un clic. Titre, espace, version, auteur et date de dernière mise à jour sont récupérés ; une page non modifiée depuis plus de 6 mois est signalée.

### Pourquoi un relais ?

Atlassian Cloud n'autorise pas les appels directs depuis une page web tierce (CORS). Le relais `relay.py` (Python 3 standard, aucun paquet à installer) fait le pont **en lecture seule** et **sert aussi l'application** : tout est même origine, et le jeton API reste côté serveur — **aucun secret n'est stocké dans le navigateur**.

### Démarrage du relais

```bash
export ATL_SITE=https://mon-entreprise.atlassian.net
export ATL_EMAIL=compte-service@mon-entreprise.fr
export ATL_TOKEN=xxxxxxxx        # jeton API : id.atlassian.com → Security → API tokens
python3 relay.py                 # sert l'app sur http://127.0.0.1:8765/
```

Options : `--host 0.0.0.0` (exposer au réseau), `--port`, `--app chemin/index.html`, `--open-cors` (uniquement si l'app est ouverte en `file://`).

Ensuite, dans l'application : **Paramètres → Intégration Atlassian** — laisser « URL du relais » vide si l'app est ouverte via le relais, renseigner l'URL du site Atlassian (pour les liens vers les tickets), puis « Tester Jira » / « Tester Confluence ».

### Sécurité

- Le relais n'accepte que des **GET** sur une **liste blanche stricte** de chemins (recherche JQL, lecture de pages/espaces, recherche de pages par label, tests de connexion) ; l'hôte amont est fixe (`ATL_SITE`) ; aucun en-tête du navigateur n'est transmis à Atlassian ; les **redirections amont ne sont jamais suivies** (le jeton ne peut pas fuir) ; le jeton n'apparaît jamais dans les journaux.
- Utilisez un **compte de service en lecture seule**, limité aux projets Jira et espaces Confluence utiles.
- Les jetons API Atlassian **expirent au bout d'un an au maximum** : prévoyez la rotation (symptôme : erreur 401 à la synchronisation).
- Par défaut le relais n'écoute que sur `127.0.0.1`. **Dès qu'il est exposé au réseau** (`--host 0.0.0.0`), définissez `RELAY_ACCESS_TOKEN` : les clients devront présenter ce jeton (Paramètres → « Jeton d'accès au relais ») — sinon toute machine du réseau lirait Jira/Confluence avec les droits du compte de service.
- Le relais pose les en-têtes de sécurité (CSP, nosniff, X-Frame-Options) sur la page servie et expose un healthcheck `GET /healthz`. Exploitation détaillée : voir `EXPLOITATION.md`.

### Alternative : reverse proxy existant

Si vous préférez votre infrastructure web, un `nginx` fait le même travail que `relay.py` :

```nginx
location /atlassian/ {
    proxy_pass https://mon-entreprise.atlassian.net/;
    proxy_set_header Authorization "Basic BASE64(email:token)";
    proxy_pass_request_headers off;
    proxy_hide_header WWW-Authenticate;
    proxy_hide_header Set-Cookie;
}
location / { root /chemin/vers/passerelle; }
```

(Restreignez alors les chemins autorisés avec des `location` plus précis, équivalents à la liste blanche de `relay.py`.)

### Dans l'Artifact claude.ai

La page publiée en Artifact bloque tout appel réseau : la synchronisation y échoue avec un message explicite, mais **les données déjà synchronisées (ou importées) restent affichées**. Synchronisez depuis la version intranet, exportez, importez dans l'Artifact si besoin.

## Qualité

- Suite de tests versionnée : `npm install` puis `npm test` — 179 contrôles : parcours applicatif complet et scénarios multi-utilisateurs réels, contre-validation comprise (`tests/e2e.js`, Playwright), API/rôles/conflits/audit/notifications sur stubs SMTP et Teams (`tests/server.sh`), relais (`tests/relay.sh`).
- Intégration continue GitHub Actions (`.github/workflows/ci.yml`) à chaque push.
- Versions : `CHANGELOG.md` ; la version courante est affichée dans l'application et incluse dans les exports.

## Limites connues et suite possible

- En **mode local**, les données restent propres à chaque navigateur (échange par export/import JSON) — le mode partagé v2 est fait pour l'usage d'équipe.
- La feuille de route initiale (phases 0 à 3) est entièrement livrée. Pistes suivantes possibles : pagination au-delà de 50 tickets par JQL, résolution des liens courts Confluence, migration PostgreSQL si la volumétrie l'exige.
- Intégration Atlassian : 50 premiers tickets par JQL (mention affichée au-delà), liens courts Confluence `/wiki/x/…` non résolus (coller l'URL complète), instances Server/Data Center non couvertes (endpoints différents), pas de relance automatique sur limitation 429 (le message affiche le délai à respecter).
