import Foundation

/// Everything the app needs to come back to a trip: the trip, who this
/// traveler is on it, and the day window they chose. Stored locally so a
/// closed app can resume (see `RecentTripsStore`).
struct TripSession: Codable, Hashable, Sendable {
    let trip: TripSummary
    let travelerID: UUID
    let planRequest: PlanRequest
}
