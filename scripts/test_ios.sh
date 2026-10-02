#!/bin/bash
# Run the Swift contract and view-model checks without launching the app.
set -euo pipefail

cd "$(dirname "$0")/.."
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/syncinerary-swift-tests.XXXXXX")
trap 'rm -rf "$test_dir"' EXIT

sources=(
  ios/Syncinerary/Models/*.swift
  ios/Syncinerary/Network/*.swift
  ios/Syncinerary/Navigation/AppRoute.swift
  ios/Syncinerary/Features/Account/AccountStore.swift
  ios/Syncinerary/Features/Account/SignInMode.swift
  ios/Syncinerary/Features/Account/SignInViewModel.swift
  ios/Syncinerary/Features/Account/AnthropicConsentViewModel.swift
  ios/Syncinerary/Features/Account/AnthropicCredentialViewModel.swift
  ios/Syncinerary/Features/Checklist/ChecklistViewModel.swift
  ios/Syncinerary/Features/Gathering/GatheringViewModel.swift
  ios/Syncinerary/Features/Group/TripChatViewModel.swift
  ios/Syncinerary/Features/Itinerary/ManualItineraryViewModel.swift
  ios/Syncinerary/Features/Lodging/LodgingViewModel.swift
  ios/Syncinerary/Features/TripCreate/TripCreateViewModel.swift
)

for test_file in ios/Tests/*Tests.swift; do
  test_name=$(basename "$test_file" .swift)
  xcrun swiftc -parse-as-library -module-cache-path "$test_dir/modules" \
    "${sources[@]}" "$test_file" -o "$test_dir/$test_name"
  "$test_dir/$test_name"
  printf 'PASS %s\n' "$test_name"
done
