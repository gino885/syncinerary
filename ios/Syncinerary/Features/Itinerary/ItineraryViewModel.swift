import Foundation
import Observation

@MainActor
@Observable
final class ItineraryViewModel {
    let session: TripSession

    var itinerary: ItineraryResponse?
    var pendingProposal: ReplanProposalResponse?
    var isShowingReplan = false
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
            await recoverPendingReplan()
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
        }
    }

    func listenForReplans() async {
        await recoverPendingReplan()
        while !Task.isCancelled {
            do {
                let proposal = try await apiClient.nextReplanProposal(
                    tripID: session.trip.id,
                    travelerID: session.travelerID
                )
                liveUpdatesUnavailable = false
                if proposal.status == .pending {
                    pendingProposal = proposal
                    isShowingReplan = true
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

    func showPendingReplan() {
        isShowingReplan = pendingProposal != nil
    }

    private func recoverPendingReplan() async {
        guard pendingProposal == nil else { return }
        do {
            if let proposal = try await apiClient.pendingReplans(
                tripID: session.trip.id,
                travelerID: session.travelerID
            ).first {
                pendingProposal = proposal
                isShowingReplan = true
            }
        } catch {
            liveUpdatesUnavailable = true
        }
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
            isShowingReplan = false
            return true
        } catch {
            errorMessage = error.localizedDescription
            isShowingError = true
            return false
        }
    }
}
