# Fish Query Project Platform

## How to set up services

### 1. Clone this repo

```bash
git clone https://github.com/Dzx1025/FishQueryPlatform.git
```

### 2. Launch services

```bash
docker compose --env-file ${ENV_FILE_PATH} up -d
```

### 3. Django setup

Go inside the Django container:

```bash
docker compose exec ai_platform-django-1 bash
```

Run `python manage.py createsuperuser` to create a superuser.
`python manage.py collectstatic --noinput` to collect static files.

Then `exit` to leave the container. In your host machine, copy the static files to the host machine by running:
`docker cp ai_platform-django-1:/app/staticfiles/ /staticfiles/`.

## 4. Hasura setup

Go inside the Django container:

```bash
docker compose exec ai_platform-hasura-1 bash
```

Run `hasura-cli metadata apply`.

## Nginx configuration example

django.conf:

```nginx
server {
    server_name django.fishquery.dzx1025.com;
    client_max_body_size 100M;

    # Static files location for Django admin and other collected static files
    location /static/ {
        alias /yourpath/staticfiles/;
        types {
            text/css css;
            application/javascript js;
            image/svg+xml svg;
        }
    }

    location /api/chat/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # For SSE
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        keepalive_timeout 3600s;
    }
    
    # Main API location
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
