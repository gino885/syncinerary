import CryptoKit
import Foundation
import Security

/// Installed-app OAuth with PKCE. Provider tokens are never persisted on device.
struct GoogleOAuthFlow {
    let challenge: SocialAuthChallenge
    let state: String
    let verifier: String

    init(challenge: SocialAuthChallenge) throws {
        self.challenge = challenge
        state = try Self.randomToken()
        verifier = try Self.randomToken()
    }

    var callbackScheme: String { challenge.clientID.split(separator: ".").reversed().joined(separator: ".") }
    var redirectURI: String { "\(callbackScheme):/oauth2redirect" }

    var authorizationURL: URL {
        var url = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
        url.queryItems = [
            URLQueryItem(name: "client_id", value: challenge.clientID),
            URLQueryItem(name: "redirect_uri", value: redirectURI),
            URLQueryItem(name: "response_type", value: "code"),
            URLQueryItem(name: "scope", value: "openid email profile"),
            URLQueryItem(name: "state", value: state),
            URLQueryItem(name: "nonce", value: challenge.nonce),
            URLQueryItem(name: "code_challenge", value: Self.base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))),
            URLQueryItem(name: "code_challenge_method", value: "S256"),
            URLQueryItem(name: "prompt", value: "select_account"),
        ]
        return url.url!
    }

    func authorizationCode(from callback: URL) throws -> String {
        let items = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
        guard callback.scheme == callbackScheme, callback.path == "/oauth2redirect",
              items.filter({ $0.name == "state" }).count == 1,
              items.first(where: { $0.name == "state" })?.value == state else {
            throw APIError.badStatus(401, "Sign-in could not be verified. Try again.")
        }
        if items.first(where: { $0.name == "error" })?.value == "access_denied" {
            throw CancellationError()
        }
        guard items.filter({ $0.name == "code" }).count == 1,
              let code = items.first(where: { $0.name == "code" })?.value, !code.isEmpty else {
            throw APIError.invalidResponse
        }
        return code
    }

    func identity(from callback: URL, session: URLSession = .shared) async throws -> SocialSignInRequest {
        let code = try authorizationCode(from: callback)
        var request = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        var form = URLComponents()
        form.queryItems = [
            URLQueryItem(name: "code", value: code),
            URLQueryItem(name: "client_id", value: challenge.clientID),
            URLQueryItem(name: "redirect_uri", value: redirectURI),
            URLQueryItem(name: "grant_type", value: "authorization_code"),
            URLQueryItem(name: "code_verifier", value: verifier),
        ]
        request.httpBody = Data((form.percentEncodedQuery ?? "").replacingOccurrences(of: "+", with: "%2B").utf8)
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw APIError.badStatus(400, "Google sign-in did not finish. Try again.")
        }
        let result = try JSONDecoder().decode(GoogleTokenResponse.self, from: data)
        return SocialSignInRequest(idToken: result.idToken, nonce: challenge.nonce)
    }

    private static func randomToken() throws -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw APIError.invalidResponse
        }
        return base64URL(Data(bytes))
    }

    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}
