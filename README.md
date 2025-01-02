# Fish Query Project Platform

## How to set up services manually at a new host

### 1. Clone this repo

```bash
git clone https://github.com/Dzx1025/FishQueryPlatform.git
```

### 2. Environment variables

Create a file `.env` in the root directory of this project. Set values of the following variables:

```dotenv
POSTGRES_DB=db_name
POSTGRES_USER=your_name
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=postgis
NEO4J_USER=your_name
NEO4J_PASSWORD=your_password
HASURA_ADMIN_SECRET=hasura-secret
HASURA_JWT_SECRET={"type":"HS256","key":"your_passphrase"}
DJANGO_SECRET_KEY=your_passphrase
```

### 3. Launch services

```bash
docker compose --env-file ${ENV_FILE_PATH} up -d
```

### 4. Set up services

Go inside the Django container:

```bash
docker compose exec django bash
```

Run `python manage.py migrate`, then `python manage.py createsuperuser`

Moreover, `python manage.py collectstatic`

Go inside the Hasura container:

```bash
docker compose exec hasura bash
```

Run `hasura-cli metadata apply`
