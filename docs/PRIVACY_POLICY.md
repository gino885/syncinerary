# Syncinerary Privacy Policy

Effective September 28, 2026

Syncinerary is a collaborative trip-planning application operated by the
developer identified on its App Store listing. This policy explains what the
service collects, why it is used, when it is shared, and how to delete it.

## Information we collect

- Account information: display name, email address, account identifier,
  password hash, verification state, and active session records.
- Trip information: destinations, dates, preferences, dietary or mobility
  needs, votes, saved links, messages, checklists, hotel selections,
  itinerary edits, and planning decisions.
- Optional uploads: screenshots that a traveler deliberately submits to
  identify a place from a supported social post.
- AI access information: an Anthropic API key supplied by a trip creator. The
  key is encrypted on the server and is never returned after it is saved.
- Operational information: bounded security events, provider failures, token
  usage, and performance metadata needed to operate and protect the service.
  Production traces exclude prompt and response content.

Syncinerary does not collect device location, contacts, advertising
identifiers, or payment-card information. It does not sell personal data,
serve targeted advertising, or track activity across other companies' apps
and websites.

## How information is used

Information is used to authenticate accounts, let invited travelers work on a
shared trip, discover and verify places, create and explain itineraries,
recover from planning failures, prevent abuse, and provide support.

## Anthropic and AI processing

Anthropic is a third-party AI provider. Before any account member's personal
trip data is sent to Anthropic, that member must explicitly allow it in the
app. Data sent for planning may include trip cities, preferences, dietary
needs, saved social links, votes, and trip instructions. Account email,
password, session token, and Anthropic API key are not placed in model
prompts.

Every member controls permission separately and may withdraw it in Account,
AI privacy. Withdrawing permission prevents new AI work for shared trips that
include that member until permission is granted again. The trip creator's
Anthropic account pays for creator-funded model requests.

Anthropic processes submitted data under its own terms and privacy practices.

## Other service providers

The service may send the minimum information needed to these processors:

- Cloud hosting, database, cache, encrypted backup, and transactional email
  providers operate the service and deliver verification or reset codes.
- Google Places and Routes receive place names, destinations, and route
  points to verify locations and calculate travel.
- Brave Search receives destination-focused search queries used to find
  public travel sources.
- Open-Meteo receives destination coordinates to retrieve weather forecasts.
- TikTok's public embed endpoint and permitted public metadata sources may be
  used for a link a traveler submits or a public travel result.

Public Instagram, TikTok, RedNote, and Google Maps links open in the relevant
service or browser. Those services apply their own privacy policies.

## Retention and deletion

Account and trip information remains in active systems while the account is
open or while it is needed for a shared trip. A user can permanently delete
their account from Account, Delete account. Deletion removes the account,
sessions, encrypted Anthropic key, trips created by that person, and that
person's identifiable messages, votes, preferences, saved links, model input
snapshots, and attribution in trips they joined.

Encrypted backups expire within 30 days. Limited security records may be kept
longer only when required to prevent fraud, comply with law, or resolve an
active dispute. Data that no longer identifies a person, such as a public
venue fact retained in a friend's itinerary, may remain.

## Security

Production traffic uses HTTPS. Session tokens are stored in the iOS Keychain
and hashed on the server. Passwords use Argon2id hashing. Anthropic API keys
use authenticated AES-256-GCM encryption with versioned server-side keys.
Access to production databases, backups, and encryption keys is restricted to
the service identities that need it.

## Children

Syncinerary is not directed to children under 13, and the service does not
knowingly collect their personal information. Contact support to report an
account created by a child.

## Changes and contact

Material changes will be reflected by a new effective date and, when
required, a new in-app consent request. For privacy questions or deletion
assistance, use the public support channel:

https://github.com/gino885/syncinerary/issues
