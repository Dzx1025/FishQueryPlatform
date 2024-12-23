# Dojango Project

## How to deploy the services on a new machine

1. Git clone this repo
2. Run `docker compose up`
3. Inside the Django container: Run `python manage.py migrate`, then `python manage.py createsuperuser`
4. Inside the Hasura container: Run `hasura metadata apply`
