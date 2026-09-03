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

    /// Any failure is repairable by naming the place, so they share one state.
    /// Treating only `needs_place_name` as repairable left the others falling
    /// through to "reading the post", which was not true and not actionable.
    var needsPlaceName: Bool { status == "failed" }

    /// What went wrong, in words the person who pasted it can act on.
    var failureLine: String {
        switch failureReason {
        case "place_not_found_in_trip_cities":
            "That one isn't in this trip's cities"
        case "no_place_named_in_post":
            "This \(platformLabel) post doesn't name a place"
        default:
            "\(platformLabel) won't open to us"
        }
    }

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
