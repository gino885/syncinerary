import Foundation

struct SourceBadge: Decodable, Hashable, Sendable {
    let kind: String
    let label: String
    /// What the badge claims: where the place came from, or why this group is
    /// being shown it. They share this row on the card, but they are not the
    /// same fact, and only provenance has somewhere outward to point.
    let category: String?
    let contributorName: String?
    /// The public origin of this provenance, when it has one (CLAUDE.md 8.5).
    /// A badge without a URL is plain text; never a search page, never guessed.
    let url: String?
    let platform: String?
    /// Which searches turned this place up. Set on the recommendation badge
    /// only, for the card details.
    let discoveryIntents: [String]?

    var isRecommendation: Bool { category == "recommendation" }

    var linkURL: URL? {
        guard let url else { return nil }
        return URL(string: url)
    }

    /// Names the destination so VoiceOver says what a tap does.
    var accessibilityLabel: String {
        guard linkURL != nil else { return label }
        if platform == "Google Maps" {
            return "\(label), opens Google Maps"
        }
        return "\(label), opens the post"
    }

    enum CodingKeys: String, CodingKey {
        case kind
        case label
        case category
        case contributorName = "contributor_name"
        case url
        case platform
        case discoveryIntents = "discovery_intents"
    }
}
