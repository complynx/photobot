const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/fit_frame.mjs'), 'utf8');

function editor(initialTransform) {
  const noop = () => {};
  const frames = [];
  const encodings = [], uploads = [];
  let draws = 0;
  const photo = {naturalWidth: 1200, naturalHeight: 1600, complete: true, addEventListener: noop};
  const canvas = () => {
    const element = {style: {}, addEventListener: noop, toBlob: callback => encodings.push(callback)};
    element.getContext = () => ({canvas: element, clearRect: noop, save: noop, restore: noop,
      translate: noop, scale: noop, rotate: noop, drawImage: image => {if (image === photo) draws++;}});
    return element;
  };
  const elements = {'.help': {}, '.photo': {clientWidth: 390, clientHeight: 700},
    '.photo img': photo, '.frame_source': {complete: true}, '.overlay': {}};
  const button = {setText: noop, show: noop, onClick: noop};
  const sandbox = {console, document: {querySelector: s => elements[s] || null, createElement: canvas,
    body: {appendChild: noop, addEventListener: noop}, addEventListener: noop},
    window: {devicePixelRatio: 3, addEventListener: noop, initial_transform: initialTransform,
      location: {href: 'https://test.invalid/photobot/fit_frame?id=demo'}},
    URL, photo_id: 'demo', alert: noop,
    fetch: (url, options) => {uploads.push(options); return Promise.resolve({ok: true, json: async () => ({})});},
    requestAnimationFrame: f => {frames.push(f); return frames.length;},
    Telegram: {WebApp: {ready: noop, expand: noop, isVersionAtLeast: () => true,
      disableVerticalSwipes: noop, onEvent: noop, close: noop, initData: 'test', platform: 'ios', MainButton: button, BackButton: button}},
    real_frame_size: 1080, help_mobile: '', finish_button_text: ''};
  vm.createContext(sandbox); vm.runInContext(source, sandbox);
  const flush = () => {while (frames.length) frames.shift()();};
  flush(); draws = 0;
  return {
    event(handler, points) {
      sandbox.event = {preventDefault: noop, touches: points.map(([identifier, clientX, clientY]) => ({identifier, clientX, clientY}))};
      vm.runInContext(`${handler}(event)`, sandbox);
    },
    state: () => JSON.parse(vm.runInContext('JSON.stringify(decompose(transformationMatrix))', sandbox)),
    run: expression => vm.runInContext(expression, sandbox), flush,
    draws: () => draws, pendingFrames: () => frames.length,
    encode: () => encodings.shift()({}), uploads,
  };
}
function near(actual, expected) {assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);}

test('two-finger translation follows the moving midpoint', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 100, 200], [2, 200, 200]]);
  e.event('onTouchMove', [[1, 120, 230], [2, 220, 230]]);
  near(e.state().translation.x, 20 * 1080 / 390);
  near(e.state().translation.y, 30 * 1080 / 390);
});

test('drag resumes immediately after two fingers become one', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 100, 200], [2, 200, 200]]);
  e.event('onTouchEnd', [[2, 200, 200]]);
  e.event('onTouchMove', [[2, 210, 220]]);
  near(e.state().translation.x, 10 * 1080 / 390);
  near(e.state().translation.y, 20 * 1080 / 390);
});

test('touch list order does not rotate the image', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 100, 200], [2, 200, 200]]);
  e.event('onTouchMove', [[2, 200, 200], [1, 100, 200]]);
  near(e.state().rotation, 0);
});

test('rotation and pinch are composed once with the correct pivot', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 145, 350], [2, 245, 350]]);
  e.event('onTouchMove', [[1, 195, 250], [2, 195, 450]]);
  near(e.state().rotation, Math.PI / 2);
  near(e.state().scaling.x, 2 * 1080 / 1200);
  near(e.state().translation.x, 0); near(e.state().translation.y, 0);
  assert.equal(e.draws(), 0); e.flush(); assert.equal(e.draws(), 1);
});

test('cancel and replacement fingers rebase without jumping', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 100, 200]]);
  e.event('onTouchCancel', []);
  e.event('onTouchMove', [[2, 300, 500]]);
  near(e.state().translation.x, 0);
  e.event('onTouchMove', [[2, 310, 500]]);
  near(e.state().translation.x, 10 * 1080 / 390);
});

test('coincident fingers keep a finite transform', () => {
  const e = editor();
  e.event('onTouchStart', [[1, 100, 200], [2, 100, 200]]);
  e.event('onTouchMove', [[1, 110, 220], [2, 110, 220]]);
  assert.ok(e.run('transformationMatrix.flat().every(Number.isFinite)'));
});

test('several input events share one animation frame', () => {
  const e = editor(); e.event('onTouchStart', [[1, 100, 200]]);
  for (let x = 101; x <= 110; x++) e.event('onTouchMove', [[1, x, 200]]);
  assert.equal(e.pendingFrames(), 1); e.flush(); assert.equal(e.draws(), 1);
  near(e.state().translation.x, 10 * 1080 / 390);
});

test('Retina preview is bounded without changing export resolution', () => {
  const e = editor(); assert.equal(e.run('viewer.width'), 780);
  assert.equal(e.run('real_frame_size'), 1080);
});

test('export metadata uses the rendered snapshot even if fingers keep moving', () => {
  const e = editor();
  const snapshot = e.run('JSON.stringify(transformationMatrix)');
  e.run('exportData()');
  e.event('onTouchStart', [[1, 100, 200]]);
  e.event('onTouchMove', [[1, 200, 300]]);
  e.encode();
  assert.equal(e.uploads[0].headers['X-Photo-Transform'], snapshot);
});

test('reopening an editor restores its saved position', () => {
  const e = editor([[1, 0, 50], [0, 1, -20]]);
  near(e.state().translation.x, 50); near(e.state().translation.y, -20);
});
