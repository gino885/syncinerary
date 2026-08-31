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
    var isShowingError = false
    var errorMessage = ""
    var currentPhoto: CandidatePhoto?

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
            candidates = try await apiClient.candidates(
                tripID: session.trip.id,
                travelerID: session.travelerID
            )
            hasLoaded = true
            await loadCurrentPhoto()
        } catch {
            show(error)
        }
    }

    func vote(_ signal: VoteSignal, noteText: String? = nil) async {
        guard let candidate = currentCandidate, !isSubmittingVote else { return }
        isSubmittingVote = true
        defer { isSubmittingVote = false }

        do {
            _ = try await apiClient.vote(
                tripID: session.trip.id,
                request: VoteRequest(
                    travelerID: session.travelerID,
                    candidateID: candidate.id,
                    signal: signal,
                    noteText: noteText
                )
            )
            currentIndex += 1
            await loadCurrentPhoto()
        } catch {
            show(error)
        }
    }

    private func loadCurrentPhoto() async {
        currentPhoto = nil
        guard let candidate = currentCandidate else { return }
        currentPhoto = try? await apiClient.candidatePhoto(
            tripID: session.trip.id,
            candidateID: candidate.id
        )
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
