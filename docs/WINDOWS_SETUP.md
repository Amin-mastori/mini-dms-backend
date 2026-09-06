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

Python 3.12 is the tested development version. For a Docker-only run, Python is
used locally only to generate `.env`. If you use WSL, enable Docker Desktop's
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
| MinIO module downloads return `403 Forbidden` | Follow the module-download section below; repeating `createsuperuser` cannot fix a failed image build |
| `service "api" is not running`, with an empty `compose ps -a` | No containers are listed for this Compose project/context; resolve the first build/startup error before running commands inside API |
| Private repository not found | Sign in to the correct GitHub account with repository access |
| Port 8000/9001 already in use | Set `API_PORT` / `MINIO_CONSOLE_PORT` in `.env` and restart; adjust browser URLs |
| Invalid database password after editing `.env` | Existing PostgreSQL volumes retain their original credentials; restore the original password or rotate it deliberately |
| Upload stays pending | Check dispatcher, worker and Redis health; inspect job records as administrator |
| OCR language unavailable | Run `docker compose exec worker tesseract --list-langs`; expected `eng` and `fas` |
| Metadata PATCH returns 428/412 | Supply the quoted current revision in `If-Match`; fetch again if stale |
| Python opens Microsoft Store | Install/configure Python and check Windows App Execution Aliases |

See [OPERATIONS.md](OPERATIONS.md) for deeper diagnosis without exposing secrets.

### MinIO module download failures

If `go build` fails while downloading a module, record the first error and its
host. HTTP 403 means the download was denied; the build log alone does not prove
whether the response came from the origin, a redirected download host or a
network intermediary. Go's default `https://proxy.golang.org,direct` setting only
falls back after HTTP 404/410, not 403. See the
[official proxy behavior](https://go.dev/ref/mod#communicating-with-proxies).

This project now defaults to direct downloads from the upstream source
repositories, while retaining checksum verification. To update an existing
clone, run the following in the project directory. Stop if Git reports local
changes/conflicts; do not discard your work to force the update.

```powershell
git status --short
git pull --ff-only origin main
docker compose --progress plain build minio
```

Keep the existing `.env`; an absent `MINIO_GOPROXY` already defaults to `direct`.
If you previously set this variable in `.env` or PowerShell, check that override.
The first direct build may take longer because Go retrieves source repositories.
BuildKit caches successful downloads and compiler work for later attempts. Do
not use `--no-cache`, prune caches or delete data volumes as a network fix.

Only after the build exits successfully, start the complete stack:

```powershell
docker compose up --build -d --wait --wait-timeout 300
docker compose ps -a
```

Only after startup succeeds and `api` is running/healthy, create the administrator:

```powershell
docker compose exec api python manage.py createsuperuser
```

If your network requires an approved Go module proxy, set `MINIO_GOPROXY` in
`.env` to its HTTPS URL before rebuilding. Follow your organization's access
policy. Do not put credentials in this value or disable TLS/checksum verification.
No third-party proxy or automatic fallback on access denials is selected by the
project. Direct mode still requires access to upstream repositories, module
discovery hosts and, when needed, `sum.golang.org`; it cannot resolve every
network restriction. If another host denies access, preserve the first error
and arrange an authorized route before retrying.

Do not regenerate secrets to fix a download error. Compose uses the fixed project
name `mini-dms`, so an existing named volume can be reused even from a new clone
directory; changing passwords in a new `.env` can then break database/storage
authentication. Never share `.env`, proxy credentials or expanded Compose config.
