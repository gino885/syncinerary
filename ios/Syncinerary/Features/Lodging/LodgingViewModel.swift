import Foundation
import Observation

@MainActor
@Observable
final class LodgingViewModel {
    let session: TripSession

    var options: [LodgingOption] = []
    var selectedID: UUID?
    var isLoading = false
    var isPlanning = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient
    private var hasLoaded = false

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    func load() async {
        guard !hasLoaded else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            options = try await apiClient.lodgingOptions(tripID: session.trip.id)
            selectedID = options.first?.id
            hasLoaded = true
        } catch {
            show(error)
        }
    }

    func choose(_ option: LodgingOption) {
        selectedID = option.id
    }

    func selectAndPlan() async -> Bool {
        guard let selectedID, !isPlanning else { return false }
        isPlanning = true
        defer { isPlanning = false }
        do {
            _ = try await apiClient.selectLodging(
                tripID: session.trip.id,
                request: LodgingSelectionRequest(
                    travelerID: session.travelerID,
                    candidateID: selectedID
                )
            )
            _ = try await apiClient.plan(
                tripID: session.trip.id,
                request: session.planRequest
            )
            return true
        } catch {
            show(error)
            return false
        }
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
