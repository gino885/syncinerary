import Foundation
import Observation

@MainActor
@Observable
final class SwipeViewModel {
    let session: TripSession

    var candidates: [CandidateCard] = []
    var currentIndex = 0
    var isLoading = false
    var isSubmittingVote = false
    var isPlanning = false
    var isShowingError = false
    var errorMessage = ""

    private let apiClient: APIClient
    private var hasLoaded = false

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var currentCandidate: CandidateCard? {
        guard candidates.indices.contains(currentIndex) else { return nil }
        return candidates[currentIndex]
    }

    var isComplete: Bool {
        hasLoaded && !candidates.isEmpty && currentIndex >= candidates.count
    }

    var progressText: String {
        guard !candidates.isEmpty else { return "No cards" }
        return "\(min(currentIndex + 1, candidates.count)) of \(candidates.count)"
    }

    func load() async {
        guard !hasLoaded else { return }
        isLoading = true
        defer { isLoading = false }

        do {
            candidates = try await apiClient.candidates(tripID: session.trip.id)
            hasLoaded = true
        } catch {
            show(error)
        }
    }

    func vote(_ signal: VoteSignal) async {
        guard let candidate = currentCandidate, !isSubmittingVote else { return }
        isSubmittingVote = true
        defer { isSubmittingVote = false }

        do {
            _ = try await apiClient.vote(
                tripID: session.trip.id,
                request: VoteRequest(
                    travelerID: session.travelerID,
                    candidateID: candidate.id,
                    signal: signal
                )
            )
            currentIndex += 1
        } catch {
            show(error)
        }
    }

    func plan() async -> UUID? {
        guard isComplete, !isPlanning else { return nil }
        isPlanning = true
        defer { isPlanning = false }

        do {
            _ = try await apiClient.plan(
                tripID: session.trip.id,
                request: session.planRequest
            )
            return session.trip.id
        } catch {
            show(error)
            return nil
        }
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
