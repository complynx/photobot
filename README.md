## photobot

Simple chatbot for photo frames

The Dockerfile pins Python and uv by version and image digest. `requirements.txt`
pins the runtime Python dependencies; `setup.py` defines their compatibility
ranges. Debian packages use the current security updates for Bookworm rather
than exact package versions that can disappear from its repositories.

Dependabot opens update pull requests for Docker images, Python dependencies,
and GitHub Actions. Updates require manual review and merge. Merging to `main`
publishes the image and triggers the existing server deployment workflow.

To check the built image without production credentials:

```sh
docker build --pull -t photobot:check .
docker run --rm -i --network none photobot:check python - < tests/check_runtime.py
```
