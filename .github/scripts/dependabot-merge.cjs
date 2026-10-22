// Run only after the trusted CI workflow finishes; never execute PR code here.
module.exports = async ({github, context, core, wait = ms => new Promise(resolve => setTimeout(resolve, ms))}) => {
  const {owner, repo} = context.repo;
  const run = context.payload.workflow_run;
  if (run.event !== 'pull_request' || run.conclusion !== 'success') return;
  if (run.head_repository?.full_name !== `${owner}/${repo}`) return;

  const pulls = await github.paginate(github.rest.repos.listPullRequestsAssociatedWithCommit, {
    owner, repo, commit_sha: run.head_sha,
  });
  const eligible = pr => pr.user.login === 'dependabot[bot]' && pr.user.type === 'Bot' &&
    pr.state === 'open' && !pr.draft && pr.base.ref === 'main' &&
    pr.head.repo?.full_name === `${owner}/${repo}` &&
    pr.head.ref.startsWith('dependabot/') && pr.head.sha === run.head_sha;
  for (const candidate of pulls) {
    let {data: pr} = await github.rest.pulls.get({owner, repo, pull_number: candidate.number});
    if (!eligible(pr)) continue;
    for (let retry = 0; pr.mergeable === null && retry < 3; retry++) {
      await wait(1000 * 2 ** retry);
      ({data: pr} = await github.rest.pulls.get({owner, repo, pull_number: candidate.number}));
      if (!eligible(pr)) break;
    }
    if (!eligible(pr)) continue;
    if (pr.mergeable === null) throw new Error(`GitHub has not calculated mergeability for PR #${pr.number}`);

    const checks = await github.paginate(github.rest.checks.listForRef, {
      owner, repo, ref: pr.head.sha, filter: 'latest',
    });
    const {data: status} = await github.rest.repos.getCombinedStatusForRef({owner, repo, ref: pr.head.sha});
    if (!checks.some(c => c.name === 'container' && c.app?.slug === 'github-actions' && c.conclusion === 'success') ||
        checks.some(c => c.status !== 'completed' || !['success', 'neutral', 'skipped'].includes(c.conclusion)) ||
        (status.total_count > 0 && status.state !== 'success') || !pr.mergeable) {
      core.info(`PR #${pr.number} is not ready to merge`);
      continue;
    }
    const reviews = await github.paginate(github.rest.pulls.listReviews, {owner, repo, pull_number: pr.number});
    const latest = new Map();
    for (const review of reviews) {
      if (['APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'].includes(review.state)) {
        latest.set(review.user.login, review.state);
      }
    }
    if ([...latest.values()].includes('CHANGES_REQUESTED')) continue;

    await github.rest.pulls.createReview({
      owner, repo, pull_number: pr.number, commit_id: pr.head.sha, event: 'APPROVE',
    });
    const {data: merge} = await github.rest.pulls.merge({
      owner, repo, pull_number: pr.number, sha: pr.head.sha, merge_method: 'squash',
    });
    if (!merge.merged) throw new Error(`PR #${pr.number} did not merge`);
    // GITHUB_TOKEN merges do not emit push workflow runs. Dispatch publication explicitly.
    await github.rest.actions.createWorkflowDispatch({owner, repo, workflow_id: 'build.yml', ref: 'main'});
    core.info(`Approved and merged Dependabot PR #${pr.number}; publication dispatched`);
  }
};
