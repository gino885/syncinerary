import Foundation

/// The unfurled card for a pasted post.
///
/// Either the place the post became, or the repair it needs. Both states are
/// one component, because they are one thing at two points in its life.
struct MessageLink: Codable, Sendable, Hashable {
    let attachmentID: UUID
    let platform: String
    let status: String
    let url: String?
    let placeName: String?
    let candidateID: UUID?
    let photoURL: String?
    let failureReason: String?

    enum CodingKeys: String, CodingKey {
        case attachmentID = "attachment_id"
        case platform
        case status
        case url
        case placeName = "place_name"
        case candidateID = "candidate_id"
        case photoURL = "photo_url"
        case failureReason = "failure_reason"
    }

    var isInTheDeck: Bool { placeName != nil }
    var needsPlaceName: Bool { failureReason == "needs_place_name" }

    /// Instagram, TikTok, RedNote. Shown so the card says where it came from
    /// without printing the URL.
    var platformLabel: String {
        switch platform {
        case "tiktok": "TikTok"
        case "instagram": "Instagram"
        case "rednote": "RedNote"
        default: platform.capitalized
        }
    }
}

struct NamePlaceRequest: Codable, Sendable {
    let placeName: String

    enum CodingKeys: String, CodingKey {
        case placeName = "place_name"
    }
}
