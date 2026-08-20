/* Tests de bout en bout de Passerelle (Playwright, Chromium).
   Lancement : node tests/e2e.js
   Chromium : celui de Playwright, ou CHROMIUM_PATH pour un binaire local. */
'use strict';
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');
const { chromium } = require('playwright');

const APP_URL = 'file://' + path.resolve(__dirname, '..', 'index.html');
const LS_KEY = 'passerelle-mee:v1';

let failures = 0;
function check(name, cond, detail) {
  if (cond) { console.log('OK   ' + name); }
  else { failures++; console.log('FAIL ' + name + (detail !== undefined ? ' → ' + String(detail).slice(0, 300) : '')); }
}

(async () => {
  const errors = [];
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('dialog', d => d.accept());

  await page.goto(APP_URL);
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.waitForTimeout(500);

  /* ---------- 1. Fonctions pures (via le contexte de la page) ---------- */
  const unit = await page.evaluate(() => {
    const r = {};
    r.fmtGarbage = fmtD('garbage');
    r.fmtEmpty = fmtD('');
    r.safeJs = safeUrl('javascript:alert(1)');
    r.safeHttps = safeUrl('https://a.b/c');
    r.parseNum = parsePageId('123456');
    r.parseUrl = parsePageId('https://x.atlassian.net/wiki/spaces/K/pages/98765/Titre');
    r.parseJs = parsePageId('javascript:alert(1)//pages/123');
    r.parseTiny = parsePageId('https://x.atlassian.net/wiki/x/AbCd');
    r.parseFtp = parsePageId('ftp://x/pages/123');
    r.vGt = versionGt('99.0.0', '1.3.0');
    r.vEq = versionGt('1.3.0', '1.3.0');
    const toxic = normalizeState({
      platforms: [null, {checklist: [{status: 'bizarre'}], targetDate: 'garbage', journal: [null, {text: 42}]},
                  {id: 'dup', name: 'A'}, {id: 'dup', name: 'B'}],
      teams: null,
      settings: {readyThreshold: '95 %'},
      integrations: {siteUrl: 'javascript:evil', relayUrl: 'gopher://x'},
    });
    r.toxCount = toxic.platforms.length;
    r.toxStatus = toxic.platforms[0].checklist[0].status;
    r.toxDate = toxic.platforms[0].targetDate;
    r.toxIds = new Set(toxic.platforms.map(p => p.id)).size;
    r.toxTh = toxic.settings.readyThreshold;
    r.thNaN = normalizeState({platforms: [], teams: [], settings: {readyThreshold: 'abc'}}).settings.readyThreshold;
    r.thHigh = normalizeState({platforms: [], teams: [], settings: {readyThreshold: 999}}).settings.readyThreshold;
    r.toxSite = toxic.integrations.siteUrl;
    r.toxName = toxic.platforms[0].name;
    return r;
  });
  check('fmtD défensif (garbage → —)', unit.fmtGarbage === '—' && unit.fmtEmpty === '—', JSON.stringify(unit));
  check('safeUrl bloque javascript:', unit.safeJs === '' && unit.safeHttps === 'https://a.b/c');
  check('parsePageId id numérique', unit.parseNum.id === '123456');
  check('parsePageId URL https', unit.parseUrl.id === '98765');
  check('parsePageId rejette javascript:', !!unit.parseJs.error);
  check('parsePageId rejette lien court', !!unit.parseTiny.error);
  check('parsePageId rejette ftp:', !!unit.parseFtp.error);
  check('versionGt', unit.vGt === true && unit.vEq === false);
  check('normalizeState filtre null + statuts + dates', unit.toxCount === 3 && unit.toxStatus === 'todo' && unit.toxDate === '');
  check('normalizeState dédoublonne les ids', unit.toxIds === 3);
  check('normalizeState re-valide le seuil', unit.toxTh === 95 && unit.thNaN === 90 && unit.thHigh === 100,
    JSON.stringify([unit.toxTh, unit.thNaN, unit.thHigh]));
  check('normalizeState assainit les URLs de config', unit.toxSite === '');
  check('normalizeState nomme les fiches', unit.toxName === 'Sans nom');

  /* ---------- 2. Parcours de base ---------- */
  check('tableau de bord : 5 tuiles', await page.locator('.tile').count() === 5);

  await page.click('a[href="#/plateformes"]');
  await page.waitForTimeout(200);
  check('liste : 7 plateformes seed', await page.locator('table.plist tbody tr').count() === 7);

  await page.selectOption('#f-status', 'blocked');
  await page.waitForTimeout(200);
  check('filtre bloquées : 2', await page.locator('table.plist tbody tr').count() === 2);
  await page.selectOption('#f-status', '');

  await page.fill('#f-search', 'kong');
  await page.waitForTimeout(250);
  check('recherche kong : 1 résultat', await page.locator('table.plist tbody tr').count() === 1);
  check('recherche : focus conservé', await page.evaluate(() => document.activeElement && document.activeElement.id) === 'f-search');
  await page.fill('#f-search', '');
  await page.waitForTimeout(250);

  await page.click('table.plist tbody tr:first-child');
  await page.waitForTimeout(300);
  check('clic ligne → fiche', (await page.evaluate(() => location.hash)).startsWith('#/plateforme/'));

  const catsOpenBefore = await page.locator('.cat.open').count();
  check('fiche 100 % : catégories repliées', catsOpenBefore === 0);
  check('impression : corps repliés présents dans le DOM', await page.locator('.cat-body.closed').count() > 0);
  await page.locator('.cat-head').first().click();
  await page.waitForTimeout(200);
  check('dépliage manuel', await page.locator('.cat.open').count() === 1);

  await page.evaluate(() => { location.hash = '#/plateforme/p-kaas'; });
  await page.waitForTimeout(300);
  const chipBefore = await page.locator('.cat.open .item .chip.st').first().textContent();
  await page.locator('.cat.open .item .chip.st').first().click();
  await page.waitForTimeout(200);
  const chipAfter = await page.locator('.cat.open .item .chip.st').first().textContent();
  check('cycle de statut d’un item', chipBefore !== chipAfter, chipBefore + ' → ' + chipAfter);

  await page.fill('form[data-submit="add-note"] input[name="note"]', 'Note de test automatisé');
  await page.click('form[data-submit="add-note"] button[type="submit"]');
  await page.waitForTimeout(200);
  check('note au journal', (await page.locator('.j-row').first().textContent()).includes('Note de test automatisé'));

  /* ---------- 3. Kanban ---------- */
  await page.click('a[href="#/pipeline"]');
  await page.waitForTimeout(300);
  await page.locator('[data-drag="p-runners"]').dragTo(page.locator('[data-drop="build"]'));
  await page.waitForTimeout(300);
  check('drag & drop kanban', await page.evaluate(k => JSON.parse(localStorage.getItem(k)).platforms.find(p => p.id === 'p-runners').stage, LS_KEY) === 'build');

  /* ---------- 4. Création + Go/No-Go ---------- */
  await page.click('button[data-action="new-platform"]');
  await page.waitForTimeout(200);
  await page.fill('#fp-name', 'Plateforme de test E2E');
  await page.fill('#fp-date', '2026-12-01');
  await page.click('.modal button[type="submit"]');
  await page.waitForTimeout(300);
  check('création → fiche + 33 items', await page.evaluate(k => {
    const s = JSON.parse(localStorage.getItem(k));
    const p = s.platforms.find(x => x.name === 'Plateforme de test E2E');
    return p && p.checklist.length === 33 && s.seeded === false;
  }, LS_KEY) === true);

  await page.fill('#gng-comment', 'Test de décision');
  await page.click('button[data-action="decide"][data-d="nogo"]');
  await page.waitForTimeout(200);
  check('décision No-Go enregistrée', await page.locator('.gng-decided').count() === 1);

  await page.click('a[href="#/equipes"]');
  await page.waitForTimeout(200);
  check('équipes : 7 cartes', await page.locator('.team-card').count() === 7);

  /* ---------- 5. Import / export ---------- */
  await page.click('a[href="#/parametres"]');
  await page.waitForTimeout(200);
  const exported = await page.evaluate(k => localStorage.getItem(k), LS_KEY);
  await page.fill('#io-area', exported);
  await page.click('button[data-action="import-apply"]');
  await page.waitForTimeout(300);
  check('import aller-retour : 8 plateformes', await page.evaluate(k => JSON.parse(localStorage.getItem(k)).platforms.length, LS_KEY) === 8);

  // import toxique : l'application doit rester utilisable
  await page.fill('#io-area', JSON.stringify({platforms: [null, {targetDate: 'n’importe quoi', checklist: [{status: 'zzz'}]}], teams: []}));
  await page.click('button[data-action="import-apply"]');
  await page.waitForTimeout(300);
  await page.goto(APP_URL + '#/tableau-de-bord');
  await page.waitForTimeout(400);
  check('import toxique : le tableau de bord tient debout', await page.locator('.tile').count() === 5);
  check('import toxique : fiche renommée « Sans nom »', await page.evaluate(k => JSON.parse(localStorage.getItem(k)).platforms[0].name, LS_KEY) === 'Sans nom');

  // avertissement de version plus récente
  const newer = JSON.parse(exported); newer.appVersion = '99.0.0';
  await page.goto(APP_URL + '#/parametres');
  await page.waitForTimeout(300);
  await page.fill('#io-area', JSON.stringify(newer));
  await page.click('button[data-action="import-apply"]');
  await page.waitForTimeout(300);
  check('avertissement version plus récente', (await page.locator('#toast-zone').textContent()).includes('version plus récente'));

  /* ---------- 6. Signature (identité déclarative) ---------- */
  await page.fill('#set-name', 'Testeur CI');
  await page.locator('#set-name').blur();
  await page.waitForTimeout(200);
  await page.goto(APP_URL + '#/plateforme/p-kaas');
  await page.waitForTimeout(300);
  await page.fill('form[data-submit="add-note"] input[name="note"]', 'Note signée');
  await page.click('form[data-submit="add-note"] button[type="submit"]');
  await page.waitForTimeout(200);
  check('journal signé', (await page.locator('.j-row').first().textContent()).includes('Testeur CI'));

  /* ---------- 7. Intégration Atlassian (stubs réseau) ---------- */
  const FIX_SEARCH = { issues: [
    { key: 'TST-1', fields: { summary: 'Ticket stub un', status: { name: 'In Progress', statusCategory: { key: 'indeterminate' } }, assignee: { displayName: 'Alice Stub' }, issuetype: { name: 'Task' }, priority: { name: 'High' }, updated: '2026-08-19T10:00:00.000+0000' } },
    { key: 'TST-2', fields: { summary: 'Ticket stub deux', status: { name: 'To Do', statusCategory: { key: 'new' } }, assignee: null, priority: null, issuetype: { name: 'Story' }, updated: '2026-08-18T09:00:00.000+0000' } },
    { key: 'TST-3', fields: { summary: 'Ticket stub trois', status: { name: 'Done', statusCategory: { key: 'done' } }, assignee: { displayName: 'Bob Stub' }, issuetype: { name: 'Task' }, priority: { name: 'Low' }, updated: '2026-08-01T08:00:00.000+0000' } },
  ], nextPageToken: 'tok123' };
  const FIX_PAGES = { results: [{ id: '555001', title: 'DMEX — Test E2E', spaceId: '42', version: { number: 4, createdAt: '2026-08-10T12:00:00.000Z', authorId: 'acc-1' } }] };
  const FIX_CQL = { _links: { base: 'https://exemple.atlassian.net/wiki' }, results: [
    { id: '777001', title: 'DMEX — Nouvelle plateforme stub', space: { key: 'TST', name: 'Espace Test' }, version: { number: 9, when: '2026-08-19T08:00:00.000+0000', by: { displayName: 'Carole Stub' } }, _links: { webui: '/spaces/TST/pages/777001/DMEX' } },
    { id: '555001', title: 'DMEX — Test E2E', space: { key: 'TST', name: 'Espace Test' }, version: { number: 4, when: '2026-08-10T12:00:00.000Z', by: { displayName: 'Alice Stub' } }, _links: { webui: '/spaces/TST/pages/555001/DMEX-Test' } },
  ] };
  const fulfillJson = (route, obj, status = 200) => route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': 'X-Relay-Token, Accept' }, body: JSON.stringify(obj) });
  let jiraMode = 'ok';
  let seenRelayToken = null;
  await page.route('http://relay.test/**', route => {
    const u = route.request().url();
    if (u.includes('/atlassian/rest/api/3/search/jql')) {
      seenRelayToken = route.request().headers()['x-relay-token'] || null;
      if (jiraMode === '400') return fulfillJson(route, { errorMessages: ['JQL invalide : champ inconnu « foo »'] }, 400);
      if (jiraMode === 'abort') return route.abort();
      return fulfillJson(route, FIX_SEARCH);
    }
    if (u.includes('/atlassian/wiki/rest/api/content/search')) return fulfillJson(route, FIX_CQL);
    if (u.includes('/atlassian/wiki/api/v2/pages')) return jiraMode === 'abort' ? route.abort() : fulfillJson(route, FIX_PAGES);
    if (u.includes('/atlassian/wiki/api/v2/spaces')) return fulfillJson(route, { results: [{ id: '42', key: 'TST', name: 'Espace Test' }] });
    if (u.includes('/atlassian/wiki/rest/api/user/current')) return fulfillJson(route, { displayName: 'Robot Confluence' });
    if (u.includes('/atlassian/wiki/rest/api/user')) return fulfillJson(route, { displayName: 'Alice Stub' });
    if (u.includes('/atlassian/rest/api/3/myself')) return fulfillJson(route, { displayName: 'Robot Jira' });
    return fulfillJson(route, { error: 'stub 404' }, 404);
  });

  await page.goto(APP_URL + '#/parametres');
  await page.waitForTimeout(300);
  await page.fill('#int-relay', 'http://relay.test');
  await page.locator('#int-relay').blur();
  await page.waitForTimeout(150);
  await page.fill('#int-site', 'https://exemple.atlassian.net');
  await page.locator('#int-site').blur();
  await page.waitForTimeout(150);
  await page.fill('#int-token', 'sekret-ci');
  await page.locator('#int-token').blur();
  await page.waitForTimeout(150);
  await page.click('button[data-action="test-atl"][data-kind="jira"]');
  await page.waitForTimeout(400);
  check('test de connexion Jira', (await page.locator('.test-line').first().textContent()).includes('Robot Jira'));

  await page.click('a[href="#/plateformes"]');
  await page.waitForTimeout(200);
  await page.click('button[data-action="new-platform"]');
  await page.waitForTimeout(200);
  await page.fill('#fp-name', 'Plateforme intégration E2E');
  await page.click('.modal button[type="submit"]');
  await page.waitForTimeout(300);
  await page.fill('input[data-change="jira-jql"]', 'project = TST');
  await page.locator('input[data-change="jira-jql"]').blur();
  await page.waitForTimeout(200);
  await page.fill('form[data-submit="add-dmex"] input[name="url"]', 'https://exemple.atlassian.net/wiki/spaces/TST/pages/555001/DMEX+Test');
  await page.click('form[data-submit="add-dmex"] button[type="submit"]');
  await page.waitForTimeout(200);
  await page.click('button[data-action="sync-platform"]');
  await page.waitForTimeout(700);
  check('synchro : 3 tickets', await page.locator('.jtable tbody tr').count() === 3);
  check('jeton relais transmis (X-Relay-Token)', seenRelayToken === 'sekret-ci', seenRelayToken);
  check('assigné null → tiret', (await page.locator('.jtable tbody tr').nth(1).textContent()).includes('—'));
  check('mention 50 premiers tickets', (await page.locator('.int-foot').first().textContent()).includes('50 premiers'));
  const dmexRow = await page.locator('.dmex-row').first().textContent();
  check('page DMEX enrichie', dmexRow.includes('DMEX — Test E2E') && dmexRow.includes('Espace Test') && dmexRow.includes('v.4') && dmexRow.includes('Alice Stub'), dmexRow);

  /* recherche par label */
  await page.click('button[data-action="dmex-search-open"]');
  await page.waitForTimeout(500);
  check('recherche label : 2 résultats', await page.locator('#dmex-results .dmex-row').count() === 2);
  check('page déjà rattachée signalée', (await page.locator('#dmex-results').textContent()).includes('Rattachée'));
  await page.click('#dmex-results button[data-action="dmex-attach"]');
  await page.waitForTimeout(300);
  check('rattachement depuis la recherche', ((await page.locator('#dmex-results').textContent()).split('Rattachée').length - 1) === 2);
  await page.click('.modal button[data-action="close-modal"]');
  await page.waitForTimeout(250);
  check('2 pages DMEX sur la fiche', await page.locator('.dmex-row').count() === 2);
  check('métadonnées reprises sans re-synchro', (await page.locator('.dmex-row', { hasText: 'Nouvelle plateforme stub' }).textContent()).includes('v.9'));

  /* persistance + erreurs */
  await page.reload();
  await page.waitForTimeout(400);
  check('persistance après rechargement', await page.locator('.jtable tbody tr').count() === 3 && await page.locator('.dmex-row').count() === 2);

  jiraMode = '400';
  await page.click('button[data-action="sync-platform"]');
  await page.waitForTimeout(600);
  check('erreur 400 : message Atlassian affiché', (await page.locator('.int-error').first().textContent()).includes('JQL invalide'));
  check('erreur : cache conservé', await page.locator('.jtable tbody tr').count() === 3);

  jiraMode = 'abort';
  await page.click('button[data-action="sync-platform"]');
  await page.waitForTimeout(600);
  check('erreur réseau actionnable', (await page.locator('.int-error').first().textContent()).includes('Réseau'));
  check('bouton synchro re-cliquable après erreur', await page.locator('button[data-action="sync-platform"]:not([disabled])').count() === 1);
  jiraMode = 'ok';
  await page.unroute('http://relay.test/**');

  /* ---------- 8. Catégorie hors référentiel ---------- */
  await page.evaluate(k => {
    const s = JSON.parse(localStorage.getItem(k));
    s.platforms.find(p => p.id === 'p-kaas').checklist.push(
      { id: 'ghost.1', cat: 'ancienne-cat', label: 'Item d’un ancien référentiel', status: 'todo', team: '', due: '', comment: '' });
    localStorage.setItem(k, JSON.stringify(s));
  }, LS_KEY);
  await page.goto(APP_URL + '#/plateforme/p-kaas');
  await page.reload();
  await page.waitForTimeout(400);
  const kaasText = await page.locator('#view').textContent();
  check('catégorie hors référentiel visible', kaasText.includes('Hors référentiel — ancienne-cat') && kaasText.includes('Item d’un ancien référentiel'));

  /* ---------- 9. Multi-onglets (écouteur storage) ---------- */
  await page.click('a[href="#/plateformes"]');
  await page.waitForTimeout(200);
  await page.evaluate(k => {
    const s = JSON.parse(localStorage.getItem(k));
    s.platforms.find(p => p.id === 'p-kaas').name = 'KaaS renommé par un autre onglet';
    localStorage.setItem(k, JSON.stringify(s));
    window.dispatchEvent(new StorageEvent('storage', { key: k, newValue: 'x' }));
  }, LS_KEY);
  await page.waitForTimeout(300);
  check('multi-onglets : état rechargé', (await page.locator('#view').textContent()).includes('KaaS renommé par un autre onglet'));
  check('multi-onglets : toast affiché', (await page.locator('#toast-zone').textContent()).includes('autre onglet'));

  /* ---------- 10. Rappel d’export + sauvegardes ---------- */
  await page.goto(APP_URL + '#/tableau-de-bord');
  await page.waitForTimeout(400);
  check('rappel d’export affiché (jamais exporté)', (await page.locator('#view').textContent()).includes('export'));

  await page.goto(APP_URL + '#/parametres');
  await page.waitForTimeout(300);
  const bakRows = await page.locator('button[data-action="restore-backup"]').count();
  check('sauvegardes locales listées', bakRows >= 1, bakRows);
  const platformsBefore = await page.evaluate(k => JSON.parse(localStorage.getItem(k)).platforms.length, LS_KEY);
  await page.click('button[data-action="restore-backup"]');
  await page.waitForTimeout(400);
  check('restauration d’une sauvegarde', (await page.locator('#toast-zone').textContent()).includes('restaurée'));
  const platformsAfter = await page.evaluate(k => JSON.parse(localStorage.getItem(k)).platforms.length, LS_KEY);
  check('état cohérent après restauration', platformsAfter >= 1, platformsBefore + ' → ' + platformsAfter);

  /* ---------- 11. Thème sombre + mobile ---------- */
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto(APP_URL + '#/tableau-de-bord');
  await page.waitForTimeout(400);
  check('mode sombre : rendu sans erreur', await page.locator('.tile').count() >= 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.waitForTimeout(400);
  check('mobile : pas de débordement horizontal', await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1) === true);

  /* ---------- 12. Mode serveur : référentiel partagé multi-utilisateurs ---------- */
  const SRV_URL = 'http://127.0.0.1:18811';
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pmee-e2e-'));
  const srv = spawn('python3', [path.resolve(__dirname, '..', 'server.py'), '--port', '18811'],
    { env: { ...process.env, DATA_DIR: dataDir, ADMIN_EMAILS: 'admin@test', WRITE_EMAILS: 'alice@test,admin@test' }, stdio: 'ignore' });
  let srvUp = false;
  for (let i = 0; i < 40; i++) {
    try { const r = await fetch(SRV_URL + '/healthz'); if (r.ok) { srvUp = true; break; } } catch (e) {}
    await new Promise(r => setTimeout(r, 200));
  }
  check('serveur v2 démarré', srvUp);

  const ctxAlice = await browser.newContext({ viewport: { width: 1400, height: 900 },
    extraHTTPHeaders: { 'X-Auth-Request-Email': 'alice@test', 'X-Auth-Request-Preferred-Username': 'Alice Martin' } });
  const ctxBob = await browser.newContext({ viewport: { width: 1400, height: 900 },
    extraHTTPHeaders: { 'X-Auth-Request-Email': 'bob@test', 'X-Auth-Request-Preferred-Username': 'Bob Durand' } });
  const pa = await ctxAlice.newPage();
  const pb = await ctxBob.newPage();
  pa.on('pageerror', e => errors.push('srv-alice: ' + e.message));
  pb.on('pageerror', e => errors.push('srv-bob: ' + e.message));
  pa.on('dialog', d => d.accept());
  pb.on('dialog', d => d.accept());

  await pa.goto(SRV_URL + '/');
  await pa.waitForTimeout(900);
  check('Alice en mode serveur (contributrice)', (await pa.locator('#side-foot').textContent()).includes('Alice Martin'));

  await pa.click('button[data-action="new-platform"]');
  await pa.waitForTimeout(200);
  await pa.fill('#fp-name', 'Plateforme multi-utilisateurs');
  await pa.click('.modal button[type="submit"]');
  await pa.waitForTimeout(900);
  const srvState = await (await fetch(SRV_URL + '/api/state', { headers: { 'X-Auth-Request-Email': 'admin@test' } })).json();
  check('fiche persistée côté serveur', srvState.platforms.length === 1 && srvState.platforms[0].updatedBy === 'Alice Martin',
    JSON.stringify(srvState.platforms.map(p => p.updatedBy)));

  await pb.goto(SRV_URL + '/#/plateformes');
  await pb.waitForTimeout(900);
  check('Bob (lecteur) voit la fiche d’Alice', (await pb.locator('#view').textContent()).includes('Plateforme multi-utilisateurs'));
  check('Bob : bouton « Nouvelle plateforme » masqué', await pb.locator('button[data-action="new-platform"]').count() === 0);

  await pb.click('table.plist tbody tr:first-child');
  await pb.waitForTimeout(400);
  await pb.locator('.cat.open .item .chip.st').first().click();
  await pb.waitForTimeout(300);
  check('Bob : modification refusée (lecture seule)', (await pb.locator('#toast-zone').textContent()).includes('Lecture seule'));

  /* SSE : Alice renomme, Bob voit le nouveau nom sans recharger */
  await pb.goto(SRV_URL + '/#/plateformes');
  await pb.waitForTimeout(500);
  await pa.click('button[data-action="edit-platform"]');
  await pa.waitForTimeout(250);
  await pa.fill('#fp-name', 'Plateforme renommée en direct');
  await pa.click('.modal button[type="submit"]');
  await pa.waitForTimeout(1600);
  check('SSE : Bob voit le renommage en direct', (await pb.locator('#view').textContent()).includes('Plateforme renommée en direct'));

  /* Conflit : une écriture avec une révision périmée est rejetée puis rechargée */
  const conflict = await pa.evaluate(async () => {
    const st = await (await fetch('/api/state', { headers: { Accept: 'application/json' } })).json();
    const p = st.platforms[0];
    const r = await fetch('/api/platforms/' + encodeURIComponent(p.data.id), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rev: 0, data: Object.assign({}, p.data, { name: 'écrasement périmé' }) }),
    });
    return r.status;
  });
  check('conflit de révision → 409', conflict === 409, conflict);

  await ctxAlice.close();
  await ctxBob.close();
  srv.kill();

  /* ---------- Bilan ---------- */
  const realErrors = errors.filter(e => !e.includes('ERR_CONNECTION') && !e.includes('ERR_FAILED') && !e.includes('status of 400') && !e.includes('ERR_NAME_NOT_RESOLVED'));
  check('aucune erreur JS de page', realErrors.length === 0, realErrors.join(' | '));

  await browser.close();
  console.log(failures === 0 ? '\nTOUS LES TESTS PASSENT' : '\n' + failures + ' ÉCHEC(S)');
  process.exit(failures === 0 ? 0 : 1);
})().catch(e => { console.error('FATAL', e); process.exit(1); });
