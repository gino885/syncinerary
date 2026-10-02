#!/bin/sh

set -eu

if [ "${CONFIGURATION:-}" != "Release" ]; then
    exit 0
fi

case "${SYNC_API_BASE_URL:-}" in
    https://*) ;;
    *)
        echo "error: Release SYNC_API_BASE_URL must be a stable HTTPS origin."
        exit 1
        ;;
esac

case "${PRODUCT_BUNDLE_IDENTIFIER:-}" in
    com.local.*|"")
        echo "error: Replace the local bundle identifier before archiving."
        exit 1
        ;;
esac

case "${SYNC_PRIVACY_POLICY_URL:-}" in
    https://*) ;;
    *)
        echo "error: Release privacy policy URL must use HTTPS."
        exit 1
        ;;
esac

case "${SYNC_SUPPORT_URL:-}" in
    https://*) ;;
    *)
        echo "error: Release support URL must use HTTPS."
        exit 1
        ;;
esac
