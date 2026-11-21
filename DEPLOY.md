# Deploying Bookhouse on Synology (Docker)

Bookhouse runs Calibre-Web-style browsing for **multiple Calibre libraries** that are
**strictly read-only**: Bookhouse never writes to `metadata.db` or book files. All
Bookhouse-owned state (users, shelves, reading progress, downloads, hidden books, the
library registry) lives in its own `app.db`, which is the only writable database.

## Principle

| Path in container | Mount | Writable? | Purpose |
|---|---|---|---|
| `/config` | named/local folder | **yes** | `app.db` (Bookhouse state), gdrive.db, logs |
| `/calibre-library` | `:ro` | no | Calibre library 1 (`metadata.db` + books) |
| `/calibre-library-2` | `:ro` | no | Calibre library 2 (optional, repeat for more) |

Enforcement is layered: SQLite `mode=ro` attach, Docker `:ro` mounts, and app-level 403s
on all metadata-mutating endpoints. Read status, shelves and bookmarks are stored per
user *and per library* in `app.db`.

## First run

1. Start the container (compose file below). The `app.db` is created automatically.
2. Log in as `admin` / `admin123` → change the password.
3. You are taken to **Library Management** (setup wizard). Add the first library, e.g.
   path `/calibre-library`. The first library becomes the **default** automatically.
4. Add more libraries (e.g. `/calibre-library-2`) as needed.
5. Edit each user under Admin → Users → **Library Access** checkboxes to grant access.

No `config_calibre_dir` bootstrap exists in this flow — fresh deployments start empty.

## docker-compose.yml (excerpt)

```yaml
services:
  bookhouse:
    build: .
    ports: ["8083:8083"]
    volumes:
      - /volume1/docker/bookhouse-config:/config
      - /volume1/calibre:/calibre-library:ro
      # - /volume1/calibre2:/calibre-library-2:ro
    environment:
      - TZ=Europe/Stockholm
```

On Synology 7.x use Container Manager → *Project* → upload this file; create the
shared folders first (`/docker/bookhouse-config`, `/calibre`).

## Libraries on the NAS

Build/keep your Calibre libraries with the Calibre desktop app on a machine that mounts
the same folder read-write, or with calibredb. Bookhouse treats them as immutable.

## Multi-library URLs

- Web UI: switch via the navbar dropdown (session-based), or share deep links with
  `?lib=<slug>`, e.g. `http://nas:8083/?lib=library-2`.
- OPDS (basic-auth clients, no cookies): point the client at
  `http://nas:8083/opds/?lib=<slug>`; all feed-internal links carry the same tag.
- Without a `lib` tag, clients/URLs land on the **default** library.

## Permissions

- Admins see all libraries.
- Regular users without explicit grants see the default library only.
- Regular users with grants see exactly the granted (enabled) libraries.
- Disabled or deleted libraries fall back cleanly; the last enabled library cannot be
  disabled or deleted (the setup wizard must remain reachable).

## Backups

Back up the `/config` volume (`app.db`) — that holds all Bookhouse state. Calibre
libraries are external source data; back them up separately with your existing process.
`cp` of a live `metadata.db` may catch a mid-transaction snapshot; prefer making the
copy from Calibre itself or use `sqlite3 database "VACUUM INTO 'backup.db'"`.

## Health check

`GET /admin/alive` returns 200 while the server is running.
