import Foundation

struct TripInvite: Codable, Sendable, Hashable {
    let code: String
    let maxUses: Int
    let uses: Int
    let revoked: Bool

    enum CodingKeys: String, CodingKey {
        case code
        case maxUses = "max_uses"
        case uses
        case revoked
    }

    var usesRemaining: Int { max(0, maxUses - uses) }
}

struct InviteCreateRequest: Codable, Sendable {
    let maxUses: Int

    enum CodingKeys: String, CodingKey {
        case maxUses = "max_uses"
    }
}

/// What someone holding a code sees before they join. Deliberately thin: a
/// code is forwardable, so this must be safe to show whoever has one.
struct InvitePreview: Codable, Sendable {
    let trip: TripSummary
    let memberNames: [String]
    let usable: Bool
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case trip
        case memberNames = "member_names"
        case usable
        case reason
    }
}

struct JoinTripRequest: Codable, Sendable {
    let name: String?
    let preferenceTags: [String]
    let homeCity: String?

    enum CodingKeys: String, CodingKey {
        case name
        case preferenceTags = "preference_tags"
        case homeCity = "home_city"
    }
}

struct JoinTripResponse: Codable, Sendable {
    let trip: TripSummary
    let travelerID: UUID
    let alreadyMember: Bool

    enum CodingKeys: String, CodingKey {
        case trip
        case travelerID = "traveler_id"
        case alreadyMember = "already_member"
    }
}
