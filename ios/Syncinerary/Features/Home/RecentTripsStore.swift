import Foundation
import Observation

/// The trips this device has planned, newest first, kept in UserDefaults.
/// There is no sign-in yet, so "your trips" can only mean this phone's.
@MainActor
@Observable
final class RecentTripsStore {
    private(set) var sessions: [TripSession] = []

    private let defaults: UserDefaults
    private let key = "recentTripSessions"
    private let limit = 8

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        sessions = Self.load(from: defaults, key: key)
    }

    func remember(_ session: TripSession) {
        sessions.removeAll { $0.trip.id == session.trip.id }
        sessions.insert(session, at: 0)
        sessions = Array(sessions.prefix(limit))
        save()
    }

    func forget(_ session: TripSession) {
        sessions.removeAll { $0.trip.id == session.trip.id }
        save()
    }

    /// Replace the stored trip with what the server reports now.
    func refresh(_ session: TripSession, with trip: TripSummary) -> TripSession {
        let updated = TripSession(
            trip: trip,
            travelerID: session.travelerID,
            planRequest: session.planRequest
        )
        remember(updated)
        return updated
    }

    private func save() {
        guard let data = try? JSONEncoder().encode(sessions) else { return }
        defaults.set(data, forKey: key)
    }

    private static func load(from defaults: UserDefaults, key: String) -> [TripSession] {
        guard let data = defaults.data(forKey: key),
              let sessions = try? JSONDecoder().decode([TripSession].self, from: data) else {
            return []
        }
        return sessions
    }
}
