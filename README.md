# Dropbox to Google Drive Migration

Migrate files from a **Dropbox personal account** to a **Google Drive personal account**, with support for local runs and on-demand **AWS Batch** jobs.

## Features

- Recursive Dropbox folder listing and streaming download
- Google Drive folder mirroring with resumable uploads
- Checkpoint/resume via local file or S3
- Dry-run mode
- Per-file retry with exponential backoff
- AWS Batch on Fargate deployment (Terraform included)
- Credentials via environment variables or AWS Secrets Manager

## Project layout

```
.
├── src/dropbox_to_gdrive/   # Application code
├── deploy/terraform/        # AWS Batch infrastructure
├── deploy/submit_job.py     # Submit on-demand Batch jobs
├── scripts/oauth_setup.py   # Google OAuth refresh token helper
├── Dockerfile
└── pyproject.toml
```

## Prerequisites

1. **Dropbox app** — [Create an app](https://www.dropbox.com/developers/apps) (Scoped access, Full Dropbox or App folder):
   - Enable scopes: `files.metadata.read`, `files.content.read`
   - Note the **App key** and **App secret** from Settings
   - Generate a **refresh token** (recommended for long migrations):

```bash
python scripts/dropbox_oauth_setup.py <app_key> <app_secret>
```

   Short-lived access tokens from the Dropbox console expire in ~4 hours and will fail mid-migration.

2. **Google Cloud project** — Create OAuth **Desktop** credentials and enable the Google Drive API.

3. **Google refresh token** — Run the helper after downloading `client_secret.json`:

```bash
python scripts/oauth_setup.py /path/to/client_secret.json
```

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# Edit .env with your credentials
```

Verify credentials:

```bash
export $(grep -v '^#' .env | xargs)
dropbox-to-gdrive verify
```

Run migration:

```bash
dropbox-to-gdrive migrate
```

Dry run:

```bash
DRY_RUN=true dropbox-to-gdrive migrate
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DROPBOX_APP_KEY` | Dropbox app key | required* |
| `DROPBOX_APP_SECRET` | Dropbox app secret | required* |
| `DROPBOX_REFRESH_TOKEN` | Dropbox OAuth refresh token (recommended) | required* |
| `DROPBOX_ACCESS_TOKEN` | Short-lived token (~4 hours); not for large migrations | optional |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | required* |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | required* |
| `GOOGLE_REFRESH_TOKEN` | Google OAuth refresh token | required* |
| `SECRETS_MANAGER_ARN` | Load all credentials from Secrets Manager | — |
| `DROPBOX_ROOT_PATH` | Dropbox subfolder to migrate (e.g. `/Photos`) | `/` |
| `GDRIVE_ROOT_FOLDER_ID` | Existing Drive folder ID | `root` |
| `GDRIVE_ROOT_FOLDER_NAME` | Folder name when using `root` | `Dropbox Migration` |
| `CHECKPOINT_URI` | `file://...` or `s3://bucket/key` | `file:///tmp/checkpoint.json` |
| `DRY_RUN` | List actions without uploading | `false` |
| `CHUNK_SIZE_MB` | Download chunk size | `8` |
| `LOG_LEVEL` | Logging level | `INFO` |

\*Not required when `SECRETS_MANAGER_ARN` is set.

### Secrets Manager JSON format

```json
{
  "dropbox_app_key": "...",
  "dropbox_app_secret": "...",
  "dropbox_refresh_token": "...",
  "google_client_id": "...",
  "google_client_secret": "...",
  "google_refresh_token": "..."
}
```

## AWS Batch deployment

### 1. Provision infrastructure

```bash
cd deploy/terraform
terraform init
terraform apply
```

This creates:

- ECR repository
- AWS Batch Fargate compute environment + job queue + job definition
- S3 bucket for checkpoints
- Secrets Manager secret (placeholder values)
- CloudWatch log group
- IAM roles

### 2. Store credentials

Update the secret created by Terraform:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(terraform output -raw secrets_manager_arn)" \
  --secret-string file://credentials.json
```

### 3. Build and push container

```bash
ECR_URL=$(terraform -chdir=deploy/terraform output -raw ecr_repository_url)
AWS_REGION=us-east-1
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

aws ecr get-login-password --region "$AWS_REGION" | \
  docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$AWS_REGION.amazonaws.com"

docker build -t dropbox-to-gdrive .
docker tag dropbox-to-gdrive:latest "$ECR_URL:latest"
docker push "$ECR_URL:latest"
```

### 4. Submit an on-demand job

```bash
python deploy/submit_job.py \
  --job-queue "$(terraform -chdir=deploy/terraform output -raw batch_job_queue_name)" \
  --job-definition "$(terraform -chdir=deploy/terraform output -raw batch_job_definition_name)" \
  --command migrate
```

Dry run:

```bash
python deploy/submit_job.py \
  --job-queue dropbox-to-gdrive-queue \
  --job-definition dropbox-to-gdrive \
  --dry-run
```

Verify credentials in Batch:

```bash
python deploy/submit_job.py \
  --job-queue dropbox-to-gdrive-queue \
  --job-definition dropbox-to-gdrive \
  --command verify
```

Monitor logs in CloudWatch: `/aws/batch/dropbox-to-gdrive`.

## Resume behavior

Progress is saved after each file. Re-run the same job to continue from the checkpoint. The default Batch setup stores checkpoints at `s3://<bucket>/checkpoint.json`.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```

## Notes

- Google OAuth scope is `drive.file` (files created by this app). Files appear in the destination folder you specify.
- Large migrations may take hours; Batch Fargate jobs have no hard timeout by default, but tune `job_memory_mb` / `job_vcpu` in Terraform if needed.
- Dropbox API rate limits are handled with retries; very large accounts may need multiple runs using checkpoint resume.
