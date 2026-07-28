.PHONY: help up down build logs shell migrate test lint clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start all services
	docker compose -f infrastructure/docker-compose.yml up -d

down: ## Stop all services
	docker compose -f infrastructure/docker-compose.yml down

build: ## Build containers
	docker compose -f infrastructure/docker-compose.yml build

logs: ## Tail logs
	docker compose -f infrastructure/docker-compose.yml logs -f

shell: ## Enter backend container
	docker compose -f infrastructure/docker-compose.yml exec backend bash

migrate: ## Run alembic migrations
	docker compose -f infrastructure/docker-compose.yml exec backend alembic upgrade head

test: ## Run tests
	docker compose -f infrastructure/docker-compose.yml exec backend pytest -v

lint: ## Lint code
	docker compose -f infrastructure/docker-compose.yml exec backend ruff check app/

clean: ## Clean up containers and volumes
	docker compose -f infrastructure/docker-compose.yml down -v
	rm -rf frontend/.next frontend/node_modules
