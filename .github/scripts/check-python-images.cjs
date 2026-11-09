const fs = require('node:fs');
const path = require('node:path');

// The copied virtual environment requires matching Python versions in both stages.
function checkPythonImages(dockerfile) {
  const images = [...dockerfile.matchAll(/^FROM\s+python:(\S+)/gmi)].map(match => match[1]);
  if (images.length !== 2) throw new Error('Expected two pinned Python images: builder and runtime');
  const versions = images.map(image => {
    const match = /^(\d+\.\d+\.\d+)-(?:slim-)?trixie@sha256:[0-9a-f]{64}$/.exec(image);
    if (!match) throw new Error(`Python image must use a stable X.Y.Z trixie tag and SHA-256 digest: ${image}`);
    return match[1];
  });
  if (versions[0] !== versions[1]) {
    throw new Error(`Python builder/runtime versions must match: ${versions.join(' != ')}`);
  }
}

if (require.main === module) {
  checkPythonImages(fs.readFileSync(path.join(__dirname, '../../Dockerfile'), 'utf8'));
}
module.exports = checkPythonImages;
