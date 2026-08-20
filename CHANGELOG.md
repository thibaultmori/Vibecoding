# Journal des versions — Passerelle

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
