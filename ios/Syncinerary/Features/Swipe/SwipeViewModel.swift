import Foundation
import Observation

@MainActor
@Observable
final class SwipeViewModel {
    let session: TripSession

    var candidates: [CandidateCard] = []
    var currentIndex = 0
    var isLoading = false
    var isShowingError = false
    var errorMessage = ""
    /// Photos for the visible cards, fetched a few ahead so the next card
    /// never appears blank.
    var photos: [UUID: CandidatePhoto] = [:]
    var lastDecision: SwipeDecision?
    var decisionCount = 0

    private let apiClient: APIClient
    private var hasLoaded = false
    private var photoAttempts: Set<UUID> = []
    private let visibleCards = 3

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var currentCandidate: CandidateCard? {
        guard candidates.indices.contains(currentIndex) else { return nil }
        return candidates[currentIndex]
    }

    /// The card on top and the ones peeking out behind it.
    var upcoming: [CandidateCard] {
        guard candidates.indices.contains(currentIndex) else { return [] }
        return Array(candidates[currentIndex...].prefix(visibleCards))
    }

    var isComplete: Bool {
        hasLoaded && !candidates.isEmpty && currentIndex >= candidates.count
    }

    var showsHint: Bool {
        currentIndex < 2
    }

    var progressText: String {
        guard !candidates.isEmpty else { return "No cards" }
        return "Card \(min(currentIndex + 1, candidates.count)) of \(candidates.count)"
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
            await prefetchPhotos()
        } catch {
            show(error)
        }
    }

    /// The deck already moved on when this runs, so the vote posts in the
    /// background. A failure puts the card back rather than losing the vote.
    func decide(_ decision: SwipeDecision) async {
        guard let candidate = currentCandidate else { return }
        currentIndex += 1
        decisionCount += 1
        lastDecision = decision
        await prefetchPhotos()

        do {
            _ = try await apiClient.vote(
                tripID: session.trip.id,
                request: VoteRequest(
                    travelerID: session.travelerID,
                    candidateID: candidate.id,
                    signal: decision.voteSignal,
                    noteText: decision.noteText
                )
            )
        } catch {
            currentIndex = max(0, currentIndex - 1)
            show(error)
        }
    }

    private func prefetchPhotos() async {
        let pending = upcoming.filter { !photoAttempts.contains($0.id) }
        guard !pending.isEmpty else { return }
        for candidate in pending {
            photoAttempts.insert(candidate.id)
        }
        let tripID = session.trip.id
        let apiClient = apiClient
        await withTaskGroup(of: (UUID, CandidatePhoto?).self) { group in
            for candidate in pending {
                group.addTask {
                    (candidate.id, try? await apiClient.candidatePhoto(tripID: tripID, candidateID: candidate.id))
                }
            }
            for await (id, photo) in group {
                if let photo {
                    photos[id] = photo
                }
            }
        }
    }

    private func show(_ error: Error) {
        errorMessage = error.localizedDescription
        isShowingError = true
    }
}
