# Fish Query Project Platform

## How to set up services

### 1. Clone this repo

```bash
git clone https://github.com/Dzx1025/FishQueryPlatform.git
```

### 2. Edit the `.env` file

| Key                   | Value                                      |
|-----------------------|--------------------------------------------|
| **Postgres Settings** |                                            |
| POSTGRES_DB           | database name                              |
| POSTGRES_USER         | database username                          |
| POSTGRES_PASSWORD     | database password                          |
| POSTGRES_HOST         | your_db_host                               |
| POSTGRES_PORT         | database port                              |
| **Neo4j Settings**    |                                            |
| NEO4J_USER            | neo4j username                             |
| NEO4J_PASSWORD        | neo4j password                             |
| **Hasura Settings**   |                                            |
| HASURA_ADMIN_SECRET   | hasura admin secret                        |
| HASURA_JWT_SECRET     | {"type":"HS256","key":"django_secret_key"} |
| **Qdrant Settings**   |                                            |
| COLLECTION_NAME       | collection name                            |
| **Django Settings**   |                                            |
| DJANGO_SECRET_KEY     | your_django_secret_key                     |
| EMBEDDING_MODEL       | embedding model name                       |
| NOMIC_TOKEN           | embedding model token                      |
| RERANK_MODEL          | rerank model name                          |
| TOP_K                 | top_k                                      |
| RERANK_TOP_K          | rerank_top_k                               |
| OPENAI_API_KEY        | llm api key                                |
| OPENAI_MODEL          | llm model name                             |

### 3. Launch services

```bash
docker compose build
```

```bash
docker compose up -d
```

### 4. Django setup

Go inside the Django container:

```bash
sudo docker exec -it fishqueryplatform-django-1 bash
```

Then `python manage.py migrate` to apply migrations.

#### Admin Page

If you want to use the admin interface, you need to create a superuser.

Run `python manage.py createsuperuser` to create a superuser.
`python manage.py collectstatic --noinput` to collect static files.

Then `exit` to leave the container.

##### Production Admin Page Setup

In your host machine, copy the static files to the host machine by running:
`docker cp fishqueryplatform-django-1:/app/staticfiles/ .`

Also, you need to set the permissions for the static files directory (if it's not working, you need to set permissions
of its parent directory as well):

```bash
sudo chmod -R 755 ${DEPLOY_PATH}/FishQueryPlatform/staticfiles
```

### Nginx configuration example

**django.conf:**

```nginx
server {
    server_name django.fishquery.dzx1025.com;
    client_max_body_size 100M;

    # Static files location for Django admin and other collected static files
    location /static/ {
        alias /<project-path>/staticfiles/;
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

**gql.conf:**

```nginx
server {
    server_name gql.fishquery.dzx1025.com;
    client_max_body_size 100M;

    location / {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-Host $http_host; # necessary for proper absolute redirects and CSRF check
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade; # WebSocket support
        proxy_read_timeout 86400;
    }

}
```

**qdrant.conf:**

```nginx
server {
    server_name qdrant.fishquery.dzx1025.com;
    client_max_body_size 100M;

    location / {
        proxy_pass http://localhost:6334;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Forwarded-Host $http_host; # necessary for proper absolute redirects and CSRF check
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header Upgrade $http_upgrade; # WebSocket support
        proxy_read_timeout 86400;
    }

}
```
