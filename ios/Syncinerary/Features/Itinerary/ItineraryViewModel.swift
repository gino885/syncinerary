import Foundation
import Observation

@MainActor
@Observable
final class ItineraryViewModel {
    let session: TripSession

    var itinerary: ItineraryResponse?
    var isLoading = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }

        do {
            itinerary = try await apiClient.itinerary(
                tripID: session.trip.id,
                travelerID: session.travelerID
            )
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
        }
    }
}
