# Adapterly - Arkkitehtuurikuvaus

## Mikä Adapterly on?

MCP (Model Context Protocol) -gateway, joka yhdistää AI-agentit ulkoisiin järjestelmiin. Agentti saa API-avaimen, jolla se kutsuu MCP-endpointtia — Adapterly tarkistaa oikeudet ja välittää kutsun oikeaan järjestelmään.

---

## Ydinkonseptit ja niiden suhteet

```
Account (yritys/organisaatio)
│
├── User* ─── AccountUser (rooli: admin/tavallinen)
│
├── Project* (konteksti agentin operaatioille)
│   ├── ProjectIntegration* ──→ System (mitkä järjestelmät käytössä)
│   └── allowed_categories (rajoittaa työkaluja)
│
├── MCPApiKey* (agentin tunnistautuminen)
│   ├── → AgentProfile (mitä saa tehdä)
│   ├── → Project (mihin sidottu, valinnainen)
│   ├── mode: safe/power
│   └── is_admin (voi vaihtaa projektia headerilla)
│
├── AgentProfile* (uudelleenkäytettävä oikeusprofiili)
│   ├── allowed_categories → ToolCategory*
│   ├── include_tools / exclude_tools
│   └── mode: safe/power
│
├── ToolCategory* (työkalu­luokittelut, esim. "crm.read", "jira.write")
├── ToolCategoryMapping* (fnmatch-pattern → kategoria)
│
├── AgentPolicy* (API-avain → sallitut kategoriat)
├── ProjectPolicy* (projekti → sallitut kategoriat)
└── UserPolicy* (käyttäjä → sallitut kategoriat)
```

## System-hierarkia (ulkoiset järjestelmät)

```
System (esim. "My API", "CRM System")
├── alias: "jira" (käytetään tool-nimissä)
├── Interface* (REST API / GraphQL / XHR)
│   └── Resource* (esim. "projects", "issues")
│       └── Action* (esim. GET /projects, POST /issues)
│           └── is_mcp_enabled → näkyy agenteille
├── AuthenticationStep* (login-flow)
└── AccountSystem (tilin credentials per Account)
    └── project (valinnainen, projektikohtaiset credentialit)
```

**Tool-nimeäminen**: `{alias}_{resource}_{action}` → esim. `jira_issues_create`

Järjestelmät hallitaan tietokannassa ja synkronoidaan gatewaylle. Uusia järjestelmiä voi luoda web-käyttöliittymässä Adapter Generatorilla.

---

## Autentikointi

| Menetelmä | Käyttötarkoitus |
|-----------|----------------|
| Google OAuth (allauth) | Käyttäjän kirjautuminen selaimessa |
| DRF Token (`Authorization: Token xxx`) | API-kutsut, agent-view yhteys |
| MCP API Key (`ak_live_xxx` / `ak_test_xxx`) | Agentin MCP-kutsut |
| Device Authorization | Agent-view kirjautuminen ilman salasanaa |

### Device Authorization -flow
1. Agent-view: `POST /api/auth/device/` → saa `device_code` + `user_code`
2. Käyttäjä avaa `https://adapterly.ai/account/authorize/ABCD1234/`
3. Kirjautuu Google-tilillä → hyväksyy
4. Agent-view pollaa `GET /api/auth/device/<uuid>/status/` → saa DRF tokenin

---

## Oikeustarkistus (MCP-kutsu)

```
Agentti kutsuu toolia (esim. jira_issues_create)
  │
  ├── 1. Tunnista API-avain → Account, User, Project
  ├── 2. Tarkista mode (safe = vain read, power = kaikki)
  ├── 3. Tarkista AgentProfile (jos asetettu)
  ├── 4. Laske efektiiviset kategoriat:
  │      agent_categories ∩ project_categories ∩ user_categories
  ├── 5. Tarkista onko työkalu sallitussa kategoriassa
  └── 6. Salli tai estä + kirjaa MCPAuditLog
```

---

## Deployment-moodit

Ympäristömuuttuja `DEPLOYMENT_MODE` ohjaa toimintaa:

| Moodi | Kuvaus |
|-------|--------|
| `monolith` (oletus) | Django + FastAPI + PostgreSQL yhdellä palvelimella |
| `control_plane` | Django control plane adapterly.ai:ssa, Gateway Sync API |
| `gateway` | Standalone FastAPI gateway, synkkaa speksit control planelta |

### Control Plane + Gateway -arkkitehtuuri

```
┌─────────────────────────────────────┐
│  Control Plane (Django)             │
│  ├── apps/gateways/ (Django app)    │
│  ├── Gateway Sync API               │
│  │   ├── /gateway-sync/v1/register  │
│  │   ├── /gateway-sync/v1/specs     │
│  │   ├── /gateway-sync/v1/keys      │
│  │   ├── /gateway-sync/v1/audit     │
│  │   └── /gateway-sync/v1/health    │
│  └── Gateway admin UI               │
└─────────────────────────────────────┘
           │ (sync)
           v
┌─────────────────────────────────────┐
│  Gateway (FastAPI + SQLite)         │
│  ├── gateway_core/ (jaettu paketti) │
│  │   ├── executor                   │
│  │   ├── crypto                     │
│  │   ├── models                     │
│  │   ├── auth                       │
│  │   └── diagnostics                │
│  ├── MCP Server (JSON-RPC 2.0)     │
│  ├── Setup Wizard (/setup/)        │
│  └── Admin UI                       │
└─────────────────────────────────────┘
```

**gateway_core/** on jaettu paketti, jota käyttävät sekä control plane (Django) että standalone gateway (FastAPI). Se sisältää executor-logiikan, kryptografiafunktiot, datamallit, autentikoinnin ja diagnostiikkatyökalut.

**Credentialit** eivät koskaan poistu gatewayltä — ne syötetään suoraan gatewayn admin/setup UI:ssa.

---

## Django-appit

| App | Tarkoitus |
|-----|-----------|
| `accounts` | Käyttäjät, tilit, kutsut, device auth |
| `systems` | Ulkoiset järjestelmät, adapterit, resurssit, toiminnot |
| `mcp` | MCP-gateway, projektit, API-avaimet, profiilit, kategoriat, logit |
| `gateways` | Gateway-hallinta, Sync API, rekisteröinti |
| `core` | Landing page, base-template, middleware |
| `help` | Dokumentaatio |

## Tärkeimmät URL-polut

### Käyttöliittymä
| URL | Sivu |
|-----|------|
| `/projects/` | Projektilista |
| `/projects/<slug>/` | Projektin yksityiskohdat |
| `/mcp/profiles/` | Agent-profiilit |
| `/mcp/api-keys/` | MCP API -avaimet |
| `/mcp/categories/` | Työkalu­kategoriat |
| `/mcp/logs/` | Audit-logi |
| `/mcp/sessions/` | Aktiiviset sessiot |
| `/systems/` | Järjestelmä­adapterit |
| `/systems/wizard/` | Adapterin luontivelho |
| `/account/api-token/` | DRF token (agent-view:lle) |
| `/account/authorize/<code>/` | Device auth -hyväksyntä |

### REST API
| URL | Toiminto |
|-----|----------|
| `/api/auth/token/` | Username+password → DRF token |
| `/api/auth/device/` | Device auth -aloitus |
| `/api/auth/device/<uuid>/status/` | Device auth -pollaus |
| `/api/accounts/` | Account CRUD |
| `/api/mcp/agent-profiles/` | Profiili CRUD |
| `/api/mcp/api-keys/` | API Key CRUD |
| `/api/mcp/audit-logs/` | Audit-logit |
| `/mcp/v1/` | MCP Streamable HTTP (agentit) |

### Gateway Sync API
| URL | Toiminto |
|-----|----------|
| `/gateway-sync/v1/register` | Gatewayn rekisteröinti |
| `/gateway-sync/v1/specs` | Adapter-speksien synkronointi |
| `/gateway-sync/v1/keys` | API-avainten synkronointi |
| `/gateway-sync/v1/audit` | Audit-logien push |
| `/gateway-sync/v1/health` | Health check -raportointi |

---

## Deployment

- **Tuotanto**: 37.27.205.12 (adapterly.ai)
- **Repo**: github.com/adapterly-ai/adapterly (public) + adapterly-cloud (private overlay)
- **CI/CD**: GitHub Actions → SSH → `/opt/adapterly-cloud/deploy/deploy.sh`
- **Deploy-skripti**: git pull → pip install → migrate → collectstatic → systemctl restart
- **FastAPI MCP**: erillinen prosessi portissa 8001 (systemd: adapterly-fastapi)
- **Gateway (Docker)**: `docker compose up -d` @ `/opt/adapterly/adapterly-gateway/`
