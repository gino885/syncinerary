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

    /// Localized app-owned badge wording. Platform and contributor names stay
    /// verbatim because they are names, not interface copy.
    var localizedLabel: String {
        switch kind {
        case "discovered": String(localized: "Google Maps")
        case "trending": platform ?? String(localized: "Trending")
        case "classic": String(localized: "Classic")
        case "attached_by_you": String(localized: "You added this")
        case "for_you": String(localized: "For You")
        default: contributorName.map { String(localized: "From \($0)") } ?? label
        }
    }

    private var localizedAccessibilityBaseLabel: String {
        switch kind {
        case "discovered": String(localized: "Found on Google Maps")
        case "trending": platform.map { String(localized: "Trending on \($0)") } ?? label
        case "attached_by_you": String(localized: "Attached by you")
        case "attached_by_group": contributorName.map { String(localized: "From \($0)") } ?? label
        case "classic": String(localized: "Classic")
        case "for_you": String(localized: "For You")
        default: label
        }
    }

    /// Names the destination so VoiceOver says what a tap does.
    var accessibilityLabel: String {
        let baseLabel = localizedAccessibilityBaseLabel
        guard linkURL != nil else { return baseLabel }
        if platform == "Google Maps" {
            return String(localized: "\(baseLabel), opens Google Maps")
        }
        return String(localized: "\(baseLabel), opens the post")
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
