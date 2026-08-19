# Passerelle — Gestion des mises en exploitation (MEE)

Interface de gestion des **mises en exploitation de nouvelles plateformes** pour les équipes de la Direction Infrastructures & Production.

Application web autonome : **un seul fichier HTML**, aucune dépendance, aucun serveur requis. Les données sont stockées localement dans le navigateur (localStorage) et s'échangent par export/import JSON.

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

## Limites connues et suite possible

- Les données sont **locales au navigateur** : pas de temps réel multi-utilisateurs. Pour un usage d'équipe, passer par l'export/import JSON, ou faire évoluer l'outil vers une v2 avec backend (API + base) — le modèle de données JSON actuel peut servir de contrat tel quel.
- Pas d'authentification ni d'historique des modifications au-delà du journal par plateforme.
