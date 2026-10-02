import Foundation
import Observation

@MainActor @Observable
final class AccountStore {
    private(set) var account: Account?
    private(set) var trips: [TripListRow] = []
    private(set) var isWorking = false
    private(set) var needsSessionRetry = false
    private(set) var errorMessage: String?
    private let client: APIClient
    private var generation = UUID()

    init(client: APIClient = .shared) { self.client = client }
    var isSignedIn: Bool { account != nil }

    func restore() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        guard await client.isSignedIn else { return }
        let started = generation
        errorMessage = nil
        do {
            let restored = try await client.currentAccount()
            guard generation == started else { return }
            account = restored
            needsSessionRetry = false
            await loadTrips()
        } catch {
            guard generation == started else { return }
            if case APIError.badStatus(401, _) = error {
                await expireSession()
            } else {
                needsSessionRetry = account == nil
                errorMessage = Self.message(for: error)
            }
        }
    }

    @discardableResult
    func signIn(email: String, password: String) async -> Bool {
        await authenticate { try await self.client.signIn(email: email, password: password) }
    }

    @discardableResult
    func register(email: String, displayName: String, password: String) async -> Bool {
        await authenticate {
            try await self.client.register(email: email, displayName: displayName, password: password)
        }
    }

    @discardableResult
    func socialSignIn(provider: String, identity: SocialSignInRequest) async -> Bool {
        await authenticate { try await self.client.socialSignIn(provider: provider, identity: identity) }
    }

    private func authenticate(_ action: () async throws -> SignInResponse) async -> Bool {
        guard !isWorking else { return false }
        isWorking = true
        errorMessage = nil
        let started = generation
        defer { if generation == started { isWorking = false } }
        do {
            let response = try await action()
            guard generation == started else { return false }
            account = response.account
            needsSessionRetry = false
            await loadTrips()
            return isSignedIn
        } catch {
            guard generation == started else { return false }
            errorMessage = Self.message(for: error)
            return false
        }
    }

    func signOut() async {
        guard !isWorking else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            try await client.signOut()
            generation = UUID()
            account = nil
            trips = []
            needsSessionRetry = false
            errorMessage = nil
        } catch { errorMessage = Self.message(for: error) }
    }

    @discardableResult
    func deleteAccount(currentPassword: String? = nil, socialIdentity: SocialSignInRequest? = nil) async -> Bool {
        guard !isWorking else { return false }
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            try await client.deleteAccount(currentPassword: currentPassword, socialIdentity: socialIdentity)
            generation = UUID()
            account = nil
            trips = []
            needsSessionRetry = false
            return true
        } catch {
            errorMessage = Self.message(for: error)
            return false
        }
    }

    func loadTrips() async {
        guard let accountID = account?.id else { return }
        let started = generation
        do {
            let loaded = try await client.myTrips()
            guard generation == started, account?.id == accountID else { return }
            trips = loaded
            errorMessage = nil
        } catch {
            guard generation == started, account?.id == accountID else { return }
            if case APIError.badStatus(401, _) = error { await expireSession() }
            else { errorMessage = Self.message(for: error) }
        }
    }

    private func expireSession() async {
        generation = UUID()
        await client.clearSession()
        account = nil
        trips = []
        needsSessionRetry = false
        isWorking = false
        errorMessage = String(localized: "Your session expired. Sign in again.")
    }

    static func message(for error: Error) -> String {
        if case APIError.badStatus(429, _) = error {
            return String(localized: "Too many attempts. Wait 15 minutes, then try again.")
        }
        if case APIError.badStatus(401, _) = error {
            return String(localized: "Sign-in could not be verified. Check your details and try again.")
        }
        if case APIError.badStatus(400, _) = error {
            return String(localized: "Code expired or incorrect. Request a new code.")
        }
        if case let APIError.badStatus(_, detail) = error, let detail { return detail }
        return String(localized: "Could not reach the trip server. Check the connection and try again.")
    }
}
