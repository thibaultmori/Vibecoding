# Passerelle — Gestion des mises en exploitation (MEE)

Interface de gestion des **mises en exploitation de nouvelles plateformes** pour les équipes de la Direction Infrastructures & Production.

Application web autonome : **un seul fichier HTML**, aucune dépendance, aucun serveur requis — sauf pour l'intégration Jira/Confluence, qui s'appuie sur un petit relais fourni (`relay.py`, Python 3 standard). Les données sont stockées localement dans le navigateur (localStorage) et s'échangent par export/import JSON.

## Démarrage

Trois options, de la plus simple à la plus partagée :

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
- **Paramètres** : export JSON (téléchargement ou copie), import (fichier ou collage), seuil de préparation, réinitialisation.
- **Intégration Jira & Confluence Cloud** : tickets du chantier récupérés par JQL et pages DMEX (Dossier de Mise En eXploitation) rattachées à chaque fiche, avec version, auteur et fraîcheur — voir la section dédiée ci-dessous.
- **Thèmes clair et sombre** (suit le réglage du système), interface responsive (poste de travail, tablette, mobile).

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

- Le relais n'accepte que des **GET** sur une **liste blanche stricte** de chemins (recherche JQL, lecture de pages/espaces, recherche de pages par label, tests de connexion) ; l'hôte amont est fixe (`ATL_SITE`) ; aucun en-tête du navigateur n'est transmis à Atlassian ; le jeton n'apparaît jamais dans les journaux.
- Utilisez un **compte de service en lecture seule**, limité aux projets Jira et espaces Confluence utiles.
- Les jetons API Atlassian **expirent au bout d'un an au maximum** : prévoyez la rotation (symptôme : erreur 401 à la synchronisation).
- Par défaut le relais n'écoute que sur `127.0.0.1`. Si vous l'exposez au réseau (`--host 0.0.0.0`), toute machine pouvant le joindre lit Jira/Confluence avec les droits du jeton : réservez l'accès au réseau de la direction.

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

## Limites connues et suite possible

- Les données sont **locales au navigateur** : pas de temps réel multi-utilisateurs. Pour un usage d'équipe, passer par l'export/import JSON, ou faire évoluer l'outil vers une v2 avec backend (API + base) — le modèle de données JSON actuel peut servir de contrat tel quel.
- Pas d'authentification ni d'historique des modifications au-delà du journal par plateforme.
- Intégration Atlassian : 50 premiers tickets par JQL (mention affichée au-delà), liens courts Confluence `/wiki/x/…` non résolus (coller l'URL complète), instances Server/Data Center non couvertes (endpoints différents), pas de relance automatique sur limitation 429 (le message affiche le délai à respecter).
