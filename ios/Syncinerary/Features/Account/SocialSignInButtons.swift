import AuthenticationServices
import SwiftUI

struct SocialSignInButtons: View {
    @Environment(\.webAuthenticationSession) private var browser
    @Environment(\.authorizationController) private var authorization
    @Environment(\.colorScheme) private var colorScheme
    @Binding var isWorking: Bool
    var isDisabled = false
    var onlyProvider: String? = nil
    var onIdentity: (String, SocialSignInRequest) async -> Bool
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 12) {
            if onlyProvider == nil || onlyProvider == "google" {
                Button { signIn("google") } label: {
                    HStack(spacing: 12) {
                        Image("GoogleLogo").resizable().scaledToFit()
                            .frame(width: 20, height: 20).accessibilityHidden(true)
                        Text("Continue with Google")
                    }
                    .font(.body.weight(.medium))
                    .padding(.horizontal, 16).padding(.vertical, 14)
                    .frame(maxWidth: .infinity, minHeight: 52)
                    .foregroundStyle(Color(red: 0.12, green: 0.12, blue: 0.12))
                    .background(.white, in: .rect(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(.gray, lineWidth: 1))
                }.accessibilityIdentifier("auth.google")
            }
            if onlyProvider == nil || onlyProvider == "apple" {
                Button { signIn("apple") } label: {
                    Label("Continue with Apple", systemImage: "apple.logo")
                        .font(.body.weight(.medium))
                        .padding(.horizontal, 16).padding(.vertical, 14)
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .foregroundStyle(colorScheme == .dark ? .black : .white)
                        .background(colorScheme == .dark ? .white : .black, in: .rect(cornerRadius: 8))
                }.accessibilityIdentifier("auth.apple")
            }
            if isWorking { ProgressView().accessibilityLabel("Signing in") }
            if let errorMessage {
                Text(errorMessage).font(.callout).foregroundStyle(AppTheme.stamp)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.updatesFrequently)
            }
        }
        .buttonStyle(.plain)
        .disabled(isDisabled || isWorking)
    }

    private func signIn(_ provider: String) {
        guard !isWorking, !isDisabled else { return }
        isWorking = true
        errorMessage = nil
        Task {
            defer { isWorking = false }
            do {
                let challenge = try await APIClient.shared.socialChallenge(provider: provider)
                let identity: SocialSignInRequest
                if provider == "google" {
                    let flow = try GoogleOAuthFlow(challenge: challenge)
                    let schemes = (Bundle.main.object(forInfoDictionaryKey: "CFBundleURLTypes") as? [[String: Any]])?
                        .flatMap { $0["CFBundleURLSchemes"] as? [String] ?? [] } ?? []
                    guard schemes.contains(flow.callbackScheme) else {
                        throw APIError.badStatus(503, "Google sign-in isn’t available in this build yet. Use email for now.")
                    }
                    let callback: URL
                    if #available(iOS 17.4, *) {
                        callback = try await browser.authenticate(using: flow.authorizationURL,
                            callback: .customScheme(flow.callbackScheme), additionalHeaderFields: [:])
                    } else {
                        callback = try await browser.authenticate(using: flow.authorizationURL,
                            callbackURLScheme: flow.callbackScheme)
                    }
                    identity = try await flow.identity(from: callback)
                } else {
                    guard Bundle.main.object(forInfoDictionaryKey: "SyncAppleSignInEnabled") as? String == "YES",
                          challenge.clientID == Bundle.main.bundleIdentifier else {
                        throw APIError.badStatus(503, "Apple sign-in isn’t available in this build yet. Use email for now.")
                    }
                    let request = ASAuthorizationAppleIDProvider().createRequest()
                    request.requestedScopes = [.fullName, .email]
                    request.nonce = challenge.nonce
                    request.state = challenge.nonce
                    let result = try await authorization.performRequest(request)
                    guard case let .appleID(credential) = result,
                          credential.state == challenge.nonce,
                          let data = credential.identityToken,
                          let token = String(data: data, encoding: .utf8) else {
                        throw APIError.invalidResponse
                    }
                    let name = credential.fullName.map { PersonNameComponentsFormatter().string(from: $0) }
                    identity = SocialSignInRequest(idToken: token, nonce: challenge.nonce,
                        displayName: name, authorizationCode: credential.authorizationCode.flatMap { String(data: $0, encoding: .utf8) })
                }
                _ = await onIdentity(provider, identity)
            } catch is CancellationError {
                // Cancelling the provider sheet leaves the form untouched.
            } catch let error as ASAuthorizationError where error.code == .canceled {
            } catch let error as ASWebAuthenticationSessionError where error.code == .canceledLogin {
            } catch {
                if case let APIError.badStatus(_, detail) = error, let detail { errorMessage = detail }
                else { errorMessage = AccountStore.message(for: error) }
            }
        }
    }
}
