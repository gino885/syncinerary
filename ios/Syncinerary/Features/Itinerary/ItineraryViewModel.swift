import Foundation
import Observation

@MainActor
@Observable
final class ItineraryViewModel {
    let session: TripSession

    var itinerary: ItineraryResponse?
    var pendingProposal: ReplanProposalResponse?
    var isLoading = false
    var isDeciding = false
    var liveUpdatesUnavailable = false
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

    func listenForReplans() async {
        while !Task.isCancelled {
            do {
                let proposal = try await apiClient.nextReplanProposal(
                    tripID: session.trip.id,
                    travelerID: session.travelerID
                )
                liveUpdatesUnavailable = false
                if proposal.status == .pending {
                    pendingProposal = proposal
                }
            } catch {
                guard !Task.isCancelled else { return }
                liveUpdatesUnavailable = true
                do {
                    try await Task.sleep(for: .seconds(3))
                } catch {
                    return
                }
            }
        }
    }

    func approve(_ proposal: ReplanProposalResponse) async -> Bool {
        await decide(proposal, approve: true)
    }

    func reject(_ proposal: ReplanProposalResponse) async -> Bool {
        await decide(proposal, approve: false)
    }

    private func decide(_ proposal: ReplanProposalResponse, approve: Bool) async -> Bool {
        isDeciding = true
        defer { isDeciding = false }

        do {
            if approve {
                _ = try await apiClient.approveReplan(
                    tripID: session.trip.id,
                    eventID: proposal.id,
                    travelerID: session.travelerID
                )
                await load()
            } else {
                _ = try await apiClient.rejectReplan(
                    tripID: session.trip.id,
                    eventID: proposal.id,
                    travelerID: session.travelerID
                )
            }
            pendingProposal = nil
            return true
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
            return false
        }
    }
}
