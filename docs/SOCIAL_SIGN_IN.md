# Google and Apple account setup

Email/password signup works immediately without SMTP. The two provider buttons
are implemented, but their real sign-in flows require your provider configuration.
Blank credentials return a clear unavailable message. No simulated provider
identity is accepted. Use HTTPS for a physical-device or deployed backend.

## Google

1. In Google Cloud, configure the OAuth consent screen and create an **iOS**
   OAuth client for the app's actual bundle identifier. Add your test users if
   the consent screen is in testing mode.
2. Set `GOOGLE_OAUTH_CLIENT_ID` in the backend's `.env` to that client ID.
3. In both iOS build configurations, set `SYNC_GOOGLE_CALLBACK_SCHEME` to the
   reversed client ID. For `123-abc.apps.googleusercontent.com`, this is
   `com.googleusercontent.apps.123-abc`. Rebuild the app and restart the API.

This implementation uses Apple's system browser session and Google's installed
app OAuth flow with PKCE. The redirect is `REVERSED_CLIENT_ID:/oauth2redirect`.
It requests only `openid email profile`, checks state, and exchanges the code
on the device. The server verifies the signed ID token against the configured
iOS audience and a server-issued, single-use nonce. A web client secret is not
needed for this native flow. It always presents Google's account chooser.

References: [Google native OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[backend token verification](https://developers.google.com/identity/sign-in/ios/backend-auth),
[button assets and branding](https://developers.google.com/identity/branding-guidelines).
The bundled Google logo is the official asset linked from that branding page.

## Apple

Activation remains deferred until your Apple Developer account is ready.

1. Enable Sign in with Apple for the registered App ID and add the **Sign in
   with Apple** capability to the signed Xcode target. Let Xcode generate its
   entitlement and provisioning profile for the real team.
2. Set `SYNC_APPLE_SIGN_IN_ENABLED=YES` in both iOS build configurations.
3. Set `APPLE_OAUTH_CLIENT_ID` on the backend to that exact bundle identifier.
4. Create a Sign in with Apple key and generate Apple's ES256 client-secret
   JWT using the key ID, team ID, and bundle identifier. Store the JWT only in
   `APPLE_OAUTH_CLIENT_SECRET`. Rotate it before its expiration; Apple allows a
   maximum six-month lifetime. Never put the private key or client secret in
   the app or commit them.
5. Restart the backend and build/install the app with the matching team.

The app requests a native Apple credential with a fresh server nonce. The
server verifies its signature, issuer, audience, expiry, and nonce. Name data
is saved at first signup because Apple may not return it on subsequent logins.
Apple Hide My Email works: identity is the stable provider subject, not email.
Account deletion requires a fresh Apple authorization code, exchanges it,
verifies that it belongs to the same identity, revokes the Apple grant, and
then removes app data. Failure to disconnect Apple leaves app data intact for
a retry. The client-secret setting is required before enabling Apple sign-in.

References: [Apple identity verification](https://developer.apple.com/documentation/signinwithapple/verifying-a-user),
[Apple token revocation](https://developer.apple.com/documentation/signinwithapplerestapi/revoke-tokens).

## Account behavior and checks

- Email, Google, and Apple identities stay separate, even when their email
  addresses match. There is no automatic linking or transfer of trip ownership.
  Continue with the same method to return to the same trips.
- Social accounts have no app password. Deletion asks them to authenticate
  with their provider again and type DELETE.
- All methods use the same opaque, revocable app session stored in iOS Keychain.
- Signup passwords stay 8 to 128 characters. Mailbox verification happens only
  if an email/password user requests password recovery.

Automated tests sign local RSA test identities and exercise the real verifier,
database, nonce consumption, and session lifecycle. They do not prove your
Google consent-screen or Apple provisioning configuration. Once configured,
test a new account, returning sign-in, cancellation, a different account,
session restoration, Apple Hide My Email, and account deletion on a device.
