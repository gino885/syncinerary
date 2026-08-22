import Foundation

struct TripCreatedResponse: Decodable, Sendable {
    let trip: TripSummary
    let travelerID: UUID
}
