const {test} = require('node:test');
const assert = require('node:assert/strict');
const checkPythonImages = require('../.github/scripts/check-python-images.cjs');

const digest = 'a'.repeat(64);
const dockerfile = (builder, runtime = builder) =>
  `FROM python:${builder}-trixie@sha256:${digest} AS builder\n` +
  `FROM python:${runtime}-slim-trixie@sha256:${digest}\n`;

test('accept matching stable patch versions and independent digest updates', () => {
  checkPythonImages(dockerfile('3.15.1'));
  checkPythonImages(dockerfile('3.15.2').replace(`sha256:${digest}`, `sha256:${'b'.repeat(64)}`));
});

test('allow an explicit upgrade of both stages to a new stable minor', () => {
  checkPythonImages(dockerfile('3.16.0'));
});

for (const version of ['3.16.0a1', '3.16.0b1', '3.16.0rc1', '3.16.0-dev', 'latest']) {
  test(`reject prerelease or floating Python tag ${version}`, () => {
    assert.throws(() => checkPythonImages(dockerfile(version)), /stable X.Y.Z/);
  });
}

test('reject the single-stage alpha upgrade from Dependabot PR 17', () => {
  assert.throws(() => checkPythonImages(dockerfile('3.16.0a1', '3.15.1')), /stable X.Y.Z/);
});

test('reject mismatched stable builder and runtime versions', () => {
  assert.throws(() => checkPythonImages(dockerfile('3.15.2', '3.15.1')), /versions must match/);
});

test('reject missing digest pins or a missing Python stage', () => {
  assert.throws(() => checkPythonImages(dockerfile('3.15.1').replaceAll(`@sha256:${digest}`, '')), /SHA-256 digest/);
  assert.throws(() => checkPythonImages(`FROM python:3.15.1-trixie@sha256:${digest}`), /Expected two/);
});
