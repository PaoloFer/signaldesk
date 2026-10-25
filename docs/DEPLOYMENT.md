# Deploy di SignalDesk

Questa procedura richiede soltanto un host Linux con Docker Engine e Docker Compose v2. L'applicazione non dipende da percorsi, servizi o configurazioni della macchina di sviluppo.

## Strategia minima consigliata

Per il primo lancio usa **un solo VPS** con 2 vCPU, 2 GB RAM e almeno 30 GB SSD. Tutti i servizi del compose restano sullo stesso host: è la soluzione più economica che conserva i dati, non va in sleep e permette backup e HTTPS reali. Il costo tipico è nell'ordine di 4-8 EUR/mese, oltre al dominio, ma va verificato sul listino del provider scelto.

Evita per questa fase i free tier con filesystem effimero o sospensione automatica: l'applicazione usa job in background, PostgreSQL e Redis e perderebbe affidabilità. Provider equivalenti vanno bene; scegli una regione UE se il pubblico e i dati sono europei.

La prima architettura resta:

```text
Dominio -> VPS singolo -> Caddy -> FastAPI
                                  -> PostgreSQL
                                  -> Redis + worker
```

## Prerequisiti

- Un dominio con record DNS `A`/`AAAA` verso il server.
- Porte `80` e `443` aperte.
- Docker Engine con plugin Compose.
- Almeno 2 GB di RAM per un pilot piccolo.
- Ubuntu 24.04 LTS o altra distribuzione Linux supportata da Docker.
- Accesso SSH con chiave; disabilita l'accesso password quando hai verificato la chiave.

## Preparazione del VPS

Sul server appena creato:

```sh
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
```

Esci e rientra dalla sessione SSH per applicare il gruppo `docker`, quindi verifica:

```sh
docker version
docker compose version
```

Per un VPS da 2 GB è prudente aggiungere 2 GB di swap per assorbire picchi di build, senza considerarlo memoria utile per carico sostenuto:

```sh
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Clona il repository in `/srv/signaldesk` e assegna la directory all'utente di deploy:

```sh
sudo mkdir -p /srv/signaldesk
sudo chown "$USER":"$USER" /srv/signaldesk
git clone URL_DEL_REPOSITORY /srv/signaldesk
cd /srv/signaldesk
```

## Configurazione

Genera un file `.env.production` partendo da `.env.production.example`. Non aggiungerlo al repository.

```sh
cp .env.production.example .env.production
openssl rand -base64 36  # usa il risultato per POSTGRES_PASSWORD
openssl rand -base64 48  # usa il risultato per PSEUDONYM_SALT
chmod 600 .env.production
```

Il comando di deploy valida la configurazione dentro l'immagine applicativa,
quindi sull'host non è richiesta un'installazione Python separata. Se Python
e le dipendenze del progetto sono già disponibili, la validazione può essere
eseguita anche manualmente:

```sh
python scripts/check_deploy_config.py .env.production
```

Valori critici:

- `DEPLOY_DOMAIN`: dominio pubblico senza protocollo.
- `ACME_EMAIL`: contatto per i certificati TLS.
- `POSTGRES_PASSWORD`: password casuale di almeno 20 caratteri.
- `PSEUDONYM_SALT`: segreto casuale di almeno 32 caratteri.
- `PUBLIC_ORIGIN`: deve essere `https://DEPLOY_DOMAIN`.
- `COOKIE_SECURE`: deve essere `true`.

## Primo Deploy

Per creare il primo proprietario imposta temporaneamente `ALLOW_REGISTRATION=true`, quindi esegui:

```sh
sh scripts/deploy.sh .env.production
```

Apri `https://DEPLOY_DOMAIN/login`, crea il primo account e poi imposta `ALLOW_REGISTRATION=false`. Applica la modifica eseguendo nuovamente lo stesso comando.

Caddy ottiene e rinnova automaticamente il certificato TLS. PostgreSQL e Redis non espongono porte pubbliche.

La landing pubblica risponde su `/`; la dashboard autenticata su `/app`. `/robots.txt` e `/sitemap.xml` vengono generati dall'app usando `PUBLIC_ORIGIN`. Dashboard, login e API sono escluse dall'indicizzazione.

### Preview pubblica beta

`/try` espone una preview anonima non persistita. In produzione resta disabilitata finché non imposti:

```dotenv
PUBLIC_PREVIEW_ENABLED=true
PUBLIC_PREVIEW_DAILY_LIMIT=2
PUBLIC_PREVIEW_MAX_CHANNELS=100
```

La preview usa un rate limit per IP adatto al singolo processo API previsto dal setup VPS iniziale. Prima di aumentare repliche o aprire traffico significativo, sposta il contatore su Redis e aggiungi CAPTCHA/email verification. Monitora la quota YouTube: la pagina pubblica non aggira `YOUTUBE_DAILY_QUOTA`.

Per una beta con account self-service, crea prima il proprietario con la preview ancora disabilitata. Solo dopo valuta `ALLOW_REGISTRATION=true`; la preview resta utilizzabile senza account e il limite giornaliero riduce l'abuso, ma la registrazione pubblica richiede monitoraggio e rate limiting Redis prima di una campagna ampia.

## DNS e indicizzazione

1. Crea un record `A` per il dominio verso l'IPv4 del VPS; aggiungi `AAAA` solo se il server ha IPv6 configurato.
2. Attendi la propagazione DNS e completa il primo deploy.
3. Verifica `https://DOMINIO/`, `https://DOMINIO/robots.txt` e `https://DOMINIO/sitemap.xml`.
4. Aggiungi il dominio a Google Search Console e Bing Webmaster Tools.
5. Invia `https://DOMINIO/sitemap.xml` in entrambe le console e richiedi l'indicizzazione della home.
6. Collega il dominio da profili social e siti pertinenti: la sitemap rende la pagina scopribile, ma non sostituisce contenuti utili e link esterni.

La home è l'unica pagina indicizzabile iniziale. Per ottenere traffico organico reale, il passo successivo è pubblicare pagine editoriali server-rendered su casi d'uso, metodologia e report pubblici anonimizzati. Non rendere indicizzabili dashboard o risultati appartenenti agli utenti.

Prima di aprire una beta pubblica aggiungi pagine legali adeguate alla tua attività e giurisdizione: privacy policy, termini, contatti del titolare e informativa sui dati pubblici analizzati. Non inserire testi legali generici senza revisione competente.

## Architettura

```text
Internet → Caddy/TLS → FastAPI
                        ↓
               PostgreSQL + Redis
                        ↑
                     Worker
```

- `migrate`: job one-shot Alembic.
- `app`: API e frontend, senza scheduler o job inline.
- `worker`: acquisizioni e monitoraggio periodico.
- `postgres`: dati applicativi persistenti.
- `redis`: coordinamento dello scheduler e base per code distribuite.
- `caddy`: HTTPS e reverse proxy.

## Aggiornamenti

```sh
git pull
sh scripts/deploy.sh .env.production
```

La migrazione Alembic viene completata prima dell'avvio di API e worker.

## Backup

PostgreSQL (setup Docker di produzione, dump nel container):

```sh
BACKUP_DIR=/srv/signaldesk/backups RETENTION_DAYS=14 \
  sh scripts/backup_postgres.sh .env.production
```

In alternativa, dallo stesso host con il client PostgreSQL installato, oppure per il database SQLite di sviluppo:

```sh
python scripts/backup.py --dir /srv/signaldesk/backups --keep 14
```

`scripts/backup.py` usa la `DATABASE_URL` configurata: copia consistente a caldo per SQLite, `pg_dump` in formato custom per PostgreSQL. `--keep` indica quanti backup conservare (default 14); i più vecchi vengono eliminati a ogni esecuzione.

Pianifica il backup con cron e copia i dump su uno storage esterno cifrato. Verifica periodicamente un ripristino su un database separato (`pg_restore` per i dump custom, apertura diretta del file per SQLite).

Esempio cron giornaliero alle 03:20:

```cron
20 3 * * * cd /srv/signaldesk && BACKUP_DIR=/srv/signaldesk/backups RETENTION_DAYS=14 sh scripts/backup_postgres.sh .env.production >> /var/log/signaldesk-backup.log 2>&1
```

Un backup sullo stesso VPS non protegge dalla perdita del server. Sincronizza almeno una copia giornaliera verso object storage o un altro host e prova il ripristino prima del lancio.

## Rotazione dei segreti

- **`PSEUDONYM_SALT`: non ruotarlo.** Gli identificativi autore pseudonimizzati (`author_hash`) derivano da questo salt: cambiarlo renderebbe gli stessi autori irriconoscibili nei dati storici e invaliderebbe cluster e segnali longitudinali. Se la rotazione fosse davvero necessaria, va trattata come una migrazione dati dedicata con re-pseudonimizzazione di tutto lo storico.
- **`YOUTUBE_API_KEY`**: sostituisci il valore in `.env.production` e riesegui `sh scripts/deploy.sh .env.production`. Nessun dato storico dipende dalla chiave.
- **`POSTGRES_PASSWORD`**: aggiorna la password nel ruolo PostgreSQL (`ALTER ROLE ... WITH PASSWORD`), allinea `POSTGRES_PASSWORD` in `.env.production` e ridistribuisci. Verifica che `DATABASE_URL` (se valorizzata esplicitamente) resti coerente.

All'avvio con `APP_ENV=production` l'applicazione registra un warning per ogni impostazione critica insicura (`COOKIE_SECURE=false`, `ALLOW_REGISTRATION=true`, `PUBLIC_ORIGIN` mancante, `ALLOWED_HOSTS=*`, `PSEUDONYM_SALT` assente): controlla i log del servizio `app` dopo ogni modifica.

## Controlli

```sh
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml logs app worker
curl https://DEPLOY_DOMAIN/api/health
```

Il servizio è pronto soltanto quando `database` e `redis` risultano entrambi `ok`.

Controlla settimanalmente spazio disco, RAM, riavvii e coda dei job:

```sh
df -h
free -h
docker stats --no-stream
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml logs --since=24h app worker
```

## Percorso di crescita

Non distribuire l'architettura in anticipo. Potenzia solo quando misure reali mostrano uno di questi segnali per più giorni: RAM oltre 80%, CPU oltre 70%, risposte API p95 oltre 1 secondo, disco oltre 70%, job che restano in coda o backup che interferiscono con il servizio.

### Fase 0: pilot

- Un VPS da 2 GB, stack Docker attuale, motore semantico `tfidf`.
- Registrazioni chiuse dopo la creazione del proprietario.
- Backup giornaliero esterno e monitor uptime HTTP su `/api/health`.

### Fase 1: prime visite e beta

- Ridimensiona lo stesso VPS a 4 GB prima di introdurre nuovi servizi.
- Usa Cloudflare solo come DNS/proxy e CDN per asset pubblici; non mettere in cache `/api/`, `/app` o `/login`.
- Aggiungi monitoraggio di errori e metriche, limiti applicativi e un processo esplicito di invito utenti.
- Se i job rallentano la UI, aumenta i worker sullo stesso host solo dopo aver verificato CPU e quota YouTube.

### Fase 2: traffico stabile

- Sposta PostgreSQL su un servizio gestito con backup e point-in-time recovery.
- Sposta il worker su una macchina separata; API e worker usano lo stesso `DATABASE_URL` e `REDIS_URL`.
- Pubblica l'immagine Docker in un registry invece di compilarla sul server.
- Introduci staging, deploy automatizzato e osservabilità centralizzata.

### Fase 3: produzione scalata

- Esegui più repliche stateless di `app` dietro un load balancer.
- Usa Redis gestito e una coda distribuita con concorrenza e retry controllati.
- Scala worker e API indipendentemente; conserva migrazioni come job one-shot.
- Aggiungi rate limiting per account/IP, alert su SLO e restore test automatizzati.

Il codice è già predisposto alla separazione: API e worker sono container distinti, sessioni e dati sono in PostgreSQL, mentre Redis coordina i job. Non eseguire più repliche API con SQLite.

## Arresto

```sh
docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml down
```

Non aggiungere `--volumes` in produzione: eliminerebbe i volumi persistenti.
