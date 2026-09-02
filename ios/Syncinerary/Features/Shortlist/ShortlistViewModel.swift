import Foundation
import Observation

@MainActor
@Observable
final class ShortlistViewModel {
    let session: TripSession

    var candidates: [CandidateCard] = []
    var selectedIDs: Set<UUID> = []
    var mustGoIDs: Set<UUID> = []
    var confirmation: ShortlistStateResponse?
    var isLoading = false
    var isSubmitting = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient
    private var hasLoaded = false

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var selectedCandidates: [CandidateCard] {
        candidates.filter { selectedIDs.contains($0.id) }
    }

    var wishlistCandidates: [CandidateCard] {
        candidates.filter { !selectedIDs.contains($0.id) }
    }

    var confirmationText: String {
        guard let confirmation else { return "" }
        return "\(confirmation.confirmedBy.count) of \(confirmation.confirmationsRequired) confirmations"
    }

    func load() async {
        guard !hasLoaded else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            async let state = loadState()
            async let deck = apiClient.candidates(
                tripID: session.trip.id,
                travelerID: session.travelerID
            )
            let (loadedState, loadedCandidates) = try await (state, deck)
            candidates = loadedCandidates
            apply(loadedState)
            hasLoaded = true
        } catch {
            show(error)
        }
    }

    func toggleSelection(_ candidate: CandidateCard) {
        if selectedIDs.remove(candidate.id) != nil {
            mustGoIDs.remove(candidate.id)
        } else {
            selectedIDs.insert(candidate.id)
        }
    }

    func toggleMustGo(_ candidate: CandidateCard) {
        guard selectedIDs.contains(candidate.id) else { return }
        if mustGoIDs.remove(candidate.id) != nil {
            return
        }
        guard mustGoIDs.count < session.trip.days else {
            errorMessage = "You can mark up to \(session.trip.days) must-go places for this trip."
            isShowingError = true
            return
        }
        mustGoIDs.insert(candidate.id)
    }

    func saveAndConfirm() async -> Bool {
        guard !isSubmitting else { return false }
        isSubmitting = true
        defer { isSubmitting = false }
        do {
            _ = try await apiClient.editShortlist(
                tripID: session.trip.id,
                request: ShortlistEditRequest(
                    travelerID: session.travelerID,
                    selectedCandidateIDs: candidates.compactMap {
                        selectedIDs.contains($0.id) ? $0.id : nil
                    },
                    mustGoCandidateIDs: candidates.compactMap {
                        mustGoIDs.contains($0.id) ? $0.id : nil
                    }
                )
            )
            let state = try await apiClient.confirmShortlist(
                tripID: session.trip.id,
                request: ShortlistConfirmRequest(travelerID: session.travelerID)
            )
            apply(state)
            return state.isConfirmed
        } catch {
            show(error)
            return false
        }
    }

    func refreshConfirmation() async -> Bool {
        do {
            let state = try await apiClient.shortlist(tripID: session.trip.id)
            apply(state)
            return state.isConfirmed
        } catch {
            show(error)
            return false
        }
    }

    /// Building is only allowed once, when voting ends. A trip reopened at
    /// this step already has its shortlist, so read it back instead.
    private func loadState() async throws -> ShortlistStateResponse {
        do {
            return try await apiClient.buildShortlist(tripID: session.trip.id)
        } catch {
            return try await apiClient.shortlist(tripID: session.trip.id)
        }
    }

    private func apply(_ state: ShortlistStateResponse) {
        confirmation = state
        selectedIDs = Set(state.selectedCandidateIDs)
        mustGoIDs = Set(state.mustGoCandidateIDs)
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
