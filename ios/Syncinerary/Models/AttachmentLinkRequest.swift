import Foundation

struct AttachmentLinkRequest: Encodable, Sendable {
    let travelerID: UUID
    let url: String
    let placeName: String?

    enum CodingKeys: String, CodingKey {
        case travelerID = "traveler_id"
        case url
        case placeName = "place_name"
    }
}
