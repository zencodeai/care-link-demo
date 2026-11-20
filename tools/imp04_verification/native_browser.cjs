const fs = require('node:fs');
const crypto = require('node:crypto');
const {chromium} = require('/opt/playwright-core');
process.umask(0o077);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const observations = [];
const labels = {
  'en-CA': {check:'Check current access', search:'Refresh sourced options',
    open:'Open current plan', title:'Plans, sharing and service options',
    ready:'Current information loaded.', committed:'Committed. Current views were refreshed.',
    invalid:'The service returned an invalid result or the form is incomplete.',
    states:['Normal operations — availability requires current evidence',
      'Temporary closure — unavailable', 'Regional outage — unavailable',
      'Holiday hours — verify current hours and eligibility',
      'Severe weather — verify current hours and eligibility',
      'Source API failure — availability unknown', 'Conflicting sources — availability unknown']},
  'fr-CA': {check:'Vérifier l’accès actuel', search:'Actualiser les options sourcées',
    open:'Ouvrir le plan actuel', title:'Plans, partage et options de service',
    ready:'Les informations actuelles sont chargées.',
    committed:'Enregistré. Les vues actuelles ont été actualisées.',
    invalid:'Le service a renvoyé un résultat invalide ou le formulaire est incomplet.',
    states:['Activités normales — disponibilité selon les preuves actuelles',
      'Fermeture temporaire — indisponible', 'Panne régionale — indisponible',
      'Horaire férié — vérifier heures et admissibilité',
      'Intempéries — vérifier heures et admissibilité',
      'Défaillance API — disponibilité inconnue', 'Sources contradictoires — disponibilité inconnue']}
};
const metrics = page => page.evaluate(() => ({
  dpr:devicePixelRatio, width:innerWidth, outer:outerWidth,
  pinch:visualViewport.scale, height:innerHeight
}));
function ensure(value) {
  if (!value) {const error = new Error('qualification_failed');
    error.name = 'QualificationAssertion'; throw error;}
}
function workspaceReady({notices, controlName}) {
  const workspace = document.querySelector('section[aria-labelledby="plans-title"]');
  const notice = workspace?.querySelector(':scope > [role="status"], :scope > [role="alert"]');
  const control = Array.from(workspace?.querySelectorAll('button') || [])
    .find(button => button.textContent === controlName);
  return notices.includes(notice?.textContent) && !!control && !control.disabled &&
    !control.closest('[hidden],[inert]');
}
function failure(row, error, stage, substage) {
  row.status = 'failed';
  if (row.error_category) return;
  row.stage = stage;
  row.substage = substage;
  row.error_category = error.name === 'TimeoutError' ? 'driver_timeout' :
    error.name === 'QualificationAssertion' ? 'check_failed' : 'driver_error';
}
async function identity(response, actor) {
  ensure(response.status() === 200);
  const value = await response.json();
  ensure(value.account_id === actor.account_id && value.role === actor.role &&
    value.assurance === 'AL2');
}
async function qualify(page, zoom, actor, locale, row, state) {
  let baseline, stage = 'baseline', substage = 'start';
  try {
    stage = 'baseline';
    substage = 'navigate';
    await zoom.selectOption('1');
    ensure((await page.goto(input.origin)).status() === 200);
    await page.locator('#language').selectOption(locale);
    await page.waitForFunction(lang => document.documentElement.lang === lang, locale);
    await page.getByRole('heading', {name:labels[locale].title, exact:true})
      .waitFor({state:'visible'});
    stage = 'identity';
    substage = 'http_status';
    const current = await page.evaluate(async origin => {
      const reply = await fetch(origin + '/v1/auth/session', {
        credentials:'same-origin', redirect:'error', signal:AbortSignal.timeout(10000)
      });
      const body = await reply.json();
      return {status:reply.status, account_id:body.account_id, role:body.role,
        assurance:body.assurance};
    }, input.origin);
    row.initial_session_status = current.status;
    ensure(current.status === 200 && current.account_id === actor.account_id &&
      current.role === actor.role && current.assurance === 'AL2');
    const workspace = page.locator('section[aria-labelledby="plans-title"]');
    const check = workspace.getByRole('button', {name:labels[locale].check, exact:true});
    await check.waitFor({state:'visible'});
    baseline = state.baseline = await metrics(page);
    stage = 'access_check';
    substage = 'activate';
    const accessResponse = page.waitForResponse(r => r.url() === input.origin +
      '/v1/auth/session' && r.request().method() === 'GET');
    const [access] = await Promise.all([accessResponse, check.press('Enter')]);
    substage = 'http_status';
    await identity(access, actor);
    substage = 'wait_ready';
    await page.waitForFunction(workspaceReady,
      {notices:[labels[locale].ready],controlName:labels[locale].check});
    stage = 'directory_search';
    substage = 'enabled';
    const search = page.getByRole('button', {name:labels[locale].search, exact:true});
    await page.waitForFunction(workspaceReady,
      {notices:[labels[locale].ready],controlName:labels[locale].search});
    const searchResponse = page.waitForResponse(r => r.url() === input.origin +
      '/v1/directory/search' && r.request().method() === 'POST');
    substage = 'activate';
    const [searched] = await Promise.all([searchResponse, search.press('Enter')]);
    substage = 'http_status';
    row.directory_status = searched.status();
    ensure(searched.status() === 200);
    substage = 'wait_ready';
    await page.waitForFunction(workspaceReady,
      {notices:[labels[locale].ready, labels[locale].committed],controlName:labels[locale].check});
    substage = 'localized_labels';
    const options = page.locator('section[aria-labelledby="directory-title"]');
    for (const label of labels[locale].states)
      await options.getByText(label, {exact:true}).waitFor({state:'visible'});
    stage = 'invalid_plan';
    substage = 'activate';
    const planId = page.locator('#plans-id');
    let invalidReads = 0;
    const countInvalidRead = request => {
      const url = new URL(request.url());
      if (url.origin === input.origin && url.pathname.startsWith('/v1/plans/') &&
          request.method() === 'GET') invalidReads++;
    };
    page.on('request', countInvalidRead);
    try {
      await planId.fill('not-a-uuid');
      await planId.press('Enter');
      await workspace.getByRole('alert').filter({hasText:labels[locale].invalid})
        .waitFor({state:'visible'});
      ensure(invalidReads === 0);
    } finally {page.off('request', countInvalidRead);}
    stage = 'input_focus';
    substage = 'wait_ready';
    await page.waitForFunction(workspaceReady,
      {notices:[labels[locale].ready, labels[locale].committed],controlName:labels[locale].open});
    substage = 'focus_input';
    await planId.focus();
    substage = 'tab';
    await page.keyboard.press('Tab');
    const open = workspace.getByRole('button', {name:labels[locale].open, exact:true});
    substage = 'focus_assert';
    ensure(await open.evaluate(el => el === document.activeElement && el.tagName === 'BUTTON'));
    stage = 'axe_scan';
    substage = 'scan';
    ensure(await page.locator('iframe,frame').count() === 0);
    await page.evaluate(input.axe_source);
    const axe = await page.evaluate(async tags => {
      const result = await window.axe.run(document, {runOnly:{type:'tag', values:tags}});
      return {violations:result.violations.map(v => ({rule:v.id, impact:v.impact,
        affected_nodes:v.nodes.length})), passed_rule_count:result.passes.length,
        incomplete_rule_count:result.incomplete.length};
    }, input.axe_tags);
    Object.assign(row, {accessibility:{...axe, tags:input.axe_tags,
      source_sha256:input.axe_sha256, axe_version:input.axe_version,
      current_access_status:access.status(), directory_search_status:searched.status(),
      keyboard_input_to_submit_focus:true, invalid_plan_alert:true,
      invalid_plan_get_count:invalidReads, localized_state_count:labels[locale].states.length,
      assurance:'AL2', frame_count:0}});
    ensure(axe.passed_rule_count > 0 && axe.violations.length === 0);
    stage = 'native_zoom';
    substage = 'zoom';
    await zoom.selectOption('2');
    await page.waitForFunction(dpr => Math.abs(devicePixelRatio/dpr - 2) < .02,
      baseline.dpr);
    const enlarged = await metrics(page);
    ensure(Math.abs(enlarged.width*2 - baseline.width) <= 2);
    ensure(Math.abs(enlarged.outer - baseline.outer) <= 1);
    ensure(Math.abs(enlarged.pinch - baseline.pinch) < .01);
    stage = 'keyboard';
    substage = 'walk_tabs';
    await page.bringToFront();
    await page.evaluate(() => document.activeElement?.blur());
    let tabs = 0;
    for (; tabs < 80; tabs++) {
      await page.keyboard.press('Tab');
      if (await check.evaluate(el => el === document.activeElement)) break;
    }
    row.keyboard_tabs = tabs + 1;
    ensure(tabs < 80 && await check.isEnabled());
    substage = 'visible_bounds';
    const reachable = await check.evaluate(el => {
      const r = el.getBoundingClientRect();
      return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight;
    });
    ensure(reachable);
    substage = 'activate';
    const response = page.waitForResponse(r => r.url() === input.origin +
      '/v1/auth/session' && r.request().method() === 'GET');
    const [checked] = await Promise.all([response, page.keyboard.press('Enter')]);
    substage = 'http_status';
    row.session_status = checked.status();
    await identity(checked, actor);
    substage = 'wait_ready';
    await page.waitForFunction(workspaceReady,
      {notices:[labels[locale].ready],controlName:labels[locale].check});
    row.current_access_completed_200 = true;
    stage = 'scroll';
    substage = 'scroll';
    const limit = await page.evaluate(() =>
      document.documentElement.scrollHeight-innerHeight);
    await page.keyboard.press('Control+End');
    if (limit > 0) await page.waitForFunction(() => scrollY > 0);
    const end = await page.evaluate(() => scrollY);
    await page.keyboard.press('Control+Home');
    await page.waitForFunction(() => scrollY === 0);
    Object.assign(row, {status:'passed', stage:'complete', baseline, enlarged,
      keyboard_tabs:tabs+1, control_reachable:true, session_status:200,
      scroll_end:end, scroll_limit:limit});
  } catch (error) {failure(row,error,stage,substage);}
}
(async () => {
  ensure(crypto.createHash('sha256').update(input.axe_source).digest('hex') === input.axe_sha256);
  ensure(input.axe_version === '4.14.0');
  let expired = false, cleanupBlocked = false, currentContext;
  const watchdog = setTimeout(() => {
    expired = true;
    if (currentContext) currentContext.close().catch(() => {});
  }, 210000);
  try {
    for (const actor of input.actors) for (const locale of input.locales) {
      const row = {slot:actor.slot,account_id:actor.account_id,role:actor.role,locale,
        status:'failed',stage:'launch',profile_removed:false,
        cleanup:{status:'not_run',zoom_restored:false,page_unloaded:false,
          context_closed:false,profile_removed:false,failures:[]}};
      observations.push(row);
      if (expired || cleanupBlocked) {
        failure(row,{name:'Stopped'},expired?'deadline':'cleanup',expired?'start':'close');
        if (expired) row.deadline_elapsed = true;
        continue;
      }
      const profile = fs.mkdtempSync('/tmp/imp04-native-zoom-');
      fs.chmodSync(profile,0o700);
      let context, settings, page, stage = 'launch';
      const state = {};
      const cleanupFailure = (error,stage,substage) => {
        const detail = {};
        failure(detail,error,stage,substage);
        row.cleanup.failures.push({stage:detail.stage,substage:detail.substage,
          error_category:detail.error_category});
        failure(row,error,stage,substage);
      };
      try {
        context = await chromium.launchPersistentContext(profile, {
          executablePath:'/opt/chrome-for-testing/chrome',headless:true,
          ignoreHTTPSErrors:false,viewport:{width:1440,height:1100},timeout:10000,
          args:['--host-resolver-rules=MAP plans.localhost '+input.address_pin]
        });
        currentContext = context;
        context.setDefaultTimeout(10000);
        context.setDefaultNavigationTimeout(10000);
        ensure(!expired);
        await context.addCookies(actor.cookies);
        stage = 'settings';
        settings = await context.newPage();
        await settings.goto('chrome://settings/appearance');
        const zoom = settings.locator('#zoomLevel');
        ensure(await zoom.locator('option[value="1"]').count() === 1);
        ensure(await zoom.locator('option[value="2"]').count() === 1);
        page = await context.newPage();
        await qualify(page,zoom,actor,locale,row,state);
      } catch (error) {
        failure(row,error,expired?'deadline':stage,'start');
      } finally {
        try {
          if (settings) {
            await settings.locator('#zoomLevel').selectOption('1');
            if (state.baseline && page) {
              await page.waitForFunction(before =>
                Math.abs(devicePixelRatio-before.dpr)<.01 &&
                Math.abs(innerWidth-before.width)<=1,state.baseline);
              row.zoom_restored = row.cleanup.zoom_restored = true;
            }
          }
        } catch (error) {cleanupFailure(error,'restore_zoom','restore');}
        try {
          if (page) {
            await page.goto('about:blank',{waitUntil:'load'});
            row.cleanup.page_unloaded = true;
          }
        } catch (error) {cleanupFailure(error,'unload','navigate');}
        try {
          if (context) {
            await context.close();
            row.cleanup.context_closed = true;
          }
          ensure(profile.startsWith('/tmp/imp04-native-zoom-'));
          fs.rmSync(profile,{recursive:true,force:true});
          row.profile_removed = row.cleanup.profile_removed = true;
        } catch (error) {cleanupFailure(error,'cleanup','close');}
        if (context && !row.cleanup.context_closed) cleanupBlocked = true;
        else currentContext = undefined;
        row.cleanup.status = row.cleanup.failures.length ? 'failed' : 'passed';
        if (expired) {
          failure(row,{name:'Deadline'},'deadline','start');
          row.deadline_elapsed = true;
        }
      }
    }
  } finally {clearTimeout(watchdog);}
  console.log(JSON.stringify({version:input.version,observations}));
})().catch(() => {
  console.log(JSON.stringify({error:'native_zoom_runner_failed'}));process.exitCode=1;
});
