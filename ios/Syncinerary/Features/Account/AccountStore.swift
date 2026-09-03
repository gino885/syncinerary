import Foundation
import Observation

/// Who is signed in, and the trips they are on.
///
/// Owns the session because two unrelated screens need it: the trips board
/// and every authenticated call underneath it.
@MainActor
@Observable
final class AccountStore {
    private(set) var account: Account?
    private(set) var trips: [TripListRow] = []
    private(set) var isWorking = false
    private(set) var errorMessage: String?

    private let client: APIClient

    init(client: APIClient = .shared) {
        self.client = client
    }

    var isSignedIn: Bool { account != nil }

    /// Restores a session from the Keychain, so a relaunch does not sign the
    /// person out. A rejected token is cleared rather than retried.
    func restore() async {
        guard await client.isSignedIn else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            account = try await client.currentAccount()
            await loadTrips()
        } catch {
            await client.signOut()
            account = nil
        }
    }

    func signIn(displayName: String, handle: String) async {
        isWorking = true
        errorMessage = nil
        defer { isWorking = false }
        do {
            let response = try await client.signIn(
                displayName: displayName,
                handle: handle
            )
            account = response.account
            await loadTrips()
        } catch {
            errorMessage = Self.message(for: error)
        }
    }

    func signOut() async {
        await client.signOut()
        account = nil
        trips = []
    }

    func loadTrips() async {
        do {
            trips = try await client.myTrips()
            errorMessage = nil
        } catch {
            errorMessage = Self.message(for: error)
        }
    }

    private static func message(for error: Error) -> String {
        if case let APIError.badStatus(_, detail) = error, let detail {
            return detail
        }
        return "Could not reach the trip server. Check the connection and try again."
    }
}
