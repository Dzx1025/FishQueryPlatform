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

### 3. Create a superuser

Go inside the Django container:

```bash
docker compose exec django bash
```

Run `python manage.py createsuperuser` to create a superuser.

## Nginx configuration example

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
