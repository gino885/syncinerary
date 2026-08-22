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

    enum CodingKeys: String, CodingKey {
        case id
        case type
        case nameCanonical
        case nameOriginalLang
        case latitude = "lat"
        case longitude = "lng"
        case area
        case address
        case category
        case priceTier
        case durationEstimateMin
        case dietaryTags
    }
}
