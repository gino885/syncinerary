import Foundation

struct ManualItineraryRequest: Encodable, Sendable {
    let travelerID: UUID
    let baseVersionID: UUID
    let stops: [ItineraryDraftStop]
    let adjustDays: [Int]
    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id", baseVersionID = "base_version_id", stops, adjustDays = "adjust_days"
    }
}
