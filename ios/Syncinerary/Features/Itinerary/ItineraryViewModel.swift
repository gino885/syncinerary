import Foundation
import Observation

@MainActor
@Observable
final class ItineraryViewModel {
    let tripID: UUID

    var itinerary: ItineraryResponse?
    var isLoading = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient

    init(tripID: UUID, apiClient: APIClient = .shared) {
        self.tripID = tripID
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }

        do {
            itinerary = try await apiClient.itinerary(tripID: tripID)
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
        }
    }
}
