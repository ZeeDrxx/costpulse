# Deploying on an OVHcloud VPS

One small VPS runs the whole stack with Docker Compose: PostgreSQL, Django (gunicorn) and Caddy,
which gets an HTTPS certificate automatically. The smallest VPS tier (2 GB RAM) is enough.

```
Internet ──443──► Caddy ──► web (gunicorn, Django) ──► db (PostgreSQL)
                                                      ▲
Power BI Desktop ──SSH tunnel──► 127.0.0.1:5432 ──────┘   (never exposed publicly)
```

## 1. Order and secure the server

1. In the OVHcloud Control Panel, order a **VPS** with **Ubuntu 24.04**, and add your SSH public key.
2. Point a DNS **A record** (e.g. `costpulse.example.com`) at the VPS IPv4 address.
3. Log in and harden the basics:

```bash
ssh ubuntu@<vps-ip>
sudo apt update && sudo apt upgrade -y
sudo adduser --disabled-password deploy && sudo usermod -aG sudo deploy
sudo mkdir -p /home/deploy/.ssh && sudo cp ~/.ssh/authorized_keys /home/deploy/.ssh/ && sudo chown -R deploy: /home/deploy/.ssh
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

Then set `PasswordAuthentication no` in `/etc/ssh/sshd_config` and `sudo systemctl restart ssh`.

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy   # log out and back in as deploy
```

> Docker publishes ports past UFW. That is why the compose files bind PostgreSQL to `127.0.0.1` only
> and the web container publishes nothing in production: only Caddy's 80/443 face the internet.

## 3. Deploy

```bash
git clone https://github.com/ZeeDrxx/costpulse.git && cd costpulse
cp .env.example .env
nano .env        # DOMAIN, DJANGO_ALLOWED_HOSTS, CSRF origins, and two long random secrets:
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
docker compose logs -f web      # first start: migrations (+ demo data if DEMO_DATA=1)
```

Open `https://<your domain>/`. Create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

## 4. Load real data every month

Put new raw CSVs in the `rawdata` volume and ingest them. A crontab line on the host (`crontab -e`):

```cron
# 06:00 on the 2nd of each month: import whatever arrived, then retrain forecasts
0 6 2 * * cd /home/deploy/costpulse && docker compose exec -T web sh -c "python manage.py ingest data/raw && python manage.py train_forecasts" >> /home/deploy/costpulse-cron.log 2>&1
```

## 5. Power BI access

```bash
docker compose exec -T db psql -U costpulse -d costpulse -v pw="'<another strong password>'" < deploy/powerbi_role.sql
```

On your laptop: `ssh -N -L 5433:127.0.0.1:5432 deploy@<vps-ip>`, then connect Power BI to `localhost:5433`
as `powerbi` (see [`powerbi/README.md`](../powerbi/README.md)).

## 6. Backups and updates

```bash
# nightly database dump, kept 14 days (crontab)
0 3 * * * cd /home/deploy/costpulse && docker compose exec -T db pg_dump -U costpulse -Fc costpulse > /home/deploy/backups/costpulse-$(date +\%F).dump && find /home/deploy/backups -name '*.dump' -mtime +14 -delete

# update to the latest code
git pull && docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

Use OVHcloud's automated VPS backup option as well. A dump on the same disk is not a backup on its own.
