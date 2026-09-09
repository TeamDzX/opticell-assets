// Runs the REAL dynamic-copy IIFE lifted out of home.html against a DOM shim.
// Checks the happy path, both failure paths, and that model text never
// reaches innerHTML.
const fs = require('fs');
const HTML = fs.readFileSync('/Users/alex/Desktop/Opticell/home.html', 'utf8');

const start = HTML.indexOf('/* ---- Dynamic copy');
if (start === -1) { console.error('could not find the dynamic-copy block'); process.exit(1); }
const openIdx = HTML.indexOf('(function () {', start);
const endIdx = HTML.indexOf('\n    })();', openIdx);
const CODE = HTML.slice(openIdx, endIdx + '\n    })();'.length);
if (!/function renderRepos/.test(CODE)) {
  console.error('renderRepos is not inside the dynamic-copy block'); process.exit(1);
}

const fails = [];
const check = (label, cond) => { if (!cond) fails.push(label); };

function makeEl(id) {
  const el = {
    id, hidden: true, textContent: '', children: [], className: '',
    _classes: new Set(), _attrs: {},
    classList: { add(c) { el._classes.add(c); }, contains: c => el._classes.has(c) },
    appendChild(c) { el.children.push(c); return c; },
    setAttribute(k, v) { el._attrs[k] = String(v); },
    getAttribute(k) { return el._attrs[k]; },
    set innerHTML(v) { fails.push(`innerHTML written on #${id}: ${String(v).slice(0, 60)}`); },
    get innerHTML() { return ''; },
  };
  return el;
}

function run({ payload, fetchFails = false }) {
  const els = {
    workshop: makeEl('workshop'),
    workshopStrip: makeEl('workshopStrip'),
    workshopItems: makeEl('workshopItems'),
    workshopIntro: makeEl('workshopIntro'),
    workshopDateline: makeEl('workshopDateline'),
    opensource: makeEl('opensource'),
    osGroups: makeEl('osGroups'),
    osProfile: makeEl('osProfile'),
    osProfileLabel: makeEl('osProfileLabel'),
  };
  const events = [];
  const doc = {
    getElementById: id => els[id] || null,
    createElement: tag => { const e = makeEl('<' + tag + '>'); e.tag = tag; e.tagName = tag.toUpperCase(); return e; },
    createTextNode: t => ({ text: String(t) }),
    addEventListener: () => {},
    dispatchEvent: e => { events.push(e); return true; },
  };
  const sandbox = {
    document: doc,
    fetch: () => fetchFails
      ? Promise.reject(new Error('network'))
      : Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }),
    AbortController: function () { this.signal = {}; this.abort = () => {}; },
    CustomEvent: function (type, init) { this.type = type; this.detail = init && init.detail; },
    setTimeout, clearTimeout,
    requestAnimationFrame: fn => fn(),
    Promise, Date, Array, String, Object, Error, isNaN,
  };
  const vm = require('vm');
  vm.createContext(sandbox);
  vm.runInContext(CODE, sandbox);
  return new Promise(r => setImmediate(() => setImmediate(() => r({ els, events }))));
}

const now = Date.now();
const iso = ms => new Date(ms).toISOString();
const DAY = 86400000;

const liveDoc = {
  schema: 1,
  editions: [
    { // expired -- must be ignored even though it is listed first
      id: '2026-08-01', publishedAt: iso(now - 40 * DAY), expiresAt: iso(now - 30 * DAY),
      dateline: '1 August 2026', intro: 'STALE INTRO', items: [], principles: { ads: 'stale' },
    },
    {
      id: '2026-09-08', publishedAt: iso(now - DAY), expiresAt: iso(now + 9 * DAY),
      dateline: '8 September 2026',
      intro: 'A steady week: two apps out, one of them a rewrite.',
      items: [
        { app: 'WorkFlow', version: '4.3.1', url: 'https://apps.apple.com/gb/app/x/id1',
          body: 'Attachments that are not a photo or a PDF now open in the app.' },
        { app: 'E-Grid', version: '2.2', url: 'javascript:alert(1)',
          body: 'A digest card on Home, refreshed every morning.' },
        { app: '', version: '9.9', url: 'https://x', body: 'no app name -- must be skipped' },
      ],
      principles: { ads: 'Refreshed ads copy.', bogus: 'not a real key' },
    },
  ],
};

(async () => {
  // ---- happy path --------------------------------------------------------
  let { els, events } = await run({ payload: liveDoc });
  check('section revealed', els.workshop.hidden === false);
  check('is-live class added', els.workshopStrip._classes.has('is-live'));
  check('intro is the LIVE edition, not the expired one',
    els.workshopIntro.textContent === 'A steady week: two apps out, one of them a rewrite.');
  check('dateline set', els.workshopDateline.textContent === '8 September 2026');
  check('two items rendered (blank app skipped)', els.workshopItems.children.length === 2);
  check('principles event fired', events.length === 1 && events[0].type === 'opticell:principles');
  check('principles detail carries the live edition',
    events[0] && events[0].detail && events[0].detail.ads === 'Refreshed ads copy.');

  // the javascript: URL must not have become a link
  const second = els.workshopItems.children[1];
  const heading2 = second.children[1].children[0];
  const linked = heading2.children.some(c => c.tag === 'a');
  check('javascript: URL rejected as a link', !linked);
  const first = els.workshopItems.children[0];
  const heading1 = first.children[1].children[0];
  check('https URL became a link', heading1.children.some(c => c.tag === 'a'));

  // ---- expired-only ------------------------------------------------------
  ({ els, events } = await run({
    payload: { editions: [liveDoc.editions[0]] },
  }));
  check('expired-only stays hidden', els.workshop.hidden === true);
  check('expired-only fires no principles event', events.length === 0);

  // ---- fetch failure -----------------------------------------------------
  ({ els, events } = await run({ payload: null, fetchFails: true }));
  check('dead fetch stays hidden', els.workshop.hidden === true);
  check('dead fetch fires no principles event', events.length === 0);

  // ---- malformed payload -------------------------------------------------
  ({ els } = await run({ payload: { editions: 'not an array' } }));
  check('malformed payload stays hidden', els.workshop.hidden === true);

  // ---- empty intro -------------------------------------------------------
  ({ els } = await run({
    payload: { editions: [{ ...liveDoc.editions[1], intro: '   ' }] },
  }));
  check('blank intro stays hidden', els.workshop.hidden === true);

  // ---- repos: top level, must render with NO live edition -----------------
  const REPOS = {
    user: 'TeamDzX', profileUrl: 'https://github.com/TeamDzX', total: 17,
    groups: [
      { id: 'tools', label: 'Open tools', blurb: 'Things you can run.', items: [
        { name: 'myllm-connect', description: 'Private AI backend.', language: 'Rust',
          stars: 4, pushedAt: '2026-06-10', url: 'https://github.com/TeamDzX/myllm-connect' },
        { name: 'evil', description: 'x', language: '', stars: 0, pushedAt: '',
          url: 'javascript:alert(1)' },
        { name: '', description: 'no name', url: 'https://github.com/TeamDzX/x' },
      ] },
      { id: 'empty', label: 'Nothing here', blurb: '', items: [] },
    ],
  };

  ({ els } = await run({ payload: { editions: [liveDoc.editions[0]], repos: REPOS } }));
  check('repos render with only an EXPIRED edition', els.opensource.hidden === false);
  check('strip still hidden in that case', els.workshop.hidden === true);
  check('empty group produced no block', els.osGroups.children.length === 1);
  const grid = els.osGroups.children[0].children[1];
  check('two valid repos rendered (blank name skipped)', grid.children.length === 2);
  check('https repo became a link', grid.children[0].tagName === 'A');
  check('javascript: repo did NOT become a link', grid.children[1].tagName === 'DIV');
  check('profile label counts the total', els.osProfileLabel.textContent === 'See all 17 repositories on GitHub');

  // ---- repos absent or malformed: section stays hidden ---------------------
  ({ els } = await run({ payload: { editions: [], repos: null } }));
  check('no repos block -> section hidden', els.opensource.hidden === true);
  ({ els } = await run({ payload: { editions: [], repos: { groups: [] } } }));
  check('empty groups -> section hidden', els.opensource.hidden === true);
  ({ els } = await run({ payload: { editions: [], repos: { groups: 'nope' } } }));
  check('malformed groups -> section hidden', els.opensource.hidden === true);

  if (fails.length) {
    console.log(`FAIL (${fails.length})`);
    fails.forEach(f => console.log(' -', f));
    process.exit(1);
  }
  console.log('All render checks passed.');
})();
