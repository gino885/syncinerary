import Foundation

struct ShortlistConfirmRequest: Encodable, Sendable {
    let travelerID: UUID

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
    }
}
