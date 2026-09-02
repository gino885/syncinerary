import Foundation
import Observation

@MainActor
@Observable
final class GatheringViewModel {
    let session: TripSession

    var isGathering = false
    var errorMessage: String?
    var deckSize: Int?

    private let apiClient: APIClient

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var cityName: String {
        session.trip.cities.first ?? session.trip.destination
    }

    /// One gather per screen; a retry after a failure is allowed.
    func gather() async -> Bool {
        guard !isGathering else { return false }
        isGathering = true
        errorMessage = nil
        defer { isGathering = false }

        do {
            deckSize = try await apiClient.gather(tripID: session.trip.id).deckSize
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}
