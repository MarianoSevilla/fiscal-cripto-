/* Unit checks of the real Home script and shared session renderer.
 * Tiny DOM fixture: no browser, network, real accounts, or provider calls.
 * Run: node fiscal_app_export/tests/test_home_apple_session.js
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const staticDir = path.join(__dirname, '../static');
const home = fs.readFileSync(path.join(staticDir, 'landing_apple.js'), 'utf8');
const shared = fs.readFileSync(path.join(staticDir, 'nav.js'), 'utf8');
const menuSource = shared.slice(shared.indexOf('    function addLink('), shared.indexOf("    toggle.addEventListener('click'"));
const sessionSource = shared.slice(shared.indexOf('  async function updateAuthState()'), shared.indexOf('  // ── Init principal'));

function fixture() {
  const observers = [];
  const timers = new Map();
  const ids = new Map();
  const listeners = new Map();
  let timerId = 0;
  let clock = 0;
  let mutations = false;
  let document;
  const mutate = () => { mutations = true; };
  class Element {
    constructor(tag = 'div', id = '', classes = '') {
      this.tagName = tag.toUpperCase(); this.id = id; this.children = [];
      this.parentElement = null; this.attrs = {}; this.textContent = ''; this.hidden = false;
      this.classes = new Set(classes.split(/\s+/).filter(Boolean));
      this.classList = {
        contains: value => this.classes.has(value),
        add: value => { if (!this.classes.has(value)) { this.classes.add(value); mutate(); } },
        remove: value => { if (this.classes.delete(value)) mutate(); },
      };
      if (id) ids.set(id, this);
    }
    get className() { return [...this.classes].join(' '); }
    set className(value) { this.classes = new Set(value.split(/\s+/).filter(Boolean)); mutate(); }
    get href() { return this.getAttribute('href'); }
    set href(value) { this.setAttribute('href', value); }
    setAttribute(name, value) { this.attrs[name] = String(value); mutate(); }
    getAttribute(name) { return this.attrs[name] ?? null; }
    removeAttribute(name) { delete this.attrs[name]; mutate(); }
    appendChild(child) {
      if (child.parentElement) child.parentElement.children.splice(child.parentElement.children.indexOf(child), 1);
      child.parentElement = this; this.children.push(child); mutate(); return child;
    }
    remove() {
      if (!this.parentElement) return;
      this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1);
      this.parentElement = null;
      if (this.contains(document.activeElement)) document.activeElement = document.body;
      mutate();
    }
    replaceChildren() { [...this.children].forEach(child => child.remove()); }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    querySelectorAll(selector) {
      if (selector === '.snav-links a') return [];
      const matches = node => selector === 'a' ? node.tagName === 'A' :
        selector === '[role="menuitem"]' ? node.getAttribute('role') === 'menuitem' :
          node.classList.contains(selector.slice(1));
      const all = [];
      const visit = node => { node.children.forEach(child => { if (matches(child)) all.push(child); visit(child); }); };
      visit(this); return all;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener() {}
    focus() {
      document.activeElement = this;
      (listeners.get('focusin') || []).forEach(callback => callback({ target: this }));
    }
  }
  const body = new Element('body', '', 'apple-home');
  document = {
    body, activeElement: body,
    getElementById: id => ids.get(id) || null,
    createElement: tag => new Element(tag),
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: (event, callback) => listeners.set(event, [...(listeners.get(event) || []), callback]),
    removeEventListener: (event, callback) => listeners.set(event, (listeners.get(event) || []).filter(item => item !== callback)),
  };
  const nav = body.appendChild(new Element('nav', 'site-nav'));
  const right = nav.appendChild(new Element('div', '', 'snav-right'));
  const skeleton = right.appendChild(new Element('div', 'snavSkeleton', 'snav-skeleton'));
  const login = right.appendChild(new Element('a', 'snavBtnLogin', 'snav-btn-login snav-hidden'));
  login.href = '/login/'; login.textContent = 'Iniciar sesión';
  const signup = right.appendChild(new Element('a', 'snavBtnSignup', 'snav-btn-cta snav-hidden'));
  signup.href = '/signup/'; signup.textContent = 'Crea tu cuenta gratis';
  const panel = right.appendChild(new Element('div', 'snavAvatarWrap', 'snav-hidden'));
  panel.appendChild(new Element('button', 'snavAvatar'));
  const dropdown = panel.appendChild(new Element('div', 'snavDropdown'));
  const fields = ['snavItemPlanes','snavItemAccount','snavItemDash','snavItemStats','snavItemAdminAsesoria','snavItemAdminComms','snavItemAdminRecursos','snavItemMisSolicitudes'];
  fields.forEach((id, index) => {
    const el = dropdown.appendChild(new Element('a', id, 'snav-dd-item' + ([1,2].includes(index) ? '' : ' snav-hidden')));
    el.href = '/' + id; el.textContent = id;
  });
  const logout = dropdown.appendChild(new Element('button', 'snavBtnLogout', 'snav-dd-item danger'));
  logout.textContent = 'Cerrar sesión';
  nav.appendChild(new Element('button', 'snavMenuToggle'));
  const menu = nav.appendChild(new Element('div', 'snavMobileMenu'));
  let settle;
  let fail;
  let requests = 0;
  const response = new Promise((resolve, reject) => { settle = resolve; fail = reject; });
  const context = vm.createContext({
    document, window: { addEventListener() {} }, Intl, Date, Array,
    nav, menu, requestAnimationFrame: callback => callback(),
    MutationObserver: class {
      constructor(callback) { this.callback = callback; this.active = true; observers.push(this); }
      observe() {} disconnect() { this.active = false; }
    },
    setTimeout: (callback, delay) => { const id = ++timerId; timers.set(id, { callback, due: clock + delay }); return id; },
    clearTimeout: id => timers.delete(id),
    fetch: () => { requests += 1; return response; },
  });
  vm.runInContext('let refreshMobileMenu;\n' + menuSource + '\n' + sessionSource, context);
  vm.runInContext('updateAuthState()', context);
  vm.runInContext(home, context);
  function flush() {
    let count = 0;
    while (mutations) {
      assert.ok(++count < 20, 'mutation observer must settle'); mutations = false;
      observers.filter(observer => observer.active).forEach(observer => observer.callback());
    }
  }
  function advance(ms) {
    clock += ms;
    for (const [id, timer] of [...timers]) if (timer.due <= clock) { timers.delete(id); timer.callback(); }
    flush();
  }
  async function finish(user, error = false) {
    if (error) fail(new Error('synthetic offline'));
    else settle({ ok: true, json: async () => ({ user }) });
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    flush();
  }
  return { document, ids, right, menu, nav, panel, skeleton, login, signup, advance, finish, flush,
    rebuild: () => { vm.runInContext('refreshMobileMenu()', context); flush(); },
    fallbacks: () => nav.querySelectorAll('.apple-access-fallback'),
    requests: () => requests,
  };
}

(async function run() {
  let cases = 0;
  for (const user of [null, { full_name: 'Usuario ficticio' }, { is_fiscal_advisor: true }, { is_admin: true }]) {
    const f = fixture();
    await f.finish(user); f.advance(10_000);
    assert.equal(f.fallbacks().length, 0, 'fast reply must leave the approved header intact');
    assert.equal(f.login.classList.contains('snav-hidden'), Boolean(user));
    assert.equal(f.panel.classList.contains('snav-hidden'), !user);
    assert.equal(f.signup.textContent, 'Crear cuenta');
    assert.equal(f.requests(), 1, 'Home must not add a session request'); cases += 1;
  }
  for (const user of [null, { full_name: 'Usuario ficticio' }, { is_fiscal_advisor: true }, { is_admin: true }]) {
    const f = fixture();
    f.advance(3999); assert.equal(f.fallbacks().length, 0);
    f.advance(1); assert.equal(f.fallbacks().length, 2);
    for (const node of f.fallbacks()) assert.deepEqual(node.querySelectorAll('a').map(link => link.href), ['/login/', '/signup/']);
    assert.ok(f.panel.classList.contains('snav-hidden'), 'fallback must not imply authentication');
    f.rebuild(); assert.equal(f.menu.querySelectorAll('.apple-access-fallback').length, 1, 'mobile refresh retains public access');
    f.advance(6000); assert.equal(f.fallbacks().length, 2, 'pending lookup retains links at ten seconds');
    const oldLink = f.right.querySelector('.apple-access-fallback').querySelectorAll('a')[0];
    oldLink.focus();
    await f.finish(user);
    assert.equal(f.fallbacks().length, 0, 'late reply removes both fallbacks');
    assert.equal(f.document.activeElement.id, user ? 'snavAvatar' : 'snavBtnLogin');
    assert.equal(f.login.classList.contains('snav-hidden'), Boolean(user));
    assert.equal(f.ids.get('snavItemAdminAsesoria').classList.contains('snav-hidden'), !(user && (user.is_admin || user.is_fiscal_advisor)));
    assert.equal(f.ids.get('snavItemStats').classList.contains('snav-hidden'), !(user && user.is_admin));
    assert.equal(f.requests(), 1); cases += 1;
  }
  for (const delayed of [false, true]) {
    const f = fixture(); if (delayed) f.advance(4000);
    await f.finish(null, true); f.advance(10_000);
    assert.equal(f.fallbacks().length, 0);
    assert.equal(f.login.classList.contains('snav-hidden'), false);
    assert.equal(f.signup.classList.contains('snav-hidden'), false);
    assert.equal(f.requests(), 1); cases += 1;
  }
  for (const user of [null, { full_name: 'Usuario ficticio' }]) {
    const f = fixture(); f.advance(4000);
    f.menu.querySelector('.apple-access-fallback').querySelectorAll('a')[0].focus();
    await f.finish(user);
    assert.equal(f.fallbacks().length, 0);
    assert.equal(f.document.activeElement, user ? f.ids.get('snavMenuToggle') : f.menu.querySelectorAll('a').find(link => link.href === '/login/'), 'late mobile reply restores focus after the shared menu rebuild');
    cases += 1;
  }
  console.log('Home session: ' + cases + ' synthetic scenarios PASS; real browser QA remains pending');
})().catch(error => { console.error(error); process.exitCode = 1; });
