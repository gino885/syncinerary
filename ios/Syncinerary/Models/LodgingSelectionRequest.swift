import Foundation

struct LodgingSelectionRequest: Encodable, Sendable {
    let travelerID: UUID
    let candidateID: UUID

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case candidateID = "candidate_id"
    }
}
