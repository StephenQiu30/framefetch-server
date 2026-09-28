<div align="center">
  <img src="frontend/public/logo.png" alt="FrameFetch open-source media workflow logo" width="88" />
  <h1>FrameFetch</h1>
  <p><strong>Open-source, self-hosted public-media download, screenplay processing and AI analysis workflow</strong></p>
  <p>
    <a href="https://github.com/StephenQiu30/video-server/actions/workflows/ci.yml"><img src="https://github.com/StephenQiu30/video-server/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
    <a href="https://github.com/StephenQiu30/video-server/releases"><img src="https://img.shields.io/github/v/release/StephenQiu30/video-server?color=111111" alt="Latest release" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-111111.svg" alt="MIT License" /></a>
    <img src="https://img.shields.io/badge/Python-3.12-3776AB.svg" alt="Python 3.12" />
    <img src="https://img.shields.io/badge/Next.js-16-000000.svg" alt="Next.js 16" />
    <img src="https://img.shields.io/badge/Docker-Compose-2496ED.svg" alt="Docker Compose" />
  </p>
  <p>
    <a href="#quick-start">Quick start</a> ·
    <a href="#use-cases">Use cases</a> ·
    <a href="#capabilities">Capabilities</a> ·
    <a href="#frequently-asked-questions">FAQ</a> ·
    <a href="#screenshots">Screenshots</a> ·
    <a href="#architecture">Architecture</a> ·
    <a href="README.md">简体中文</a>
  </p>
</div>

![FrameFetch open-source self-hosted video workflow public landing page](docs/images/landing.png)

> The screenshots were captured from a local preview instance with `agent-browser`. Media-bearing views use the repository's visual-regression fixture; none contains real user data, credentials, or third-party hotlinks. See [`docs/images/README.md`](docs/images/README.md) for capture provenance.

## What is FrameFetch?

FrameFetch is an open-source, self-hosted video downloader and media workflow for creators, content researchers and developers. It turns an authorized public-media URL, local video or screenplay into an observable, recoverable job: inspect the source, select a real format, download and verify it in an isolated runner, persist the artifact, and optionally produce a structured AI analysis report.

FrameFetch is not designed to circumvent platform restrictions. Anonymous providers only handle content that can be positively identified as public, free and non-DRM. Membership, private, purchased, region-restricted and protected playback rights are outside the project's scope.

## Use cases

- **Video and short-form breakdowns**: import your own footage or authorized public videos and generate storyboards, scene timelines and keyframe evidence to review pacing and narrative structure.
- **Screenplay and script research**: import Markdown, Fountain, TXT, PDF or DOCX screenplays, then read, analyze or rewrite them in one workspace and export Markdown / DOCX reports.
- **Team media library**: keep format-, duration- and SHA-256-verified media on your own servers, with users, roles, tasks and storage managed in one place.
- **Self-hosted video downloader**: submit authorized public media links from the Web UI, API or the iOS / Android client, download asynchronously and follow progress in real time without any hosted service.
- **Building on top**: use OpenAPI as the single contract to add providers, analysis capabilities or clients on FastAPI, Next.js and Flutter.

## From video parsing to an AI report

1. Inspect an authorized public-media link or import your own local video or screenplay.
2. Confirm the source and format, then track processing; media artifacts and AI analyses have separate task states.
3. Run an available video, scene, shot or screenplay analysis and review its timeline and keyframe evidence against the source.
4. Export a Markdown or DOCX report for content research, creative planning or team review.

The Web instance exposes public Chinese pages — `/guide/` (usage guide), `/self-hosting/` (deployment guide) and `/about/` (scope and boundaries) — plus an English `/llms.txt` summary for generative search engines. See the capability table below and [project documentation](docs/README.md) for implementation and configuration. Available outputs depend on the configured analysis capabilities and AI service.

### Frequently asked questions

**How does FrameFetch relate to yt-dlp and FFmpeg?** They provide media adaptation and processing within the workflow. FrameFetch adds Web/API access, users and jobs, isolated workers, artifact storage, document processing and optional AI analysis. Extractor support does not guarantee that every platform works in a particular deployment.

**Does open source mean zero operating cost?** The source code is MIT licensed. Infrastructure, storage, bandwidth and external AI services may incur costs; free hosting or model credits are not included.

**Does self-hosting keep all data on the device?** Data resides in the infrastructure configured by the operator. When an external AI provider is used, the content needed for analysis is sent to that service. Check content permissions and the provider's data handling terms before enabling it.

**Where are the Web and mobile clients?** This repository maintains the API, Next.js Web and workers. [video-app](https://github.com/StephenQiu30/video-app) is the Flutter iOS/Android client that connects to this server; it does not run offline AI on the phone.

## Capabilities

| Capability | Current implementation |
| --- | --- |
| Public-media inspection | Extract source metadata and actual available formats from an authorized public URL or single-link share text |
| Reliable asynchronous jobs | FastAPI → Transactional Outbox → RabbitMQ → workers → isolated media runner |
| Artifact verification | Re-resolve the source, validate semantic format identity, run FFmpeg/ffprobe checks, and verify size, duration and SHA-256 before storage |
| Persistent artifacts | Store media, imported documents, normalized text and Markdown/DOCX reports in MinIO |
| Live status | WebSocket delta events with version checks, reconnect and resync; PostgreSQL remains the source of truth |
| Screenplay workflow | Import Markdown, Fountain, TXT, PDF and DOCX files for reading, navigation and analysis |
| Optional AI analysis | A host-side Codex Agent or an administrator-configured model provider, with Markdown/DOCX report export |
| Operations | User roles, provider health, download analytics, paginated artifacts and explicit retention cleanup |
| Native mobile client | Separate [FrameFetch Flutter client for iOS and Android](https://github.com/StephenQiu30/video-app) |

The system is built for recoverability and isolation rather than one-shot command execution. PostgreSQL stores job facts, the transactional outbox aligns state with message intent, and long-running download, FFmpeg and AI work never runs inside the HTTP request process.

## Screenshots

![FrameFetch authenticated public-media inspection, real format selection and asynchronous download workspace](docs/images/home.png)

<p align="center"><strong>Authenticated media inspection and real-format workspace</strong></p>

<table>
  <tr>
    <td width="50%"><img src="docs/images/providers.png" alt="FrameFetch provider capabilities and recent verification status" /></td>
    <td width="50%"><img src="docs/images/login.png" alt="FrameFetch account sign-in and secure session entry" /></td>
  </tr>
  <tr>
    <td align="center"><strong>Provider capabilities and verification</strong></td>
    <td align="center"><strong>Account and secure session</strong></td>
  </tr>
</table>

The web application includes media inspection and download, job history and details, screenplay reading and analysis, provider status, account settings, and administrator views for users, files, analytics and AI providers. The deployment's `/providers` page reports registered routes and recent verification evidence; the result for a specific public link is established by its actual inspection and file download.

## Quick start

The standard business topology includes the pinned media engine and an automatic guest maintainer for public Douyin content. On first start, the maintainer starts preparing its guest context in the background; a user can paste an authorized public link or share text without exporting browser cookies. Check the deployment state with `docker compose exec -T provider-guest python -m app.workers.runner.provider_guest_manager status`. Only `published_lease_usable=true` confirms that a guest lease has been published; container health alone does not prove a media download. Other public links may use an anonymous provider or the bounded Generic single-video route. Extractor candidates are not verified downloads. Account-restricted or otherwise protected content still depends on the platform's access rules; ordinary users do not install an extension or supply cookies.

### Requirements

- Docker Engine and Docker Compose
- `uv` for the deployment-host startup and first-admin commands
- Existing PostgreSQL, RabbitMQ, Redis and MinIO services; reuse their addresses and credentials
- Strong random secrets and a public origin are required before an internet-facing deployment

```bash
git clone https://github.com/StephenQiu30/video-server.git
cd video-server
test -f .env || cp .env.example .env

# Configure .env to reuse existing PostgreSQL, RabbitMQ, Redis and MinIO

# Initialize an empty project database with the current schema before starting
# services. These local connection parameters are examples from .env.example;
# use the actual DDL account for your database and back up an existing one first.
# -W reads the password interactively.
psql -X -v ON_ERROR_STOP=1 -W -h 127.0.0.1 -U video -d video \
  -f backend/sql/schema.sql

# Start Web, API, workers, runners, site session services and the egress proxy
docker compose --env-file .env -f docker-compose.yml up -d --build --wait
```

For an empty user table, create the first administrator on the deployment host. The command prompts for a password, writes its Argon2 hash, and refuses to run once any user exists; it does not expose a remote bootstrap endpoint:

```bash
uv run --project backend python -m app.workers.bootstrap_admin \
  --env-file .env --username your-admin --email you@example.com
```

Sites that need a login (YouTube, Douyin accounts, Reddit, WeChat Channels, Youku, Tencent Video or any other site) use one mechanism: import the logged-in state from your local Chrome **once**, and the container session browser keeps it alive afterwards. A site with an imported session never falls back to anonymous access. From `backend/` in a local terminal (macOS asks for Keychain access once):

```bash
uv run python -m app.workers.session.seed import --site youtube.com
uv run python -m app.workers.session.seed status
```

See the [site session runbook](docs/operations/011-站点会话运行手册.md).

Log in to the Web app with that account, then paste a public link. The default registration flow needs SMTP for email verification, so set up SMTP before inviting users to self-register. Do not reuse the example development secrets in a public deployment.

PowerShell:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Initialize an empty project database with your DDL account first.
psql -X -v ON_ERROR_STOP=1 -W -h 127.0.0.1 -U video -d video -f backend/sql/schema.sql
docker compose --env-file .env -f docker-compose.yml up -d --build --wait
uv run --project backend python -m app.workers.bootstrap_admin --env-file .env --username your-admin --email you@example.com
```

Open the services after startup:

- Web application: <http://localhost:8101>
- Swagger UI: <http://localhost:8111/docs>
- OpenAPI contract: <http://localhost:8111/openapi.json>

```bash
curl --fail http://127.0.0.1:8111/health/live
curl --fail http://127.0.0.1:8111/health/ready
curl --fail --head http://127.0.0.1:8101/
```

Set `ANALYSIS_ENABLED=false` in `.env` when you only need downloads and screenplay imports. See the [root Compose operations guide](docs/operations/001-root-compose运行手册.md) for startup, shutdown, external infrastructure and recovery procedures.
Re-run the same provider startup command after updating code: `docker compose restart` does not apply a new image, configuration or source plan. An existing database requires a backup and the documented schema upgrade sequence before a behavior-version upgrade. A fresh host still requires provisioned infrastructure and a real end-to-end media check; the CI infrastructure fixture is not a production installer.

### Optional AI worker

The AI worker runs on the host and is intentionally not part of the business Compose topology. The default route can reuse a signed-in Codex App Server; administrators may also configure supported model providers in the web application.

```bash
cd backend
uv sync --frozen --dev
uv run python -m app.workers.analysis.agent_cli doctor
uv run python -m app.workers.analysis.agent_cli install
uv run python -m app.workers.analysis.agent_cli status
```

Do not copy or mount Codex/Claude OAuth directories into containers. Before enabling an external model, run a canary with authorized material and review the provider's terms and your organization's data policy.

## Architecture

```mermaid
flowchart LR
  Client[Web / Mobile Client] --> Frontend[Next.js :8101]
  Frontend --> API[FastAPI :8111]
  API --> DB[(PostgreSQL)]
  DB --> Outbox[Transactional Outbox]
  Outbox --> MQ[RabbitMQ]
  MQ --> Download[Download Worker]
  MQ --> Documents[Import / Report Workers]
  Download --> Runner[Isolated Media Runner]
  Runner --> Proxy[Controlled Egress Proxy]
  Download --> Storage[(MinIO)]
  Documents --> Storage
  HostAI[Host AI Agent] --> MQ
  HostAI --> Storage
  API -. WebSocket events .-> Client
```

| Layer | Technologies |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, Radix UI |
| Backend | Python 3.12, FastAPI, SQLAlchemy, PostgreSQL |
| Async | Transactional Outbox, RabbitMQ, Redis, idempotent workers with leases and heartbeats |
| Media | FFmpeg, ffprobe, yt-dlp adapters, isolated runners and Squid egress proxy |
| Storage | MinIO object storage with short-lived presigned access URLs |
| Contract | OpenAPI is the single contract shared by the web, Flutter and server code |

See the [documentation index](docs/README.md) for maintained product, design, research, acceptance and operations facts.

## Security and content boundaries

- Process only content you are legally authorized to download or analyze.
- Anonymous providers accept only public, free and non-DRM HTTP(S) content. Private-network URLs, arbitrary yt-dlp arguments and shell input are always rejected.
- Normal API requests never accept raw cookies. Provider credentials are limited to the corresponding read-only, isolated runner and must not enter the browser, ordinary logs or unrelated workers.
- An edge agent may transfer only a clear file the user has legally obtained and explicitly selected. It must not inspect platform sessions, intercept traffic, extract content keys or transform protected media.
- External media access must pass through an egress proxy that blocks private networks; input validation is not a substitute for network isolation.

Do not disclose exploit details, secrets or user content in a public issue. Follow the [Security Policy](SECURITY.md) to report vulnerabilities privately.

## Current limitations

- FrameFetch is evolving open-source software. It currently provides self-hosted source and Compose workflows, not an official SaaS, public demo or availability SLA.
- Provider behavior can change with source pages and platforms. A platform name does not imply support for every item, region or account entitlement.
- AI analysis needs a separate host agent or a deployment-configured model service. Disabling AI does not disable downloads or document imports.
- Presigned URLs expire, but stored artifacts are not automatically deleted for that reason. Operators must plan MinIO capacity, backups and explicit retention cleanup.
- Replace every placeholder credential in your deployment environment and complete network, storage, runner and provider-canary acceptance before exposing a deployment to the internet.

## Development

The frontend requires Node.js `>=24.15 <25` and npm 11. The backend requires Python `>=3.12 <3.13` and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
uv sync --frozen --dev
uv run --frozen ruff check app tests
uv run --frozen mypy --strict app
uv run --frozen pytest -q

cd ../frontend
npm ci
npm run lint
npm test
npm run build
```

## Contributing

Contributions to provider adapters, reliability, web and mobile UX, AI reports, tests and documentation are welcome. Before opening a pull request, read the [Contributing Guide](CONTRIBUTING.md), [Code of Conduct](CODE_OF_CONDUCT.md), [repository rules](AGENTS.md), [documentation index](docs/README.md), and [Security Policy](SECURITY.md).

Keep implementation, OpenAPI contracts, tests, operations documentation and acceptance evidence aligned. Prefer small, independently verifiable changes.

## Citation

To cite FrameFetch in papers, reports or course material, use “Cite this repository” in the GitHub sidebar or the root [`CITATION.cff`](CITATION.cff). See [Releases](https://github.com/StephenQiu30/video-server/releases) for version history.

## License

FrameFetch is available under the [MIT License](LICENSE). The software license does not grant rights to download, copy or analyze third-party media.

For public-site indexing and generative-search visibility, see the [SEO/GEO operations guide](docs/operations/010-SEO与GEO运行手册.md) (Chinese). Private self-hosted instances default to noindex; intentionally public sites must opt in with `SITE_INDEXABLE=true` and a stable `SITE_URL` at build and runtime.
