const {test} = require('node:test');
const assert = require('node:assert/strict');
const mergeDependabot = require('../.github/scripts/dependabot-merge.cjs');

function fixture() {
  const calls = [];
  const pr = {
    number: 2, user: {login: 'dependabot[bot]', type: 'Bot'}, state: 'open', draft: false,
    base: {ref: 'main'}, head: {sha: 'tested', ref: 'dependabot/pip/certifi', repo: {full_name: 'complynx/photobot'}},
    mergeable: true,
  };
  const run = {event: 'pull_request', conclusion: 'success', head_sha: 'tested', head_repository: {full_name: 'complynx/photobot'}};
  const checks = [{name: 'container', app: {slug: 'github-actions'}, status: 'completed', conclusion: 'success'}];
  const status = {total_count: 0, state: 'pending'};
  const reviews = [];
  const rest = {
    repos: {listPullRequestsAssociatedWithCommit: 'pulls', getCombinedStatusForRef: async () => ({data: status})},
    checks: {listForRef: 'checks'},
    pulls: {
      get: async () => ({data: pr}), listReviews: 'reviews',
      createReview: async args => calls.push(['approve', args]),
      merge: async args => { calls.push(['merge', args]); return {data: {merged: true}}; },
    },
    actions: {createWorkflowDispatch: async args => calls.push(['dispatch', args])},
  };
  const github = {rest, paginate: async endpoint => ({pulls: [{number: 2}], checks, reviews})[endpoint]};
  const execute = () => mergeDependabot({github, context: {repo: {owner: 'complynx', repo: 'photobot'}, payload: {workflow_run: run}}, core: {info() {}}, wait: async () => {}});
  return {calls, pr, run, checks, status, reviews, rest, execute};
}

test('approve the tested commit, merge with SHA fencing, then dispatch publication', async () => {
  const f = fixture();
  await f.execute();
  assert.deepEqual(f.calls.map(c => c[0]), ['approve', 'merge', 'dispatch']);
  assert.equal(f.calls[0][1].commit_id, 'tested');
  assert.equal(f.calls[1][1].sha, 'tested');
  assert.equal(f.calls[2][1].workflow_id, 'build.yml');
});

for (const [name, alter] of Object.entries({
  'human PR': f => { f.pr.user.login = 'complynx'; },
  'foreign fork': f => { f.pr.head.repo.full_name = 'someone/photobot'; },
  'stale successful CI': f => { f.pr.head.sha = 'new-untested'; },
  'failed CI': f => { f.run.conclusion = 'failure'; },
  'push CI': f => { f.run.event = 'push'; },
  'pending check': f => { f.checks[0].status = 'in_progress'; },
  'missing CI check': f => { f.checks.length = 0; },
  'failed check': f => { f.checks[0].conclusion = 'failure'; },
  'pending status': f => { f.status.total_count = 1; },
  'conflicted PR': f => { f.pr.mergeable = false; },
  'requested changes': f => { f.reviews.push({user: {login: 'reviewer'}, state: 'CHANGES_REQUESTED'}); },
})) {
  test(`do not approve or merge ${name}`, async () => {
    const f = fixture(); alter(f); await f.execute(); assert.deepEqual(f.calls, []);
  });
}

test('do not publish when GitHub refuses the merge', async () => {
  const f = fixture();
  f.rest.pulls.merge = async () => ({data: {merged: false}});
  await assert.rejects(f.execute(), /did not merge/);
  assert.deepEqual(f.calls.map(c => c[0]), ['approve']);
});

test('retry temporary unknown mergeability', async () => {
  const f = fixture();
  let reads = 0;
  f.rest.pulls.get = async () => ({data: {...f.pr, mergeable: reads++ ? true : null}});
  await f.execute();
  assert.equal(reads, 2);
  assert.deepEqual(f.calls.map(c => c[0]), ['approve', 'merge', 'dispatch']);
});

test('report unresolved mergeability after bounded retries', async () => {
  const f = fixture(); f.pr.mergeable = null;
  await assert.rejects(f.execute(), /has not calculated mergeability/);
  assert.deepEqual(f.calls, []);
});

test('recheck the commit after mergeability retry', async () => {
  const f = fixture(); let reads = 0;
  f.rest.pulls.get = async () => ({data: reads++ ? {...f.pr, head: {...f.pr.head, sha: 'new-untested'}} : {...f.pr, mergeable: null}});
  await f.execute();
  assert.deepEqual(f.calls, []);
});
