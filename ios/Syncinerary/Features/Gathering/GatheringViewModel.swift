import Foundation
import Observation

@MainActor
@Observable
final class GatheringViewModel {
    let session: TripSession
    var isGathering = false
    var errorMessage: String?
    var deckSize: Int?
    var run: GatherRunStatus?
    private let apiClient: APIClient

    init(session: TripSession, apiClient: APIClient = .shared) {
        self.session = session
        self.apiClient = apiClient
    }

    var cityName: String { run?.city ?? session.trip.destination }
    var phaseLabel: String {
        switch run?.phase {
        case "guide_baseline": String(localized: "Reading travel guides")
        case "social_search": String(localized: "Finding places from posts")
        case "place_verification": String(localized: "Checking places")
        case "deck_build": String(localized: "Preparing your places")
        default: String(localized: "Waiting to begin")
        }
    }

    /// Observation only. Starting and retrying a job belongs to the leader.
    func gather() async -> Bool {
        guard !isGathering else { return false }
        isGathering = true
        errorMessage = nil
        defer { isGathering = false }
        var delay = 2.0
        do {
            while !Task.isCancelled {
                let status = try await apiClient.gatherStatus(tripID: session.trip.id)
                run = status
                if status.status == "completed", let count = status.deckSize, count > 0 {
                    deckSize = count
                    return true
                }
                if status.status == "failed" || status.status == "completed" {
                    errorMessage = String(localized: "Your trip was created, but finding places failed. Ask the leader to retry from the group room.")
                    return false
                }
                try await Task.sleep(for: .seconds(delay))
                delay = min(10, delay * 1.5)
            }
        } catch is CancellationError {
            return false
        } catch {
            if !Task.isCancelled {
                errorMessage = String(localized: "Your trip is saved. Reconnect to check discovery progress.")
            }
        }
        return false
    }
}
