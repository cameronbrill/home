#!/bin/bash
set -euo pipefail

echo "=== Home Automation Service Starting ==="

# Check if Infisical token is provided
if [ -z "${INFISICAL_TOKEN:-}" ]; then
    echo "ERROR: INFISICAL_TOKEN environment variable is required"
    echo "Please set INFISICAL_TOKEN to authenticate with Infisical"
    exit 1
fi

# Check if project ID is provided
if [ -z "${INFISICAL_PROJECT_ID:-}" ]; then
    echo "ERROR: INFISICAL_PROJECT_ID environment variable is required"
    exit 1
fi

# Set default environment if not provided
INFISICAL_ENVIRONMENT="${INFISICAL_ENVIRONMENT:-prod}"

echo "Fetching secrets from Infisical..."
echo "  Project ID: ${INFISICAL_PROJECT_ID}"
echo "  Environment: ${INFISICAL_ENVIRONMENT}"
echo ""

# Use 'infisical run' which is the recommended approach for containers
# It injects secrets as environment variables and runs the command
# See: https://infisical.com/docs/documentation/platform/secrets-mgmt/concepts/secrets-delivery
exec infisical run \
    --token="${INFISICAL_TOKEN}" \
    --projectId="${INFISICAL_PROJECT_ID}" \
    --env="${INFISICAL_ENVIRONMENT}" \
    -- python -m core.main

