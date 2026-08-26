import Foundation

struct TripCreatedResponse: Decodable, Sendable {
    let trip: TripSummary
    let travelerID: UUID

    enum CodingKeys: String, CodingKey {
        case trip
        case travelerID = "traveler_id"
    }
}
