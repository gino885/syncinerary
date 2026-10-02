import Foundation

@main @MainActor
struct AccountTests {
    static func main() async throws {
        let challenge = SocialAuthChallenge(nonce: "server-issued-nonce", clientID: "123-test.apps.googleusercontent.com")
        let flow = try GoogleOAuthFlow(challenge: challenge)
        let secondFlow = try GoogleOAuthFlow(challenge: challenge)
        precondition(flow.state != secondFlow.state && flow.verifier != secondFlow.verifier)
        precondition(flow.verifier.count >= 43 && flow.callbackScheme == "com.googleusercontent.apps.123-test")
        let query = URLComponents(url: flow.authorizationURL, resolvingAgainstBaseURL: false)!.queryItems!
        precondition(query.first(where: { $0.name == "code_challenge_method" })?.value == "S256")
        precondition(query.first(where: { $0.name == "nonce" })?.value == challenge.nonce)
        precondition(query.first(where: { $0.name == "prompt" })?.value == "select_account")
        let callback = URL(string: "\(flow.redirectURI)?state=\(flow.state)&code=accepted-code")!
        let code = try flow.authorizationCode(from: callback)
        precondition(code == "accepted-code")
        for bad in ["\(flow.redirectURI)?state=wrong&code=stolen",
                    "\(flow.redirectURI)?state=\(flow.state)&state=duplicate&code=stolen",
                    "attacker:/oauth2redirect?state=\(flow.state)&code=stolen"] {
            do { _ = try flow.authorizationCode(from: URL(string: bad)!); preconditionFailure("Reject invalid OAuth callbacks") }
            catch { }
        }
        let freshForm = SignInViewModel()
        precondition(freshForm.email.isEmpty)
        freshForm.email = "previous@example.com"
        freshForm.displayName = "Previous traveler"
        freshForm.password = "previous password"
        freshForm.switchMode(.register)
        precondition(freshForm.email.isEmpty && freshForm.displayName.isEmpty,
                     "Create account must not carry another person's identity from sign-in")
        precondition(freshForm.password.isEmpty)
        freshForm.email = "new@example.com"
        freshForm.switchMode(.forgot)
        precondition(freshForm.email == "new@example.com", "Recovery keeps the email the user entered")
        for mode in [SignInMode.register, .reset] {
            let passwordForm = SignInViewModel()
            passwordForm.mode = mode
            passwordForm.email = "mei@example.com"
            passwordForm.displayName = "Mei"
            passwordForm.code = "12345678"
            for length in [7, 8, 128, 129] {
                passwordForm.password = String(repeating: "a", count: length)
                passwordForm.confirmPassword = passwordForm.password
                precondition(passwordForm.canSubmit == (8...128).contains(length),
                             "New passwords must accept 8 through 128 characters")
            }
        }
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [AccountProtocol.self]
        let api = APIClient(baseURL: URL(string: "https://test.invalid")!,
                            session: URLSession(configuration: config), persistSession: false)
        let accounts = AccountStore(client: api)
        let signed = await accounts.signIn(email: "mei@example.com", password: "a long test passphrase")
        precondition(signed && accounts.isSignedIn)
        AccountProtocol.mode = .offline
        let coldLaunch = AccountStore(client: api)
        await coldLaunch.restore()
        precondition(coldLaunch.needsSessionRetry && !coldLaunch.isSignedIn)
        let retained = await api.isSignedIn
        precondition(retained, "Network failure must preserve the stored token")
        AccountProtocol.mode = .normal
        await accounts.restore()
        precondition(accounts.isSignedIn)
        AccountProtocol.mode = .expired
        await accounts.loadTrips()
        let expired = await api.isSignedIn
        precondition(!accounts.isSignedIn && !expired, "A rejected session returns to sign-in")
        AccountProtocol.mode = .normal
        let form = SignInViewModel(client: api)
        form.mode = .register
        form.displayName = "Mei"; form.email = "mei@example.com"
        form.password = "short"; form.confirmPassword = "short"
        precondition(!form.canSubmit)
        form.password = "a long test passphrase"; form.confirmPassword = form.password
        precondition(form.canSubmit)
        await form.submit(accounts: accounts)
        precondition(form.mode == .register, "Signup must not ask for a verification code")
        precondition(accounts.isSignedIn && form.password.isEmpty)
        await accounts.signOut()
        precondition(!accounts.isSignedIn && accounts.trips.isEmpty)
        print("Account validation, immediate signup, offline restoration, expiry and logout passed")
    }
}

final class AccountProtocol: URLProtocol, @unchecked Sendable {
    enum Mode { case normal, offline, expired }
    nonisolated(unsafe) static var mode = Mode.normal
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        if Self.mode == .offline {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return
        }
        let account = #"{"id":"00000000-0000-0000-0000-000000000001","display_name":"Mei","handle":"traveler-123"}"#
        let path = request.url!.path
        var status = Self.mode == .expired ? 401 : 200
        let body: String
        if Self.mode == .expired { body = #"{"detail":"Session expired"}"# }
        else if request.httpMethod == "DELETE" { status = 204; body = "" }
        else if path == "/auth/session" || path == "/auth/register" { body = "{\"token\":\"test-session\",\"account\":\(account)}" }
        else if path == "/auth/me" { body = account }
        else if path.hasSuffix("/trips") { body = "[]" }
        else { body = "{}" }
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil, headerFields: nil)!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8)); client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}
