# Windows and VS Code setup

The backend runs in Linux containers. VS Code is an editor, not a required server
component. Docker Desktop must be running before using Compose.

## 1. Check prerequisites

Open **Terminal > New Terminal** in VS Code, using PowerShell:

```powershell
git --version
python --version
docker --version
docker compose version
```

Python 3.12 is the tested application/development version. For a Docker-only run,
Python 3.8+ can run the small local `.env` and image-bundle helpers; the application
still runs on Python 3.12 inside its container. If you use WSL, enable Docker Desktop's
integration for your distribution and keep the repository in the Linux home
directory for better filesystem performance. The WSL command is `python3`.

## 2. Get and open the repository

```powershell
git clone https://github.com/Amin-mastori/mini-dms-backend.git
cd mini-dms-backend
code .
```

Authenticate using your normal GitHub/Git Credential Manager flow if prompted.
Do not put an access token in the repository URL or send credentials to another
person. If the repository is already cloned, open that existing folder instead.

## 3. Generate local configuration

```powershell
python scripts/init_env.py
```

This creates `.env` with fresh secrets and safe development connection settings.
It never overwrites an existing file. You do not need to create the PostgreSQL
database or MinIO bucket manually. Do not upload `.env` to GitHub.

## 4. Build and start

```powershell
docker compose up --build -d --wait --wait-timeout 180
docker compose ps -a
```

The first MinIO source build can take several minutes. Docker needs internet
access for image registries, OS packages, Python wheels and Go modules. Wait for
`migrate` and `storage-init` to exit successfully, and for `api`, `worker` and
`dispatcher` to run. A successful one-shot service exiting is normal.

If the build is terminated for memory pressure, increase Docker's memory
allocation. Do not replace a dependency with an arbitrary image just to make the
build proceed. Record the failing step first.

## 5. Create your administrator

```powershell
docker compose exec api python manage.py createsuperuser
```

Choose a username such as `admin`. Supply your own strong password; there is no
default administrator password. Password characters are not echoed in the
terminal. That is expected.

## 6. Exercise the API

Open [Swagger](http://localhost:8000/api/docs/). Expand `POST
/api/v1/auth/token/`, choose **Try it out**, provide the username/password and
execute. Copy only the returned access token into **Authorize**. Then use the
document-upload operation with a small PNG, JPEG or PDF.

The upload response is asynchronous: `pending` does not mean failure. Retrieve
the returned document's status and text endpoints after a few seconds. Test a
normal account as well as the administrator; administrator access alone cannot
demonstrate user isolation.

The [OpenAPI file](openapi.yaml) can also be imported into Postman. Bash `curl`
examples in the root README are easiest to run in WSL. In PowerShell, `curl` may
refer to a shell alias, so use `curl.exe` for the actual curl program or use
Swagger to avoid quoting differences.

## 7. Run evaluation checks

```powershell
docker compose --profile test run --build --rm test pytest --cov --cov-fail-under=90
docker compose --profile test run --rm test python scripts/smoke_test.py --username admin
```

The smoke test prompts for the administrator password, creates two isolated test
users, exercises real OCR/storage/queue behavior and deletes its documents.
Use an evaluation instance, not a production deployment. Test accounts and audit
events remain so their attribution is not lost.

## 8. Inspect and stop

```powershell
docker compose logs --tail=100 api worker dispatcher
docker compose down
```

Stopping preserves data in named Docker volumes. Do not use `down -v` unless
you deliberately want to erase that evaluation data.

## Common issues

| Symptom | Check |
| --- | --- |
| Docker engine connection error | Start Docker Desktop; confirm Linux containers and WSL integration if applicable |
| A previous MinIO build fails in `apt-get` with exit 100 | Pull the current repository revision; the final MinIO image no longer uses `apt-get`. Rebuild with `docker compose build minio`. |
| MinIO module download returns `403 Forbidden` | Use the private CI-built image below; increasing the startup timeout does not fix a denied download |
| Resolving `docker/dockerfile:1` returns `403 Forbidden` | Pull the current repository revision. The application Dockerfile uses only standard instructions and no longer requests that optional external frontend. Base images still require registry access when absent locally. |
| `service "api" is not running`, with an empty `compose ps -a` | Resolve the first build/startup failure; no containers are listed for the current Compose project/context |
| Private repository not found | Sign in to the correct GitHub account with repository access |
| Port 8000/9001 already in use | Set `API_PORT` / `MINIO_CONSOLE_PORT` in `.env` and restart; adjust browser URLs |
| Invalid database password after editing `.env` | Existing PostgreSQL volumes retain their original credentials; restore the original password or rotate it deliberately |
| Upload stays pending | Check dispatcher, worker and Redis health; inspect job records as administrator |
| OCR language unavailable | Run `docker compose exec worker tesseract --list-langs`; expected `eng` and `fas` |
| Metadata PATCH returns 428/412 | Supply the quoted current revision in `If-Match`; fetch again if stale |
| Python opens Microsoft Store | Install/configure Python and check Windows App Execution Aliases |

See [OPERATIONS.md](OPERATIONS.md) for deeper diagnosis without exposing secrets.

## Use the private MinIO image

Use this alternative when the local MinIO source build cannot download its Go
dependencies. It does not require changing storage providers or supplying a
GitHub token to Docker. The archive targets **Linux/amd64**: use Docker Desktop's
Linux-container mode on x64 Windows. ARM64 and Windows-container images are not
included. Python 3.8+ and Docker are required by the verification/loading helper.

### 1. Update the existing clone

```powershell
git status --short
git pull --ff-only origin main
```

Stop if Git reports a conflict or an update failure. Preserve local changes; do
not reset them. Keep the existing `.env`. Do not generate new passwords or delete
volumes to fix a build error. The fixed Compose project name `mini-dms` can reuse
existing volumes even when you clone into a different directory.

### 2. Download and extract

Open the repository's [CI workflow](https://github.com/Amin-mastori/mini-dms-backend/actions/workflows/ci.yml)
while signed into your own GitHub account. Select a **successful main-branch run**
and find `minio-image-linux-amd64-<full-commit-sha>` under **Artifacts**. Check its
commit against the run; do not use a similarly named archive from another source.

Download the ZIP, rename it to `minio-image.zip` in your Downloads folder, then
run this from the project directory:

```powershell
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\minio-image.zip" -DestinationPath ".\artifacts\minio-image"
```

Use a fresh destination if it already exists; do not overwrite another bundle.
The extracted directory should contain `minio-image.tar.gz` and `manifest.json`.
The `artifacts` directory is excluded from Git and Docker build contexts. Do not
extract the image into the project root, where it could enter application builds.

Artifacts expire after seven days. To generate another, choose **Run workflow**
on `main`, or re-run a suitable CI execution, and wait for success. Downloads
require repository read access; the workflow does not publish to a public
container registry. Availability still depends on GitHub Actions and its access
to build dependencies.

### 3. Verify and load the image

```powershell
python scripts/minio_image.py load --directory .\artifacts\minio-image
```

The helper verifies the file checksum before calling `docker image load`, then
compares the loaded filesystem layers, runtime configuration and platform with
the manifest. The recorded build-time image ID is informational because Docker
image stores can report different IDs for identical imported content. Stop on any error.
Expected final output:

```text
Verified and loaded mini-dms-minio:2025-10-15 (linux/amd64).
```

The checksum is an integrity check, not a signature: trust only this private
repository's tested artifacts. Loading can update the local image tag; it does
not delete volumes or start containers. An image-content mismatch after import is an
error even though Docker has already loaded the archive; do not start the stack.

### 4. Build only the application images

```powershell
docker compose build api storage-init
```

`api`, `worker`, `dispatcher` and `migrate` share the `mini-dms:local` image.
`storage-init` has its own image. This explicit command does **not** build MinIO.
It still needs access to Python/OS dependencies and image registries when they
are not cached. PostgreSQL/Redis images also need to be available locally or
downloadable. The application Dockerfile omits the optional external syntax
frontend because its instructions do not require it; this prevents an extra
`docker/dockerfile:1` registry lookup. This is not an entirely offline installation.

### 5. Start without rebuilding MinIO

Only after both image loading and application builds succeed:

```powershell
docker compose up --no-build -d --wait --wait-timeout 300
docker compose ps -a
```

Do **not** add `--build` to this command; that would build MinIO from source again.
Once startup succeeds and `api` is running/healthy:

```powershell
docker compose exec api python manage.py createsuperuser
```

An empty container list or an API-not-running message is a downstream symptom,
not the original cause. If a step fails, stop and retain its first error rather
than continuing to account creation. Do not share `.env`, credentials or expanded
Compose configuration in logs.
