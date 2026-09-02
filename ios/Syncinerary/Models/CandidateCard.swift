import Foundation

struct CandidateCard: Decodable, Identifiable, Sendable {
    let id: UUID
    let type: String
    let nameCanonical: String
    let nameOriginalLang: String?
    let latitude: Double
    let longitude: Double
    let area: String?
    let address: String?
    let category: String?
    let priceTier: Int
    let durationEstimateMin: Int
    let dietaryTags: [String]
    let dietaryNotice: String?
    let description: String?
    let descriptionSource: String?
    let sourceBadges: [SourceBadge]
    let sourcePosts: [SourcePost]
    let delegateBadge: DelegateBadge?

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case nameCanonical = "name_canonical"
        case nameOriginalLang = "name_original_lang"
        case latitude = "lat"
        case longitude = "lng"
        case area
        case address
        case category
        case priceTier = "price_tier"
        case durationEstimateMin = "duration_estimate_min"
        case dietaryTags = "dietary_tags"
        case dietaryNotice = "dietary_notice"
        case description
        case descriptionSource = "description_source"
        case sourceBadges = "source_badges"
        case sourcePosts = "source_posts"
        case delegateBadge = "delegate_badge"
    }
}
