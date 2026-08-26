import Foundation

struct TripSession: Hashable, Sendable {
    let trip: TripSummary
    let travelerID: UUID
    let planRequest: PlanRequest
}
