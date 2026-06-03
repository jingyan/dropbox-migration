#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_DIR="$ROOT_DIR/deploy/terraform"

AWS_REGION="${AWS_REGION:-us-east-1}"
IMAGE_TAG="${IMAGE_TAG:-latest}"

ECR_URL="$(terraform -chdir="$TERRAFORM_DIR" output -raw ecr_repository_url)"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -t dropbox-to-gdrive "$ROOT_DIR"
docker tag "dropbox-to-gdrive:latest" "$ECR_URL:$IMAGE_TAG"
docker push "$ECR_URL:$IMAGE_TAG"

echo "Pushed $ECR_URL:$IMAGE_TAG"
